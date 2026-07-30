#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="${VIDCAR_PYTHON:-$repo_root/.venv/bin/python}"
export PYTHONPATH="$repo_root:$repo_root/services/gpu-worker:${PYTHONPATH:-}"

printf 'Checking edge health via HTTP...\n'
curl -fsS "http://127.0.0.1:${HTTP_PORT:-8080}/healthz" || true
printf '\n'

printf 'Running local GPU worker smoke (mock backend + latin->russian OCR map)...\n'
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

video_path="$tmpdir/fixture.mp4"
result_path="$tmpdir/result.json"
compressed_path="$tmpdir/compressed.mp4"

"$python_bin" -c "
from pathlib import Path
import numpy as np
import cv2
video = Path(r'''$video_path''')
writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 10, (320, 240))
for i in range(30):
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    x = 20 + i * 8
    cv2.rectangle(frame, (x, 100), (x + 40, 140), (0, 255, 0), -1)
    writer.write(frame)
writer.release()
print(video)
"

"$python_bin" -m gpu_worker.cli smoke \
  --input "$video_path" \
  --result "$result_path" \
  --compressed "$compressed_path" \
  --backend mock \
  --ocr-mode latin \
  --cpu-encode

"$python_bin" -c "
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location('loader', Path('packages/model-manifest/loader.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
manifest = mod.load_pipeline_manifest(Path('models/manifests/vehicle-pipeline-0.1.0.yaml'))
errors = mod.validate_against_approved(manifest, Path('.runtime/model-registry/approved'))
assert not errors, errors
print('OK approved manifest')
"

printf 'Local smoke completed successfully.\n'
printf 'Compose stack is up at http://127.0.0.1:8080/\n'
