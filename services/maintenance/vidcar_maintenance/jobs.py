"""Safe maintenance helpers that never touch originals or production disks."""
from __future__ import annotations

import shutil
from pathlib import Path


def vacuum_scratch(scratch_root: Path, *, dry_run: bool = True) -> list[str]:
    """Remove only empty temporary directories under a configured scratch root."""
    if not scratch_root.exists():
        return [f"scratch missing: {scratch_root}"]
    actions: list[str] = []
    for path in sorted(scratch_root.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            actions.append(f"rmdir {path}")
            if not dry_run:
                path.rmdir()
    return actions


def report_blockers(repo_root: Path) -> dict[str, bool]:
    return {
        "docker_available": shutil.which("docker") is not None,
        "approved_local_present": (repo_root / ".runtime/model-registry/approved").exists(),
        "opt_approved_writable": False,
        "worker_node_evidence_valid": False,
        "central_s3_configured": False,
        "cyrillic_ocr_present": False,
    }
