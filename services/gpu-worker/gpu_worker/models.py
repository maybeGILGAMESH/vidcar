"""Fail-closed model registry and read-only staging validation."""
from __future__ import annotations

import hashlib
import json
import re
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_METADATA = ("name", "version", "sha256", "source", "license")


class ModelValidationError(ValueError):
    pass


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        return True
    except (FileNotFoundError, ValueError):
        return False


@dataclass(frozen=True)
class ApprovedModel:
    role: str
    path: Path
    metadata: dict[str, Any]


class ModelRegistry:
    """Resolves only pinned files physically contained by approved_root."""

    def __init__(self, approved_root: Path) -> None:
        self.approved_root = approved_root.resolve()

    def load_manifest(self, manifest_path: Path) -> dict[str, Any]:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("pipeline_version"):
            raise ModelValidationError("pipeline_version is required")
        if data.get("schema_version") not in (None, "model-manifest-1"):
            raise ModelValidationError("unsupported model manifest schema_version")
        if "latest" in str(data["pipeline_version"]).lower():
            raise ModelValidationError("'latest' is forbidden")
        models = data.get("models")
        if not isinstance(models, dict):
            raise ModelValidationError("models must be an object")
        ocr = data.get("ocr_capability")
        if ocr is not None:
            if not isinstance(ocr, dict) or ocr.get("mode") not in {
                "baseline", "latin", "local_allowlist", "cyrillic_approved"
            }:
                raise ModelValidationError("invalid ocr_capability")
            production = ocr.get("production_russian_ocr")
            if not isinstance(production, bool):
                raise ModelValidationError("production_russian_ocr must be boolean")
            if production and (ocr["mode"] != "cyrillic_approved" or "plate_ocr" not in models):
                raise ModelValidationError("Russian production OCR requires an approved plate_ocr model")
        return data

    def validate(self, manifest_path: Path) -> dict[str, ApprovedModel]:
        manifest = self.load_manifest(manifest_path)
        resolved: dict[str, ApprovedModel] = {}
        for role, metadata in manifest["models"].items():
            if not isinstance(metadata, dict):
                raise ModelValidationError(f"{role}: metadata must be an object")
            missing = [key for key in REQUIRED_METADATA if not metadata.get(key)]
            if missing:
                raise ModelValidationError(f"{role}: missing {', '.join(missing)}")
            if "latest" in str(metadata["version"]).lower():
                raise ModelValidationError(f"{role}: 'latest' is forbidden")
            expected = str(metadata["sha256"]).lower()
            if not SHA256_RE.fullmatch(expected):
                raise ModelValidationError(f"{role}: invalid sha256")
            relative = Path(str(metadata.get("path", "")))
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ModelValidationError(f"{role}: path must be approved-root relative")
            candidate = self.approved_root / relative
            if not _inside(candidate, self.approved_root) or not candidate.is_file():
                raise ModelValidationError(f"{role}: model is not an approved regular file")
            actual = sha256_file(candidate)
            if actual != expected:
                raise ModelValidationError(f"{role}: checksum mismatch")
            resolved[role] = ApprovedModel(role, candidate, dict(metadata))
        return resolved


def inspect_archive(path: Path) -> dict[str, Any]:
    """Inspect an archive without extracting or modifying it."""
    result: dict[str, Any] = {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "read_only": True,
        "archive_valid": False,
        "member_count": None,
        "unsafe_members": [],
    }
    names: list[str]
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                bad_crc = archive.testzip()
                if bad_crc:
                    raise ModelValidationError(f"bad CRC: {bad_crc}")
        elif tarfile.is_tarfile(path):
            with tarfile.open(path, "r:*") as archive:
                names = archive.getnames()
        else:
            result["error"] = "unsupported_or_not_archive"
            return result
        unsafe = [
            name for name in names
            if Path(name).is_absolute() or ".." in Path(name).parts
        ]
        result.update(
            archive_valid=not unsafe,
            member_count=len(names),
            unsafe_members=unsafe[:20],
        )
    except (OSError, tarfile.TarError, zipfile.BadZipFile, ModelValidationError) as exc:
        result["error"] = str(exc)
    return result
