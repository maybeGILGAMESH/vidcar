BEGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
  id varchar(128) PRIMARY KEY,
  email varchar(320) UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE roles (
  id bigserial PRIMARY KEY,
  user_id varchar(128) NOT NULL REFERENCES users(id),
  name varchar(64) NOT NULL,
  CONSTRAINT uq_role_user_name UNIQUE (user_id, name)
);
CREATE TABLE surveys (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id varchar(128) NOT NULL REFERENCES users(id),
  latitude double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
  longitude double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
  gps_accuracy_m double precision NOT NULL CHECK (gps_accuracy_m > 0),
  camera_direction_deg double precision CHECK (camera_direction_deg >= 0 AND camera_direction_deg < 360),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE pipeline_versions (
  version varchar(128) PRIMARY KEY CHECK (lower(version) <> 'latest'),
  manifest_sha256 char(64) NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  approved boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE model_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name varchar(128) NOT NULL,
  version varchar(128) NOT NULL CHECK (lower(version) <> 'latest'),
  stage varchar(32) NOT NULL,
  object_key text NOT NULL,
  sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_model_name_version UNIQUE (name, version)
);
CREATE TABLE videos (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  survey_id uuid NOT NULL REFERENCES surveys(id),
  owner_id varchar(128) NOT NULL REFERENCES users(id),
  filename varchar(255) NOT NULL,
  content_type varchar(128) NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes > 0),
  sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  object_bucket varchar(128) NOT NULL,
  object_key text NOT NULL UNIQUE,
  multipart_upload_id varchar(256),
  state varchar(32) NOT NULL,
  pipeline_version varchar(128) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (state IN ('created','uploading','uploaded','queued','claimed','processing',
    'uploading_results','awaiting_finalize','completed','failed_retryable',
    'failed_terminal','cancelled'))
);
CREATE TABLE survey_notes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  survey_id uuid NOT NULL REFERENCES surveys(id),
  video_id uuid REFERENCES videos(id),
  text text NOT NULL CHECK (length(text) BETWEEN 1 AND 2000),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE processing_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  video_id uuid NOT NULL REFERENCES videos(id),
  pipeline_version varchar(128) NOT NULL,
  state varchar(32) NOT NULL,
  priority integer NOT NULL DEFAULT 0,
  claimed_by varchar(128),
  lease_expires_at timestamptz,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_job_video_pipeline UNIQUE (video_id, pipeline_version)
);
CREATE INDEX ix_processing_jobs_claim ON processing_jobs (state, priority DESC, created_at);
CREATE TABLE processing_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES processing_jobs(id),
  worker_id varchar(128) NOT NULL,
  attempt_no integer NOT NULL CHECK (attempt_no > 0),
  state varchar(32) NOT NULL,
  heartbeat_at timestamptz,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_attempt_job_no UNIQUE (job_id, attempt_no)
);
CREATE TABLE vehicle_tracks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  video_id uuid NOT NULL REFERENCES videos(id),
  pipeline_version varchar(128) NOT NULL,
  track_ref varchar(128) NOT NULL,
  first_frame integer NOT NULL,
  last_frame integer NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_track_ref UNIQUE (video_id, pipeline_version, track_ref)
);
CREATE TABLE vehicle_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id uuid NOT NULL REFERENCES vehicle_tracks(id),
  event_type varchar(64) NOT NULL,
  frame_no integer NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE vehicle_classifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id uuid NOT NULL UNIQUE REFERENCES vehicle_tracks(id),
  size_class varchar(16) NOT NULL CHECK (size_class IN ('light','medium','heavy','unknown')),
  confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE plate_observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id uuid NOT NULL REFERENCES vehicle_tracks(id),
  frame_no integer NOT NULL,
  raw_text varchar(32) NOT NULL,
  normalized_text varchar(32) NOT NULL,
  confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  votes integer NOT NULL DEFAULT 1 CHECK (votes > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE processing_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  video_id uuid NOT NULL REFERENCES videos(id),
  pipeline_version varchar(128) NOT NULL,
  result_type varchar(64) NOT NULL,
  bucket varchar(128) NOT NULL,
  object_key text NOT NULL,
  sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  manifest_sha256 char(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_result_video_pipeline_type UNIQUE (video_id, pipeline_version, result_type)
);
CREATE TABLE audit_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  actor_id varchar(128) NOT NULL,
  action varchar(128) NOT NULL,
  resource_type varchar(64) NOT NULL,
  resource_id varchar(128) NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX ix_audit_actor_time ON audit_log (actor_id, occurred_at DESC);
COMMIT;
