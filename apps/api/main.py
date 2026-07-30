"""FastAPI control plane for uploads and processing results."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

try:
    from .database import build_engine, build_session_factory
except ImportError:  # supports ``uvicorn main:app`` from apps/api
    from database import build_engine, build_session_factory

from packages.common.external_database import StubExternalDatabaseAdapter
from packages.common.integrity import ChecksumMismatch, verify_sha256
from packages.common.storage import Boto3ObjectStorage, MemoryObjectStorage, ObjectStorage
from packages.contracts.models import (
    ArtifactManifest,
    CompleteUpload,
    ExternalDatabaseHealth,
    JobState,
    ProcessingResultOut,
    SurveyCreate,
    SurveyOut,
    UploadSessionCreate,
    UploadSessionOut,
    VideoOut,
)
from packages.schemas.db import (
    AuditLog,
    Base,
    ProcessingJob,
    ProcessingResult,
    Survey,
    SurveyNote,
    User,
    Video,
)


@dataclass(frozen=True)
class ApiSettings:
    originals_bucket: str = os.getenv("S3_ORIGINALS_BUCKET", "vehicle-originals")
    pipeline_version: str = os.getenv("PIPELINE_VERSION", "vehicle-pipeline-0.1.0")
    presign_expires_seconds: int = int(os.getenv("S3_PRESIGN_EXPIRES", "3600"))
    auto_create_schema: bool = os.getenv("AUTO_CREATE_SCHEMA", "false").lower() == "true"


class TaskSender:
    def send_probe(self, job_id: str) -> None:
        try:
            from celery import Celery
        except ImportError as exc:
            raise RuntimeError("Celery is required for the production task sender") from exc
        broker = os.environ["CELERY_BROKER_URL"]
        Celery("vidcar", broker=broker).send_task(
            "vidcar.probe_video", args=[job_id], queue="probe"
        )


class NullTaskSender:
    """Local adapter; persisted queued jobs can be picked up by the scheduler."""

    def send_probe(self, job_id: str) -> None:
        return None


def _default_storage() -> ObjectStorage:
    endpoint = os.getenv("S3_ENDPOINT")
    if not endpoint or endpoint == "replace_me":
        return MemoryObjectStorage()
    return Boto3ObjectStorage(
        endpoint_url=endpoint,
        region_name=os.getenv("S3_REGION"),
        aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY"),
    )


def create_app(
    *,
    database_url: str | None = None,
    storage: ObjectStorage | None = None,
    task_sender=None,
    external_adapter=None,
    create_schema: bool | None = None,
) -> FastAPI:
    settings = ApiSettings()
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    app = FastAPI(title="Vehicle Video API", version="0.1.0")
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.storage = storage or _default_storage()
    app.state.task_sender = (
        task_sender
        if task_sender is not None
        else (TaskSender() if os.getenv("CELERY_BROKER_URL") else NullTaskSender())
    )
    app.state.external_adapter = external_adapter or StubExternalDatabaseAdapter()

    if create_schema if create_schema is not None else settings.auto_create_schema:
        Base.metadata.create_all(engine)

    def get_db(request: Request):
        with request.app.state.session_factory() as session:
            yield session

    def current_user(
        db: Session = Depends(get_db),
        x_user_id: str | None = Header(default=None),
        x_user_email: str | None = Header(default=None),
    ) -> User:
        if not x_user_id:
            raise HTTPException(status_code=401, detail="X-User-ID is required (OIDC proxy subject)")
        user = db.get(User, x_user_id)
        if user is None:
            user = User(id=x_user_id, email=x_user_email)
            db.add(user)
            db.commit()
        return user

    def audit(db: Session, actor: str, action: str, resource_type: str, resource_id: str, **payload):
        db.add(
            AuditLog(
                actor_id=actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                payload=payload,
            )
        )

    def owned_video(db: Session, video_id: UUID, user: User) -> Video:
        video = db.get(Video, str(video_id))
        if video is None:
            raise HTTPException(status_code=404, detail="video not found")
        if video.owner_id != user.id:
            raise HTTPException(status_code=403, detail="video belongs to another user")
        return video

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/v1/surveys", response_model=SurveyOut, status_code=status.HTTP_201_CREATED)
    def create_survey(payload: SurveyCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
        survey = Survey(
            owner_id=user.id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            gps_accuracy_m=payload.gps_accuracy_m,
            camera_direction_deg=payload.camera_direction_deg,
        )
        db.add(survey)
        db.flush()
        for note in payload.notes:
            db.add(SurveyNote(survey_id=survey.id, video_id=str(note.video_id) if note.video_id else None, text=note.text))
        audit(db, user.id, "survey.create", "survey", survey.id)
        db.commit()
        return SurveyOut(
            id=survey.id,
            owner_id=user.id,
            latitude=survey.latitude,
            longitude=survey.longitude,
            gps_accuracy_m=survey.gps_accuracy_m,
            camera_direction_deg=survey.camera_direction_deg,
            notes=payload.notes,
            created_at=survey.created_at,
        )

    @app.post(
        "/api/v1/videos/upload-sessions",
        response_model=UploadSessionOut,
        status_code=status.HTTP_201_CREATED,
    )
    def create_upload(
        payload: UploadSessionCreate,
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(current_user),
    ):
        survey = db.get(Survey, str(payload.survey_id))
        if survey is None:
            raise HTTPException(status_code=404, detail="survey not found")
        if survey.owner_id != user.id:
            raise HTTPException(status_code=403, detail="survey belongs to another user")
        video = Video(
            survey_id=survey.id,
            owner_id=user.id,
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
            sha256=payload.sha256.lower(),
            object_bucket=settings.originals_bucket,
            object_key="pending",
            pipeline_version=settings.pipeline_version,
        )
        db.add(video)
        db.flush()
        video.object_key = f"originals/{video.id}/{payload.filename}"
        try:
            upload_id = request.app.state.storage.create_multipart(
                video.object_bucket,
                video.object_key,
                video.content_type,
                {"sha256": video.sha256, "video-id": video.id},
            )
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        video.multipart_upload_id = upload_id
        video.transition_to(JobState.uploading)
        count = math.ceil(payload.size_bytes / payload.part_size_bytes)
        if count > 10_000:
            raise HTTPException(status_code=422, detail="multipart upload exceeds 10,000 parts")
        urls = [
            {
                "part_number": part,
                "url": request.app.state.storage.presign_part(
                    video.object_bucket,
                    video.object_key,
                    upload_id,
                    part,
                    settings.presign_expires_seconds,
                ),
            }
            for part in range(1, count + 1)
        ]
        audit(db, user.id, "video.upload.start", "video", video.id)
        db.commit()
        return UploadSessionOut(
            video_id=video.id,
            upload_id=upload_id,
            object_key=video.object_key,
            part_size_bytes=payload.part_size_bytes,
            part_urls=urls,
        )

    @app.post("/api/v1/videos/{video_id}/complete-upload", response_model=VideoOut)
    def complete_upload(
        video_id: UUID,
        payload: CompleteUpload,
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(current_user),
    ):
        video = owned_video(db, video_id, user)
        if video.state != JobState.uploading.value or not video.multipart_upload_id:
            raise HTTPException(status_code=409, detail="video is not uploading")
        parts = [{"PartNumber": part.part_number, "ETag": part.etag} for part in payload.parts]
        request.app.state.storage.complete_multipart(
            video.object_bucket, video.object_key, video.multipart_upload_id, parts
        )
        info = request.app.state.storage.head(video.object_bucket, video.object_key)
        if int(info["ContentLength"]) != video.size_bytes:
            raise HTTPException(status_code=422, detail="uploaded size does not match")
        try:
            verify_sha256(
                request.app.state.storage.iter_bytes(video.object_bucket, video.object_key),
                video.sha256,
            )
        except ChecksumMismatch as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        video.transition_to(JobState.uploaded)
        video.transition_to(JobState.queued)
        job = ProcessingJob(
            video_id=video.id,
            pipeline_version=video.pipeline_version,
            state=JobState.queued.value,
        )
        db.add(job)
        audit(db, user.id, "video.upload.complete", "video", video.id, job_id=job.id)
        db.commit()
        request.app.state.task_sender.send_probe(job.id)
        return _video_out(video)

    @app.get("/api/v1/videos/{video_id}", response_model=VideoOut)
    def get_video(video_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
        return _video_out(owned_video(db, video_id, user))

    @app.get("/api/v1/videos/{video_id}/result", response_model=ProcessingResultOut)
    def get_result(video_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
        video = owned_video(db, video_id, user)
        rows = db.scalars(
            select(ProcessingResult).where(
                ProcessingResult.video_id == video.id,
                ProcessingResult.pipeline_version == video.pipeline_version,
            )
        ).all()
        if not rows:
            raise HTTPException(status_code=404, detail="result is not ready")
        artifacts = [
            ArtifactManifest(
                result_type=row.result_type,
                bucket=row.bucket,
                object_key=row.object_key,
                size_bytes=row.size_bytes,
                sha256=row.sha256,
            )
            for row in rows
        ]
        return ProcessingResultOut(
            video_id=video.id,
            pipeline_version=video.pipeline_version,
            summary=rows[0].summary,
            artifacts=artifacts,
            completed_at=max(row.created_at for row in rows),
        )

    @app.get("/api/v1/videos/{video_id}/download")
    def download_video(
        video_id: UUID,
        request: Request,
        kind: str = Query(default="derived", pattern="^(derived|original)$"),
        db: Session = Depends(get_db),
        user: User = Depends(current_user),
    ):
        video = owned_video(db, video_id, user)
        bucket, key = video.object_bucket, video.object_key
        if kind == "derived":
            row = db.scalar(
                select(ProcessingResult).where(
                    ProcessingResult.video_id == video.id,
                    ProcessingResult.pipeline_version == video.pipeline_version,
                    ProcessingResult.result_type == "compressed_video",
                )
            )
            if row is None:
                raise HTTPException(status_code=404, detail="derived video is not ready")
            bucket, key = row.bucket, row.object_key
        url = request.app.state.storage.presign_get(bucket, key, settings.presign_expires_seconds)
        audit(db, user.id, "video.download", "video", video.id, kind=kind)
        db.commit()
        return RedirectResponse(url, status_code=307)

    @app.get(
        "/api/v1/integrations/external-database/health",
        response_model=ExternalDatabaseHealth,
    )
    def external_health(request: Request):
        return request.app.state.external_adapter.healthcheck()

    return app


def _video_out(video: Video) -> VideoOut:
    return VideoOut(
        id=video.id,
        survey_id=video.survey_id,
        filename=video.filename,
        size_bytes=video.size_bytes,
        sha256=video.sha256,
        state=video.state,
        object_key=video.object_key,
        pipeline_version=video.pipeline_version,
        created_at=video.created_at,
    )


app = create_app()
