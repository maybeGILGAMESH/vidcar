"""Versioned Pydantic contracts shared by API and workers."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class JobState(str, Enum):
    created = "created"
    uploading = "uploading"
    uploaded = "uploaded"
    queued = "queued"
    claimed = "claimed"
    processing = "processing"
    uploading_results = "uploading_results"
    awaiting_finalize = "awaiting_finalize"
    completed = "completed"
    failed_retryable = "failed_retryable"
    failed_terminal = "failed_terminal"
    cancelled = "cancelled"


class SurveyNoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    video_id: UUID | None = None


class SurveyCreate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    gps_accuracy_m: float = Field(gt=0)
    camera_direction_deg: float | None = Field(default=None, ge=0, lt=360)
    notes: list[SurveyNoteIn] = Field(default_factory=list, max_length=10)


class SurveyOut(SurveyCreate):
    id: UUID
    owner_id: str
    created_at: datetime


class UploadSessionCreate(BaseModel):
    survey_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = "video/mp4"
    size_bytes: int = Field(gt=0, le=10 * 1024**3)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    part_size_bytes: int = Field(default=64 * 1024**2, ge=5 * 1024**2)

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        if "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("filename must not contain a path")
        return value


class MultipartPart(BaseModel):
    part_number: int = Field(ge=1, le=10_000)
    etag: str


class UploadSessionOut(BaseModel):
    video_id: UUID
    upload_id: str
    object_key: str
    part_size_bytes: int
    part_urls: list[dict[str, Any]]


class CompleteUpload(BaseModel):
    parts: list[MultipartPart] = Field(min_length=1)

    @field_validator("parts")
    @classmethod
    def unique_ordered_parts(cls, value: list[MultipartPart]) -> list[MultipartPart]:
        numbers = [part.part_number for part in value]
        if len(numbers) != len(set(numbers)):
            raise ValueError("part numbers must be unique")
        return sorted(value, key=lambda part: part.part_number)


class VideoOut(BaseModel):
    id: UUID
    survey_id: UUID
    filename: str
    size_bytes: int
    sha256: str
    state: JobState
    object_key: str
    pipeline_version: str
    created_at: datetime


class ArtifactManifest(BaseModel):
    result_type: str = Field(min_length=1, max_length=64)
    bucket: str
    object_key: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    content_type: str | None = None


class ProcessingManifest(BaseModel):
    schema_version: str = "1.0"
    job_id: UUID
    video_id: UUID
    pipeline_version: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    worker_id: str
    produced_at: datetime
    artifacts: list[ArtifactManifest] = Field(min_length=1)
    summary: dict[str, Any] = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_result_types(self):
        result_types = [artifact.result_type for artifact in self.artifacts]
        if len(result_types) != len(set(result_types)):
            raise ValueError("result_type must be unique in a manifest")
        return self


class ProcessingResultOut(BaseModel):
    video_id: UUID
    pipeline_version: str
    summary: dict[str, Any]
    artifacts: list[ArtifactManifest]
    completed_at: datetime


class ExternalDatabaseHealth(BaseModel):
    status: str = "not_configured"
    state: str = "dns_nxdomain"
    retryable: bool = False
