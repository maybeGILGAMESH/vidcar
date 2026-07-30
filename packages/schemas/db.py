"""SQLAlchemy schema; PostgreSQL in production and SQLite for unit tests."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from packages.common.state_machine import validate_transition
from packages.contracts.models import JobState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_role_user_name"),)


class Survey(Base, TimestampMixin):
    __tablename__ = "surveys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    gps_accuracy_m: Mapped[float] = mapped_column(Float, nullable=False)
    camera_direction_deg: Mapped[float | None] = mapped_column(Float)


class SurveyNote(Base, TimestampMixin):
    __tablename__ = "survey_notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    survey_id: Mapped[str] = mapped_column(ForeignKey("surveys.id"), nullable=False, index=True)
    video_id: Mapped[str | None] = mapped_column(ForeignKey("videos.id"), index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class Video(Base, TimestampMixin):
    __tablename__ = "videos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    survey_id: Mapped[str] = mapped_column(ForeignKey("surveys.id"), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    multipart_upload_id: Mapped[str | None] = mapped_column(String(256))
    state: Mapped[str] = mapped_column(String(32), default=JobState.created.value, nullable=False, index=True)
    pipeline_version: Mapped[str] = mapped_column(String(128), nullable=False)

    def transition_to(self, target: JobState | str) -> None:
        self.state = validate_transition(self.state, target).value


class PipelineVersion(Base, TimestampMixin):
    __tablename__ = "pipeline_versions"
    version: Mapped[str] = mapped_column(String(128), primary_key=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ModelVersion(Base, TimestampMixin):
    __tablename__ = "model_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_name_version"),)


class ProcessingJob(Base, TimestampMixin):
    __tablename__ = "processing_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default=JobState.queued.value, nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("video_id", "pipeline_version", name="uq_job_video_pipeline"),
    )

    def transition_to(self, target: JobState | str) -> None:
        self.state = validate_transition(self.state, target).value


class ProcessingAttempt(Base, TimestampMixin):
    __tablename__ = "processing_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("job_id", "attempt_no", name="uq_attempt_job_no"),)


class VehicleTrack(Base, TimestampMixin):
    __tablename__ = "vehicle_tracks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"), nullable=False, index=True)
    pipeline_version: Mapped[str] = mapped_column(String(128), nullable=False)
    track_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    first_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    last_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("video_id", "pipeline_version", "track_ref", name="uq_track_ref"),
    )


class VehicleEvent(Base, TimestampMixin):
    __tablename__ = "vehicle_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    track_id: Mapped[str] = mapped_column(ForeignKey("vehicle_tracks.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    frame_no: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class VehicleClassification(Base, TimestampMixin):
    __tablename__ = "vehicle_classifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    track_id: Mapped[str] = mapped_column(ForeignKey("vehicle_tracks.id"), nullable=False, unique=True)
    size_class: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class PlateObservation(Base, TimestampMixin):
    __tablename__ = "plate_observations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    track_id: Mapped[str] = mapped_column(ForeignKey("vehicle_tracks.id"), nullable=False, index=True)
    frame_no: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_text: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    votes: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class ProcessingResult(Base, TimestampMixin):
    __tablename__ = "processing_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(128), nullable=False)
    result_type: Mapped[str] = mapped_column(String(64), nullable=False)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "video_id", "pipeline_version", "result_type", name="uq_result_video_pipeline_type"
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
