"""Metadata probe before a job is routed to a GPU consumer."""
from __future__ import annotations

import os

from celery import Celery
from sqlalchemy.orm import Session

from packages.common.storage import Boto3ObjectStorage, ObjectStorage
from packages.contracts.models import JobState
from packages.schemas.db import ProcessingJob, Video


celery_app = Celery(
    "vidcar-probe",
    broker=os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"),
)
celery_app.conf.update(task_acks_late=True, task_reject_on_worker_lost=True)


def probe_job(db: Session, storage: ObjectStorage, job_id: str, send_task) -> dict:
    job = db.get(ProcessingJob, job_id)
    if job is None:
        raise LookupError(f"job {job_id} does not exist")
    if job.state != JobState.queued.value:
        return {"job_id": job_id, "state": job.state, "dispatched": False}
    video = db.get(Video, job.video_id)
    if video is None:
        raise LookupError(f"video {job.video_id} does not exist")
    info = storage.head(video.object_bucket, video.object_key)
    if int(info["ContentLength"]) != video.size_bytes:
        job.state = JobState.failed_terminal.value
        job.error = "original object size mismatch"
        db.commit()
        raise ValueError(job.error)
    metadata = info.get("Metadata", {})
    metadata_checksum = metadata.get("sha256")
    if metadata_checksum and metadata_checksum.lower() != video.sha256.lower():
        job.state = JobState.failed_terminal.value
        job.error = "original object checksum metadata mismatch"
        db.commit()
        raise ValueError(job.error)
    send_task(
        "vidcar.process_video",
        args=[job.id, video.id, video.object_bucket, video.object_key, job.pipeline_version],
        queue="gpu",
    )
    return {"job_id": job.id, "state": job.state, "dispatched": True}


@celery_app.task(name="vidcar.probe_video", autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=5)
def probe_video_task(job_id: str) -> dict:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    storage = Boto3ObjectStorage(
        endpoint_url=os.environ["S3_ENDPOINT"],
        region_name=os.getenv("S3_REGION"),
        aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY"),
    )
    factory = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True))
    with factory() as db:
        return probe_job(db, storage, job_id, celery_app.send_task)
