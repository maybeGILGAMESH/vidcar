from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from packages.contracts.models import JobState
from packages.schemas.db import Base, ProcessingJob, Survey, User, Video
from vidcar_scheduler.app import claim_next_job, recover_expired_jobs


def test_claims_distinct_jobs_and_requeues_failure():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(id="recovery-user")
        survey = Survey(owner_id=user.id, latitude=1, longitude=2, gps_accuracy_m=1)
        db.add_all([user, survey])
        db.flush()
        for index in range(2):
            video = Video(
                survey_id=survey.id,
                owner_id=user.id,
                filename=f"{index}.mp4",
                content_type="video/mp4",
                size_bytes=1,
                sha256="0" * 64,
                object_bucket="originals",
                object_key=f"originals/{index}",
                state=JobState.queued.value,
                pipeline_version="p1",
            )
            db.add(video)
            db.flush()
            db.add(
                ProcessingJob(
                    video_id=video.id,
                    pipeline_version="p1",
                    state=JobState.queued.value,
                )
            )
        db.commit()

        first = claim_next_job(db, "gpu-1")
        second = claim_next_job(db, "gpu-2")
        assert first.id != second.id
        first.state = JobState.failed_retryable.value
        first.lease_expires_at = None
        db.commit()
        assert recover_expired_jobs(db, datetime.now(timezone.utc)) == 1
        assert db.get(ProcessingJob, first.id).state == JobState.queued.value
