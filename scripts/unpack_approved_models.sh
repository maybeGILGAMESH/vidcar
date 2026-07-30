#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
approved_root="${MODEL_APPROVED_ROOT:-$repo_root/.runtime/model-registry/approved}"

if [[ ! -d "$approved_root" ]]; then
  printf 'BLOCKED: approved root missing: %s\n' "$approved_root" >&2
  exit 1
fi

python_bin="${VIDCAR_PYTHON:-$repo_root/.venv/bin/python}"

"$python_bin" - <<'PY' "$approved_root"
import hashlib
import json
import sys
import tarfile
import zipfile
from pathlib import Path

approved = Path(sys.argv[1])
ok = True
for version_dir in sorted(approved.glob("*/0.1.0")):
    source = version_dir / "source.json"
    if not source.is_file():
        print(f"ERROR: missing source.json in {version_dir}", file=sys.stderr)
        ok = False
        continue
    meta = json.loads(source.read_text(encoding="utf-8"))
    expected = str(meta.get("sha256", "")).lower()
    archives = list(version_dir.glob("model.zip")) + list(version_dir.glob("model.tar.gz"))
    if not archives:
        print(f"ERROR: no model archive in {version_dir}", file=sys.stderr)
        ok = False
        continue
    archive = archives[0]
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != expected:
        print(f"ERROR: checksum mismatch for {archive}: {digest} != {expected}", file=sys.stderr)
        ok = False
        continue
    out = version_dir / "unpacked"
    marker = out / ".unpacked_ok"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == digest:
        print(f"OK already unpacked: {version_dir.name} ({version_dir.parent.name})")
        continue
    if out.exists():
        for path in sorted(out.rglob("*"), reverse=True):
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    out.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(out)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            tf.extractall(out)
    else:
        print(f"ERROR: unsupported archive {archive}", file=sys.stderr)
        ok = False
        continue
    marker.write_text(digest + "\n", encoding="utf-8")
    print(f"OK unpacked: {archive} -> {out}")

# Flatten nested single-dir layouts for easier discovery
for version_dir in sorted(approved.glob("*/0.1.0")):
    out = version_dir / "unpacked"
    if not out.is_dir():
        continue
    children = [p for p in out.iterdir() if p.name != ".unpacked_ok"]
    if len(children) == 1 and children[0].is_dir():
        nested = children[0]
        for item in nested.iterdir():
            target = out / item.name
            if not target.exists():
                item.rename(target)
        if not any(nested.iterdir()):
            nested.rmdir()

raise SystemExit(0 if ok else 2)
PY
