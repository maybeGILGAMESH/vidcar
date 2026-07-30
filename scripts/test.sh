#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="${VIDCAR_PYTHON:-$repo_root/.venv/bin/python}"
export PYTHONPATH="$repo_root:$repo_root/services/gpu-worker:${PYTHONPATH:-}"

printf 'Running pytest suite...\n'
"$python_bin" -m pytest \
  tests/unit \
  tests/recovery \
  tests/load \
  tests/gpu \
  tests/integration \
  -q
