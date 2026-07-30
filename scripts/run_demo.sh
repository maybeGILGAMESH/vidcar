#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="${VIDCAR_PYTHON:-$repo_root/.venv/bin/python}"
export PYTHONPATH="$repo_root:$repo_root/services/gpu-worker:${PYTHONPATH:-}"

fixtures_dir="$repo_root/tests/fixtures/videos"
output_dir="${1:-$repo_root/.runtime/demo-results}"
mkdir -p "$output_dir"

mapfile -t videos < <(find "$fixtures_dir" -maxdepth 1 -type f \( -name '*.mp4' -o -name '*.avi' \) | sort)
if ((${#videos[@]} == 0)); then
  printf 'No fixture videos in %s\n' "$fixtures_dir" >&2
  exit 1
fi

printf 'Running visual demos for %s videos -> %s\n' "${#videos[@]}" "$output_dir"
"$python_bin" -m gpu_worker.cli demo \
  --inputs "${videos[@]}" \
  --output-dir "$output_dir" \
  --backend opencv \
  --ocr-mode latin \
  --max-frames 180 \
  --gif-fps 4

printf '\nArtifacts:\n'
find "$output_dir" -maxdepth 1 -type f | sort
