from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from gpu_worker.models import ModelRegistry, ModelValidationError, inspect_archive, sha256_file


def manifest(model_path: str, checksum: str, **overrides: str) -> dict:
    metadata = {
        "name": "detector",
        "version": "1.0.0",
        "path": model_path,
        "sha256": checksum,
        "source": "https://example.invalid/model",
        "license": "Apache-2.0",
    }
    metadata.update(overrides)
    return {"pipeline_version": "pipeline-1.0.0", "models": {"detector": metadata}}


def test_registry_accepts_only_pinned_approved_file(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    model = approved / "model.onnx"
    model.write_bytes(b"model")
    descriptor = tmp_path / "manifest.json"
    descriptor.write_text(json.dumps(manifest(model.name, sha256_file(model))))

    resolved = ModelRegistry(approved).validate(descriptor)

    assert resolved["detector"].path == model


@pytest.mark.parametrize(
    "change",
    [
        {"path": "../staging/model.onnx"},
        {"sha256": "0" * 64},
        {"license": ""},
        {"version": "latest"},
    ],
)
def test_registry_rejects_unapproved_or_unpinned(tmp_path: Path, change: dict[str, str]) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    model = approved / "model.onnx"
    model.write_bytes(b"model")
    descriptor = tmp_path / "manifest.json"
    descriptor.write_text(json.dumps(manifest(model.name, sha256_file(model), **change)))

    with pytest.raises(ModelValidationError):
        ModelRegistry(approved).validate(descriptor)


def test_archive_inspection_is_read_only_and_detects_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape", b"x")
    before = archive.stat().st_mtime_ns

    report = inspect_archive(archive)

    assert not report["archive_valid"]
    assert report["unsafe_members"] == ["../escape"]
    assert archive.stat().st_mtime_ns == before
