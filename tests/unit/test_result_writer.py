import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from packages.common.storage import MemoryObjectStorage
from packages.contracts.models import ArtifactManifest, JobState, ProcessingManifest
from packages.schemas.db import Base, ProcessingJob, ProcessingResult, Survey, User, Video
from vidcar_result_writer.writer import ResultConflict, publish_manifest


def make_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_manifest_publication_is_idempotent_and_atomic():
    db = make_session()
    user = User(id="writer-test")
    survey = Survey(
        owner_id=user.id, latitude=1, longitude=2, gps_accuracy_m=3
    )
    db.add_all([user, survey])
    db.flush()
    video_id, job_id = str(uuid4()), str(uuid4())
    video = Video(
        id=video_id,
        survey_id=survey.id,
        owner_id=user.id,
        filename="v.mp4",
        content_type="video/mp4",
        size_bytes=1,
        sha256="0" * 64,
        object_bucket="vehicle-originals",
        object_key=f"originals/{video_id}/v.mp4",
        state=JobState.awaiting_finalize.value,
        pipeline_version="pipeline-1",
    )
    job = ProcessingJob(
        id=job_id,
        video_id=video_id,
        pipeline_version="pipeline-1",
        state=JobState.awaiting_finalize.value,
    )
    db.add_all([video, job])
    db.commit()

    storage = MemoryObjectStorage()
    data = b'{"count": 1}'
    key = f"results/{video_id}/pipeline-1/report.json"
    storage.put_object("vehicle-results", key, data)
    artifact = ArtifactManifest(
        result_type="report",
        bucket="vehicle-results",
        object_key=key,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        content_type="application/json",
    )
    manifest = ProcessingManifest(
        job_id=job_id,
        video_id=video_id,
        pipeline_version="pipeline-1",
        worker_id="gpu-01",
        produced_at=datetime.now(timezone.utc),
        artifacts=[artifact],
        summary={"count": 1},
    )

    first = publish_manifest(db, storage, manifest)
    second = publish_manifest(db, storage, manifest)
    assert first[0].id == second[0].id
    assert db.scalar(select(func.count()).select_from(ProcessingResult)) == 1
    assert db.get(ProcessingJob, job_id).state == JobState.completed.value
    assert db.get(Video, video_id).state == JobState.completed.value

    changed = manifest.model_copy(
        update={"summary": {"count": 2}}
    )
    # Summary is covered by the canonical manifest hash, so a replay with altered
    # content cannot masquerade as the already-published result.
    with pytest.raises(ResultConflict):
        publish_manifest(db, storage, changed)
