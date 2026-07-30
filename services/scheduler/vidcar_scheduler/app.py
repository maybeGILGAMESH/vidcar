"""Celery routing and recovery scheduler."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from celery import Celery
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.contracts.models import JobState
from packages.schemas.db import ProcessingJob, Video


celery_app = Celery(
    "vidcar-scheduler",
    broker=os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"),
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "vidcar.probe_video": {"queue": "probe"},
        "vidcar.process_video": {"queue": "gpu"},
        "vidcar.finalize_result": {"queue": "result-writer"},
        "vidcar.recover_expired_jobs": {"queue": "scheduler"},
    },
    beat_schedule={
        "recover-expired-jobs": {
            "task": "vidcar.recover_expired_jobs",
            "schedule": 30.0,
        }
    },
)


def claim_next_job(db: Session, worker_id: str, lease_seconds: int = 300) -> ProcessingJob | None:
    """Atomically claims one queued job; PostgreSQL uses SKIP LOCKED."""
    statement = (
        select(ProcessingJob)
        .where(ProcessingJob.state == JobState.queued.value)
        .order_by(ProcessingJob.priority.desc(), ProcessingJob.created_at)
        .limit(1)
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    job = db.scalar(statement)
    if job is None:
        return None
    job.transition_to(JobState.claimed)
    job.claimed_by = worker_id
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
    db.commit()
    return job


def recover_expired_jobs(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    jobs = db.scalars(
        select(ProcessingJob).where(
            ProcessingJob.state.in_(
                [
                    JobState.claimed.value,
                    JobState.processing.value,
                    JobState.failed_retryable.value,
                ]
            )
        )
    ).all()
    recovered = 0
    for job in jobs:
        expired = job.lease_expires_at is None or job.lease_expires_at < now
        if job.state == JobState.failed_retryable.value or expired:
            if job.state != JobState.failed_retryable.value:
                job.state = JobState.failed_retryable.value
            job.transition_to(JobState.queued)
            job.claimed_by = None
            job.lease_expires_at = None
            video = db.get(Video, job.video_id)
            if video and video.state not in {
                JobState.completed.value,
                JobState.cancelled.value,
                JobState.failed_terminal.value,
            }:
                video.state = JobState.queued.value
            recovered += 1
    db.commit()
    return recovered


@celery_app.task(name="vidcar.recover_expired_jobs")
def recover_expired_jobs_task() -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    database_url = os.environ["DATABASE_URL"]
    factory = sessionmaker(bind=create_engine(database_url, pool_pre_ping=True))
    with factory() as db:
        return recover_expired_jobs(db)
