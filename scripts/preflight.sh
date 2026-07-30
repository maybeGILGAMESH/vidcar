#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="${VIDCAR_PYTHON:-$repo_root/.venv/bin/python}"
failed=0

printf '== vidcar preflight ==\n'

if [[ -x "$python_bin" ]]; then
  printf 'OK python: %s\n' "$("$python_bin" -c 'import sys; print(sys.executable)')"
else
  printf 'BLOCKED: project python missing at %s\n' "$python_bin" >&2
  failed=1
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | sed 's/^/OK gpu: /'
else
  printf 'BLOCKED: nvidia-smi unavailable\n' >&2
  failed=1
fi

if command -v docker >/dev/null 2>&1; then
  printf 'OK docker: %s\n' "$(docker --version)"
  if docker compose version >/dev/null 2>&1; then
    printf 'OK compose: available\n'
  else
    printf 'BLOCKED: docker compose plugin missing\n' >&2
    failed=1
  fi
else
  printf 'BLOCKED: docker not installed (needs sudo to install)\n' >&2
  failed=1
fi

approved="$repo_root/.runtime/model-registry/approved"
if [[ -d "$approved" ]]; then
  printf 'OK local approved registry: %s\n' "$approved"
else
  printf 'BLOCKED: local approved registry missing\n' >&2
  failed=1
fi

if [[ -f models/manifests/vehicle-pipeline-0.1.0.json ]]; then
  if [[ -x "$python_bin" ]]; then
    if "$python_bin" - <<'PY'
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location(
    "model_manifest_loader",
    "packages/model-manifest/loader.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
manifest = mod.load_pipeline_manifest(Path("models/manifests/vehicle-pipeline-0.1.0.yaml"))
errors = mod.validate_against_approved(manifest, Path(".runtime/model-registry/approved"))
if errors:
    print("\n".join(errors))
    raise SystemExit(1)
print("OK pipeline manifest validates against local approved")
PY
    then
      :
    else
      printf 'BLOCKED: pipeline manifest validation failed\n' >&2
      failed=1
    fi
  fi
else
  printf 'BLOCKED: vehicle-pipeline-0.1.0.json missing\n' >&2
  failed=1
fi

scratch="${SCRATCH_ROOT:-$repo_root/.runtime/scratch}"
mkdir -p "$scratch"
df -h "$scratch" | sed 's/^/OK disk: /'

if (( failed != 0 )); then
  printf 'Preflight FAILED (compose runtime still blocked without Docker).\n' >&2
  exit 1
fi

printf 'Preflight passed for local components.\n'
