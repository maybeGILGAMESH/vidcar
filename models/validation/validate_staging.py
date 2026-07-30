#!/usr/bin/env python3
"""Read-only validation entry point for unapproved model archives."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKER_ROOT = Path(__file__).resolve().parents[2] / "services" / "gpu-worker"
sys.path.insert(0, str(WORKER_ROOT))

from gpu_worker.models import inspect_archive  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("staging_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.staging_root.is_dir():
        parser.error(f"not a directory: {args.staging_root}")
    reports = [
        inspect_archive(path)
        for path in sorted(args.staging_root.iterdir())
        if path.is_file() and path.name.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz"))
    ]
    result = {
        "schema_version": "staging-validation-1",
        "staging_root": str(args.staging_root.resolve()),
        "inspection_mode": "read_only",
        "promotion_performed": False,
        "promotion_eligible": False,
        "promotion_blocker": "license/source metadata must be supplied and reviewed",
        "archives": reports,
    }
    body = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(body, encoding="utf-8")
    print(body, end="")
    return 0 if all(item["archive_valid"] for item in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
