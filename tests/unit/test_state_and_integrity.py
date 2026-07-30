import hashlib
import io

import pytest

from packages.common.integrity import ChecksumMismatch, sha256_stream, validate_model_reference, verify_sha256
from packages.common.state_machine import InvalidTransition, validate_transition
from packages.common.storage import MemoryObjectStorage
from packages.contracts.models import JobState


def test_state_machine_accepts_pipeline_and_rejects_skip():
    assert validate_transition(JobState.uploaded, JobState.queued) == JobState.queued
    with pytest.raises(InvalidTransition):
        validate_transition(JobState.uploaded, JobState.completed)


def test_checksum_and_model_guards():
    payload = b"vehicle-video"
    expected = hashlib.sha256(payload).hexdigest()
    assert sha256_stream(io.BytesIO(payload)) == expected
    verify_sha256([payload[:4], payload[4:]], expected)
    with pytest.raises(ChecksumMismatch):
        verify_sha256([payload], "0" * 64)
    with pytest.raises(ValueError, match="latest"):
        validate_model_reference("latest", expected, "approved")
    with pytest.raises(ValueError, match="approved"):
        validate_model_reference("1.0", expected, "staging")


def test_memory_multipart_is_immutable():
    storage = MemoryObjectStorage()
    upload_id = storage.create_multipart("bucket", "key", "video/mp4", {"sha256": "x"})
    etag = storage.put_part(upload_id, 1, b"abc")
    storage.complete_multipart(
        "bucket", "key", upload_id, [{"PartNumber": 1, "ETag": etag}]
    )
    assert b"".join(storage.iter_bytes("bucket", "key")) == b"abc"
    with pytest.raises(FileExistsError):
        storage.create_multipart("bucket", "key", "video/mp4", {})
