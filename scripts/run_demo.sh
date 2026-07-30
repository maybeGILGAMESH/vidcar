#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="${VIDCAR_PYTHON:-$repo_root/.venv/bin/python}"
export PYTHONPATH="$repo_root:$repo_root/services/gpu-worker:${PYTHONPATH:-}"

backend="${VIDCAR_DEMO_BACKEND:-paddle}"
approved_root="${MODEL_APPROVED_ROOT:-$repo_root/.runtime/model-registry/approved}"
manifest="${MODEL_MANIFEST:-$repo_root/models/manifests/vehicle-pipeline-0.1.0.yaml}"
fixtures_dir="$repo_root/tests/fixtures/videos"

if [[ "$backend" == "paddle" ]]; then
  output_dir="${1:-$repo_root/.runtime/demo-results-paddle}"
  "$repo_root/scripts/unpack_approved_models.sh"
  "$python_bin" -m gpu_worker.cli preflight-paddle \
    --approved-root "$approved_root" \
    --manifest "$manifest"
  if [[ "${VIDCAR_DEMO_FORCE:-0}" == "1" ]]; then
    rm -rf "$output_dir"
  fi
else
  output_dir="${1:-$repo_root/.runtime/demo-results}"
fi

mkdir -p "$output_dir"

# Prefer multi-car / plate fixtures when present; still include all mp4/avi.
mapfile -t videos < <(find "$fixtures_dir" -maxdepth 1 -type f \( -name '*.mp4' -o -name '*.avi' \) | sort)
if ((${#videos[@]} == 0)); then
  printf 'No fixture videos in %s\n' "$fixtures_dir" >&2
  exit 1
fi

printf 'Running visual demos (%s) for %s videos -> %s\n' "$backend" "${#videos[@]}" "$output_dir"
demo_args=(
  --inputs "${videos[@]}"
  --output-dir "$output_dir"
  --backend "$backend"
  --ocr-mode latin
  --max-frames 180
  --gif-fps 4
)
if [[ "$backend" == "paddle" ]]; then
  demo_args+=(--approved-root "$approved_root" --manifest "$manifest")
fi

"$python_bin" -m gpu_worker.cli demo "${demo_args[@]}"

printf '\nArtifacts:\n'
find "$output_dir" -maxdepth 1 -type f | sort
