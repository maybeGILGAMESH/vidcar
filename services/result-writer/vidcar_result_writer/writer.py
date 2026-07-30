"""Single transactional, idempotent result publication path."""
from __future__ import annotations

import json
import os

from celery import Celery
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.common.integrity import (
    ChecksumMismatch,
    manifest_sha256,
    verify_sha256,
)
from packages.common.storage import Boto3ObjectStorage, ObjectStorage
from packages.contracts.models import JobState, ProcessingManifest
from packages.schemas.db import ProcessingJob, ProcessingResult, Video


class ResultConflict(RuntimeError):
    pass


def publish_manifest(db: Session, storage: ObjectStorage, manifest: ProcessingManifest) -> list[ProcessingResult]:
    job = db.get(ProcessingJob, str(manifest.job_id))
    if job is None:
        raise LookupError(f"job {manifest.job_id} does not exist")
    video = db.get(Video, str(manifest.video_id))
    if video is None or job.video_id != str(manifest.video_id):
        raise ResultConflict("manifest video does not match job")
    if job.pipeline_version != manifest.pipeline_version or video.pipeline_version != manifest.pipeline_version:
        raise ResultConflict("manifest pipeline version does not match job")

    payload = manifest.model_dump(mode="json")
    digest = manifest_sha256(payload)
    for artifact in manifest.artifacts:
        allowed_prefixes = (
            f"results/{manifest.video_id}/{manifest.pipeline_version}/",
            f"derived/{manifest.video_id}/{manifest.pipeline_version}/",
        )
        if not artifact.object_key.startswith(allowed_prefixes):
            raise ResultConflict(f"artifact key is outside immutable result prefixes: {artifact.object_key}")
        info = storage.head(artifact.bucket, artifact.object_key)
        if int(info["ContentLength"]) != artifact.size_bytes:
            raise ResultConflict(f"artifact size mismatch: {artifact.object_key}")
        try:
            verify_sha256(storage.iter_bytes(artifact.bucket, artifact.object_key), artifact.sha256)
        except ChecksumMismatch as exc:
            raise ResultConflict(str(exc)) from exc

    existing = db.scalars(
        select(ProcessingResult).where(
            ProcessingResult.video_id == str(manifest.video_id),
            ProcessingResult.pipeline_version == manifest.pipeline_version,
        )
    ).all()
    if existing:
        expected = {
            artifact.result_type: (artifact.object_key, artifact.sha256) for artifact in manifest.artifacts
        }
        actual = {row.result_type: (row.object_key, row.sha256) for row in existing}
        if actual != expected or any(row.manifest_sha256 != digest for row in existing):
            raise ResultConflict("a different result was already published")
        return existing

    if job.state not in {
        JobState.awaiting_finalize.value,
        JobState.uploading_results.value,
    }:
        raise ResultConflict(f"job cannot be finalized from state {job.state}")
    rows = [
        ProcessingResult(
            video_id=str(manifest.video_id),
            pipeline_version=manifest.pipeline_version,
            result_type=artifact.result_type,
            bucket=artifact.bucket,
            object_key=artifact.object_key,
            sha256=artifact.sha256.lower(),
            size_bytes=artifact.size_bytes,
            summary=manifest.summary,
            manifest_sha256=digest,
        )
        for artifact in manifest.artifacts
    ]
    db.add_all(rows)
    job.state = JobState.completed.value
    video.state = JobState.completed.value
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.scalars(
            select(ProcessingResult).where(
                ProcessingResult.video_id == str(manifest.video_id),
                ProcessingResult.pipeline_version == manifest.pipeline_version,
            )
        ).all()
        actual = {row.result_type: (row.object_key, row.sha256) for row in concurrent}
        expected = {
            artifact.result_type: (artifact.object_key, artifact.sha256.lower())
            for artifact in manifest.artifacts
        }
        if actual != expected:
            raise ResultConflict("concurrent publication produced a different result")
        return concurrent
    return rows


celery_app = Celery(
    "vidcar-result-writer",
    broker=os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"),
)
celery_app.conf.update(task_acks_late=True, task_reject_on_worker_lost=True)


@celery_app.task(
    name="vidcar.finalize_result",
    autoretry_for=(ConnectionError,),
    retry_backoff=True,
    max_retries=10,
)
def finalize_result_task(manifest_bucket: str, manifest_key: str, expected_sha256: str) -> dict:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    storage = Boto3ObjectStorage(
        endpoint_url=os.environ["S3_ENDPOINT"],
        region_name=os.getenv("S3_REGION"),
        aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY"),
    )
    chunks = list(storage.iter_bytes(manifest_bucket, manifest_key))
    verify_sha256(chunks, expected_sha256)
    manifest = ProcessingManifest.model_validate(json.loads(b"".join(chunks)))
    factory = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True))
    with factory() as db:
        rows = publish_manifest(db, storage, manifest)
        return {"video_id": str(manifest.video_id), "result_ids": [row.id for row in rows]}
