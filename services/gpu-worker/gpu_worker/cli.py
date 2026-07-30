"""Command-line smoke runner and model validation utilities."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import (
    ByteTrackStyleTracker,
    DeterministicMockDetector,
    OpenCVForegroundDetector,
    PlateOCRAdapter,
    VideoPipeline,
    compress_video,
    write_immutable_manifest,
)
from .demo import run_visual_demo
from .models import ModelRegistry, inspect_archive, sha256_file


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def validate_models(args: argparse.Namespace) -> int:
    models = ModelRegistry(Path(args.approved_root)).validate(Path(args.manifest))
    _print({"valid": True, "models": {role: str(model.path) for role, model in models.items()}})
    return 0


def inspect_staging(args: argparse.Namespace) -> int:
    root = Path(args.staging_root)
    if not root.is_dir():
        _print({"valid": False, "error": "staging root does not exist", "path": str(root)})
        return 2
    suffixes = (".zip", ".tar", ".tar.gz", ".tgz")
    reports = [
        inspect_archive(path)
        for path in sorted(root.iterdir())
        if path.is_file() and path.name.lower().endswith(suffixes)
    ]
    output = {
        "staging_root": str(root.resolve()),
        "inspection_mode": "read_only",
        "promotion_performed": False,
        "archives": reports,
    }
    if args.output:
        destination = Path(args.output)
        destination.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _print(output)
    return 0 if all(item["archive_valid"] for item in reports) else 2


def preflight_paddle(args: argparse.Namespace) -> int:
    from .paddle_runtime import build_paddle_backends, require_paddle_gpu

    require_paddle_gpu()
    bundle = build_paddle_backends(Path(args.approved_root), Path(args.manifest))
    _print(
        {
            "ok": True,
            "paddle_gpu": True,
            "pipeline_version": bundle.pipeline_version,
            "model_versions": bundle.model_versions,
            "detector_backend": bundle.detector.backend_name,
        }
    )
    return 0


def demo(args: argparse.Namespace) -> int:
    outputs = []
    for source in args.inputs:
        path = Path(source)
        result = run_visual_demo(
            path,
            Path(args.output_dir),
            backend=args.backend,
            ocr_mode=args.ocr_mode,
            line_position=args.line_position,
            max_frames=args.max_frames,
            gif_fps=args.gif_fps,
            approved_root=Path(args.approved_root) if args.approved_root else None,
            manifest=Path(args.manifest) if args.manifest else None,
        )
        outputs.append(result)
    _print({"ok": True, "demos": outputs})
    return 0


def smoke(args: argparse.Namespace) -> int:
    source, result_path = Path(args.input), Path(args.result)
    if args.backend == "paddle":
        from .paddle_runtime import build_paddle_backends

        if not args.approved_root or not args.manifest:
            raise RuntimeError("paddle smoke requires --approved-root and --manifest")
        bundle = build_paddle_backends(Path(args.approved_root), Path(args.manifest))
        pipeline = VideoPipeline(
            bundle.detector,
            ByteTrackStyleTracker(),
            PlateOCRAdapter(bundle.plate_recognizer, mode=args.ocr_mode),
            plate_detector=bundle.plate_detector,
        )
    else:
        detector: Any = (
            OpenCVForegroundDetector() if args.backend == "opencv" else DeterministicMockDetector()
        )
        pipeline = VideoPipeline(detector, ByteTrackStyleTracker(), PlateOCRAdapter(mode=args.ocr_mode))

    probe = pipeline.video.probe(source)
    line_x = probe.width * float(args.line_position)
    result = pipeline.process(source, ((line_x, 0.0), (line_x, float(probe.height))))
    result.update({
        "job_id": args.job_id,
        "video_id": args.video_id,
        "pipeline_version": args.pipeline_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": sha256_file(source),
        "database_access": False,
    })
    if args.compressed:
        result["compressed"] = compress_video(source, Path(args.compressed), prefer_nvenc=not args.cpu_encode)
        result["compressed"]["sha256"] = sha256_file(Path(args.compressed))
    write_immutable_manifest(result_path, result)
    _print({"ok": True, "result": str(result_path), "crossing_count": result["crossing_count"]})
    return 0


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="gpu-worker")
    subcommands = command.add_subparsers(dest="command", required=True)

    validate = subcommands.add_parser("validate-models")
    validate.add_argument("--manifest", required=True)
    validate.add_argument("--approved-root", required=True)
    validate.set_defaults(handler=validate_models)

    inspect = subcommands.add_parser("inspect-staging")
    inspect.add_argument("--staging-root", required=True)
    inspect.add_argument("--output")
    inspect.set_defaults(handler=inspect_staging)

    preflight = subcommands.add_parser("preflight-paddle")
    preflight.add_argument("--manifest", required=True)
    preflight.add_argument("--approved-root", required=True)
    preflight.set_defaults(handler=preflight_paddle)

    run = subcommands.add_parser("smoke")
    run.add_argument("--input", required=True)
    run.add_argument("--result", required=True)
    run.add_argument("--compressed")
    run.add_argument("--cpu-encode", action="store_true")
    run.add_argument("--backend", choices=("mock", "opencv", "paddle"), default="mock")
    run.add_argument("--approved-root")
    run.add_argument("--manifest")
    run.add_argument(
        "--ocr-mode",
        choices=("baseline", "latin", "local_allowlist"),
        default="latin",
        help="Latin OCR from downloaded baseline models; local lookalike map to Russian plate letters",
    )
    run.add_argument("--line-position", type=float, default=0.5)
    run.add_argument("--job-id", default="smoke-job")
    run.add_argument("--video-id", default="smoke-video")
    run.add_argument("--pipeline-version", default="vehicle-pipeline-0.1.0-baseline")
    run.set_defaults(handler=smoke)

    visual = subcommands.add_parser("demo")
    visual.add_argument("--inputs", nargs="+", required=True, help="One or more fixture videos")
    visual.add_argument("--output-dir", required=True)
    visual.add_argument("--backend", choices=("mock", "opencv", "paddle"), default="paddle")
    visual.add_argument(
        "--approved-root",
        default=".runtime/model-registry/approved",
        help="Approved model registry root (required for paddle)",
    )
    visual.add_argument(
        "--manifest",
        default="models/manifests/vehicle-pipeline-0.1.0.yaml",
        help="Pipeline manifest with unpacked_dir paths",
    )
    visual.add_argument(
        "--ocr-mode",
        choices=("baseline", "latin", "local_allowlist"),
        default="latin",
    )
    visual.add_argument("--line-position", type=float, default=0.5)
    visual.add_argument("--max-frames", type=int, default=240)
    visual.add_argument("--gif-fps", type=float, default=4.0)
    visual.set_defaults(handler=demo)
    return command


def main() -> int:
    try:
        args = parser().parse_args()
        return int(args.handler(args))
    except Exception as exc:
        _print({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
