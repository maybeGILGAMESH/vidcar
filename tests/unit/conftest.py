from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT,
    ROOT / "apps" / "api",
    ROOT / "services" / "result-writer",
    ROOT / "services" / "external-db-adapter",
):
    sys.path.insert(0, str(path))
