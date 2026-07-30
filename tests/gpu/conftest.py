from __future__ import annotations

import sys
from pathlib import Path

WORKER_ROOT = Path(__file__).resolve().parents[2] / "services" / "gpu-worker"
sys.path.insert(0, str(WORKER_ROOT))
