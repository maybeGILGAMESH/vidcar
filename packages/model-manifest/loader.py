"""Load and validate versioned pipeline manifests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


class ManifestError(ValueError):
    pass


def load_pipeline_manifest(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ManifestError("manifest root must be an object")
    version = str(data.get("pipeline_version", ""))
    if not version or "latest" in version.lower():
        raise ManifestError("pipeline_version must be pinned and not 'latest'")
    models = data.get("models")
    if not isinstance(models, dict):
        raise ManifestError("models must be an object")
    return data


def validate_against_approved(manifest: dict[str, Any], approved_root: Path) -> list[str]:
    """Return empty list when every referenced file exists with matching sha256 metadata."""
    errors: list[str] = []
    for role, meta in manifest.get("models", {}).items():
        rel = Path(str(meta.get("path", "")))
        candidate = approved_root / rel
        if not candidate.is_file():
            errors.append(f"{role}: missing {candidate}")
            continue
        source = candidate.parent / "source.json"
        if not source.is_file():
            errors.append(f"{role}: missing source.json beside model")
            continue
        recorded = json.loads(source.read_text(encoding="utf-8")).get("sha256")
        expected = str(meta.get("sha256", "")).lower()
        if recorded != expected:
            errors.append(f"{role}: source.json sha256 mismatch")
    return errors
