"""Celery GPU consumer: decode → detect/track → publish results for finalize."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from celery import Celery
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.common.integrity import canonical_manifest_bytes, manifest_sha256
from packages.common.storage import Boto3ObjectStorage
from packages.contracts.models import ArtifactManifest, JobState, ProcessingManifest
from packages.schemas.db import ProcessingJob, Video

celery_app = Celery(
    "vidcar-gpu",
    broker=os.getenv("CELERY_BROKER_URL") or os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//"),
)
celery_app.conf.update(task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1)


def _storage() -> Boto3ObjectStorage:
    return Boto3ObjectStorage(
        endpoint_url=os.environ["S3_ENDPOINT"],
        region_name=os.getenv("S3_REGION"),
        aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID") or os.getenv("S3_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY") or os.getenv("S3_SECRET_KEY"),
    )


def _db_factory():
    return sessionmaker(bind=create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True))


def _put_file(
    storage: Boto3ObjectStorage,
    bucket: str,
    key: str,
    path: Path,
    *,
    result_type: str,
    content_type: str,
) -> ArtifactManifest:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    storage.put_object(bucket, key, data, metadata={"sha256": digest})
    return ArtifactManifest(
        result_type=result_type,
        bucket=bucket,
        object_key=key,
        size_bytes=len(data),
        sha256=digest,
        content_type=content_type,
    )


def _fail(job_id: str, video_id: str, message: str) -> None:
    factory = _db_factory()
    with factory() as db:
        job = db.get(ProcessingJob, job_id)
        video = db.get(Video, video_id)
        if job and job.state not in {JobState.completed.value, JobState.failed_terminal.value, JobState.cancelled.value}:
            try:
                if job.state in {JobState.queued.value, JobState.claimed.value, JobState.processing.value, JobState.uploading_results.value}:
                    job.transition_to(JobState.failed_retryable)
                else:
                    job.state = JobState.failed_retryable.value
            except Exception:
                job.state = JobState.failed_retryable.value
            job.error = message[:2000]
        if video and video.state not in {JobState.completed.value, JobState.failed_terminal.value, JobState.cancelled.value}:
            try:
                video.transition_to(JobState.failed_retryable)
            except Exception:
                video.state = JobState.failed_retryable.value
        db.commit()


def _move_job_video(db, job: ProcessingJob, video: Video, target: JobState, *, worker_id: str | None = None) -> None:
    """Advance job+video through allowed hops until target (or raise)."""
    hops = {
        JobState.queued: JobState.claimed,
        JobState.claimed: JobState.processing,
        JobState.processing: JobState.uploading_results,
        JobState.uploading_results: JobState.awaiting_finalize,
        JobState.awaiting_finalize: JobState.completed,
        JobState.failed_retryable: JobState.queued,
    }
    guard = 0
    while job.state != target.value:
        current = JobState(job.state)
        nxt = hops.get(current)
        if nxt is None:
            raise RuntimeError(f"cannot advance job from {job.state} toward {target.value}")
        job.transition_to(nxt)
        if video.state == current.value:
            video.transition_to(nxt)
        elif video.state != nxt.value and video.state != target.value:
            # Keep video aligned when it lags one step behind / matches job.
            try:
                video.transition_to(nxt)
            except Exception:
                if JobState(video.state) in hops and hops[JobState(video.state)] == nxt:
                    video.transition_to(nxt)
                else:
                    raise
        if nxt == JobState.claimed and worker_id:
            job.claimed_by = worker_id
            lease_s = int(os.getenv("GPU_LEASE_SECONDS", "3600"))
            job.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=lease_s)
        if nxt == target:
            break
        guard += 1
        if guard > 8:
            raise RuntimeError(f"state advance loop stuck at {job.state}")
    db.commit()
    db.refresh(job)
    db.refresh(video)
    if job.state != target.value:
        raise RuntimeError(f"expected job state {target.value}, got {job.state}")


@celery_app.task(name="vidcar.process_video", bind=True, max_retries=2)
def process_video_task(
    self,
    job_id: str,
    video_id: str,
    object_bucket: str,
    object_key: str,
    pipeline_version: str,
) -> dict:
    from gpu_worker.demo import run_visual_demo

    worker_id = os.getenv("WORKER_ID", "gpu-main")
    results_bucket = os.getenv("S3_RESULTS_BUCKET", "vehicle-results")
    scratch = Path(os.getenv("SCRATCH_ROOT", "/srv/vehicle-ai/scratch")) / worker_id / str(job_id)
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    storage = _storage()
    factory = _db_factory()
    job_id = str(job_id)
    video_id = str(video_id)

    try:
        with factory() as db:
            job = db.get(ProcessingJob, job_id)
            video = db.get(Video, video_id)
            if job is None or video is None:
                raise LookupError(f"job/video missing job={job_id} video={video_id}")
            if job.state == JobState.failed_retryable.value:
                job.transition_to(JobState.queued)
                if video.state == JobState.failed_retryable.value:
                    video.transition_to(JobState.queued)
                db.commit()
            _move_job_video(db, job, video, JobState.processing, worker_id=worker_id)

        source = scratch / Path(object_key).name
        with source.open("wb") as out:
            for chunk in storage.iter_bytes(object_bucket, object_key):
                out.write(chunk)

        output_dir = scratch / "out"
        output_dir.mkdir(exist_ok=True)

        backend = os.getenv("DETECTOR_BACKEND", "paddle").strip().lower()
        approved_root = Path(os.getenv("MODEL_APPROVED_ROOT", "/opt/vehicle-ai/model-registry/approved"))
        manifest_path = Path(
            os.getenv("MODEL_MANIFEST", "/app/models/manifests/vehicle-pipeline-0.1.0.yaml")
        )
        raw_frames = os.getenv("GPU_MAX_FRAMES", os.getenv("GPU_DEMO_MAX_FRAMES", "180")).strip().lower()
        max_frames = None if raw_frames in {"", "0", "none", "all"} else int(raw_frames)
        if backend == "paddle":
            if not approved_root.is_dir():
                raise RuntimeError(f"approved model root missing: {approved_root}")
            if not manifest_path.is_file():
                raise RuntimeError(f"pipeline manifest missing: {manifest_path}")

        summary = run_visual_demo(
            source,
            output_dir,
            backend=backend,
            ocr_mode=os.getenv("OCR_MODE", "latin"),
            max_frames=max_frames,
            gif_fps=float(os.getenv("GPU_GIF_FPS", "3")),
            approved_root=approved_root if backend == "paddle" else None,
            manifest=manifest_path if backend == "paddle" else None,
        )
        result_json = Path(summary["manifest"])
        annotated = Path(summary["annotated_video"])
        if backend == "paddle" and not str(summary.get("detector_backend", "")).startswith("paddle"):
            raise RuntimeError(
                f"expected paddle ensemble, got detector_backend={summary.get('detector_backend')!r}"
            )

        prefix = f"results/{video_id}/{pipeline_version}"
        with factory() as db:
            job = db.get(ProcessingJob, job_id)
            video = db.get(Video, video_id)
            assert job and video
            _move_job_video(db, job, video, JobState.uploading_results)

        artifacts = [
            _put_file(
                storage,
                results_bucket,
                f"{prefix}/result.json",
                result_json,
                result_type="result_json",
                content_type="application/json",
            )
        ]
        if annotated.is_file() and annotated.stat().st_size > 0:
            artifacts.append(
                _put_file(
                    storage,
                    results_bucket,
                    f"{prefix}/annotated.mp4",
                    annotated,
                    result_type="annotated_video",
                    content_type="video/mp4",
                )
            )

        summary_payload = json.loads(result_json.read_text(encoding="utf-8"))
        manifest = ProcessingManifest(
            job_id=UUID(job_id),
            video_id=UUID(video_id),
            pipeline_version=pipeline_version,
            worker_id=worker_id,
            produced_at=datetime.now(timezone.utc),
            artifacts=artifacts,
            summary={
                "crossing_count": summary_payload.get("crossing_count"),
                "frames_processed": summary_payload.get("frames_processed"),
                "detector_backend": summary_payload.get("detector_backend"),
                "tracks": len(summary_payload.get("tracks") or []),
            },
            models={"detector": str(summary_payload.get("detector_backend", "opencv"))},
        )
        payload = manifest.model_dump(mode="json")
        manifest_bytes = canonical_manifest_bytes(payload)
        digest = manifest_sha256(payload)
        manifest_key = f"{prefix}/manifest.json"
        storage.put_object(results_bucket, manifest_key, manifest_bytes, metadata={"sha256": digest})

        with factory() as db:
            job = db.get(ProcessingJob, job_id)
            video = db.get(Video, video_id)
            assert job and video
            _move_job_video(db, job, video, JobState.awaiting_finalize)

        celery_app.send_task(
            "vidcar.finalize_result",
            args=[results_bucket, manifest_key, digest],
            queue="result-writer",
        )
        return {"job_id": job_id, "video_id": video_id, "manifest_key": manifest_key, "sha256": digest}
    except Exception as exc:
        _fail(job_id, video_id, str(exc))
        raise
