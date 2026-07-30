"""Render annotated demo video + progress GIF for pipeline inspection."""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import (
    ByteTrackStyleTracker,
    DeterministicMockDetector,
    LineCrossingCounter,
    OpenCVForegroundDetector,
    OpenCVVideo,
    PlateOCRAdapter,
    PlateAdapter,
    BestFrameSelector,
    compress_video,
    write_immutable_manifest,
)
from .models import sha256_file

ATTR_INTERVAL = 15


def _cv2() -> Any:
    import cv2

    return cv2


def _attr_short(attrs: dict[str, Any] | None) -> str:
    if not attrs:
        return ""
    values = attrs.get("values") or {}
    color = (values.get("color") or {}).get("label")
    body = (values.get("type") or {}).get("label")
    parts = [p for p in (color, body) if p and p != "unknown"]
    return "/".join(parts)


def _plate_short(plate: dict[str, Any] | None) -> str:
    if not plate:
        return ""
    ocr = plate.get("ocr") or {}
    text = ocr.get("normalized") or ocr.get("normalized_latin") or ocr.get("raw") or ""
    return str(text).strip()


def _draw_frame(
    frame: Any,
    tracks: list[Any],
    line: tuple[tuple[float, float], tuple[float, float]],
    crossed: set[int],
    frame_index: int,
    backend: str,
    *,
    hud_extra: str = "",
    attr_by_track: dict[int, dict[str, Any]] | None = None,
    plate_by_track: dict[int, dict[str, Any]] | None = None,
) -> Any:
    cv2 = _cv2()
    canvas = frame.copy()
    (x1, y1), (x2, y2) = line
    cv2.line(canvas, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 255), 2)
    hud = (
        f"frame={frame_index} backend={backend} tracks={len(tracks)} "
        f"crossed={len(crossed)}"
    )
    if hud_extra:
        hud = f"{hud} {hud_extra}"
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 28), (0, 0, 0), -1)
    cv2.putText(
        canvas,
        hud[:140],
        (8, 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    attr_by_track = attr_by_track or {}
    plate_by_track = plate_by_track or {}
    for track in tracks:
        if isinstance(track, dict):
            track_id = int(track["track_id"])
            bx1, by1, bx2, by2 = track["bbox"]
            confidence = float(track["confidence"])
        else:
            track_id = track.track_id
            bx1, by1, bx2, by2 = track.bbox
            confidence = float(track.confidence)
        color = (0, 200, 0) if track_id in crossed else (255, 160, 0)
        cv2.rectangle(canvas, (bx1, by1), (bx2, by2), color, 2)
        label = f"id={track_id} {confidence:.2f}"
        attr_txt = _attr_short(attr_by_track.get(track_id))
        if attr_txt:
            label = f"{label} {attr_txt}"
        plate_txt = _plate_short(plate_by_track.get(track_id))
        if plate_txt:
            label = f"{label} plate={plate_txt}"
        # Keep label below HUD bar when the box sits near the top edge.
        text_y = by1 - 6
        if text_y < 40:
            text_y = min(canvas.shape[0] - 8, by2 + 16)
        cv2.putText(
            canvas,
            label[:56],
            (bx1, max(40, text_y)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )
    return canvas


def _write_gif_from_video(source: Path, destination: Path, fps: float = 5.0, scale: int = 480) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is unavailable")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    filter_complex = (
        f"fps={fps},scale={scale}:-1:flags=lanczos,split[s0][s1];"
        f"[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer"
    )
    command = [
        ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-i",
        str(source),
        "-vf",
        filter_complex,
        "-loop",
        "0",
        str(destination),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffmpeg gif failed")
    return {
        "path": str(destination),
        "size_bytes": destination.stat().st_size,
        "fps": fps,
        "scale_width": scale,
    }


def _crop_track(frame: Any, bbox: tuple[int, int, int, int]) -> Any:
    x1, y1, x2, y2 = bbox
    return frame[max(0, y1) : max(0, y2), max(0, x1) : max(0, x2)]


def run_visual_demo(
    source: Path,
    output_dir: Path,
    *,
    backend: str = "paddle",
    ocr_mode: str = "latin",
    line_position: float = 0.5,
    max_frames: int | None = 240,
    gif_fps: float = 4.0,
    approved_root: Path | None = None,
    manifest: Path | None = None,
) -> dict[str, Any]:
    """Process a fixture video and write annotated mp4 + progress gif + manifest."""
    cv2 = _cv2()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    annotated_path = output_dir / f"{stem}.annotated.mp4"
    gif_path = output_dir / f"{stem}.progress.gif"
    compressed_path = output_dir / f"{stem}.compressed.mp4"
    result_path = output_dir / f"{stem}.result.json"
    for path in (annotated_path, gif_path, compressed_path, result_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite {path}")

    attributes = None
    paddle_meta: dict[str, Any] = {}
    plate_detector = None
    recognizer = None

    if backend == "opencv":
        detector: Any = OpenCVForegroundDetector()
    elif backend == "mock":
        detector = DeterministicMockDetector()
    elif backend == "paddle":
        if approved_root is None or manifest is None:
            raise RuntimeError("paddle backend requires --approved-root and --manifest")
        from .paddle_runtime import build_paddle_backends, gpu_memory_brief

        bundle = build_paddle_backends(approved_root, manifest)
        detector = bundle.detector
        plate_detector = bundle.plate_detector
        recognizer = bundle.plate_recognizer
        attributes = bundle.attributes
        paddle_meta = {
            "pipeline_version": bundle.pipeline_version,
            "model_versions": bundle.model_versions,
            "vram_brief": gpu_memory_brief(),
            "approved_root": str(bundle.approved_root),
        }
    else:
        raise ValueError(f"unsupported backend: {backend}")

    tracker = ByteTrackStyleTracker()
    ocr = PlateOCRAdapter(recognizer, mode=ocr_mode)
    plate = PlateAdapter(ocr, plate_detector)
    video = OpenCVVideo()
    info = video.probe(source)
    line = ((info.width * line_position, 0.0), (info.width * line_position, float(info.height)))
    counter = LineCrossingCounter(*line)
    selector = BestFrameSelector()

    attr_by_track: dict[int, dict[str, Any]] = {}
    frame_snapshots: list[list[dict[str, Any]]] = []
    frames_processed = 0
    started = time.perf_counter()
    hud_base = ""
    if paddle_meta:
        versions = paddle_meta.get("model_versions") or {}
        hud_base = (
            f"pv={paddle_meta.get('pipeline_version', '')} "
            f"vd={versions.get('vehicle_detector', '')} {paddle_meta.get('vram_brief', '')}"
        )

    for frame_index, frame in video.frames(source):
        if max_frames is not None and frame_index >= max_frames:
            break
        detections = detector.detect(frame, frame_index)
        tracks = list(tracker.update(detections, frame_index))
        snapshot: list[dict[str, Any]] = []
        for track in tracks:
            counter.observe(track)
            selector.observe(track, frame, frame_index)
            snapshot.append(
                {
                    "track_id": track.track_id,
                    "bbox": track.bbox,
                    "confidence": track.confidence,
                }
            )
            if attributes is not None and (
                track.track_id not in attr_by_track or frame_index % ATTR_INTERVAL == 0
            ):
                crop = _crop_track(frame, track.bbox)
                if getattr(crop, "size", 0) > 0:
                    attr_by_track[track.track_id] = attributes.classify(crop)
        frame_snapshots.append(snapshot)
        frames_processed += 1

    observations = []
    plate_by_track: dict[int, dict[str, Any]] = {}
    for track_id, selected in sorted(selector.best.items()):
        plate_result = plate.analyze(selected["crop"])
        plate_by_track[track_id] = plate_result
        entry: dict[str, Any] = {
            "track_id": track_id,
            "best_frame_index": selected["frame_index"],
            "best_frame_score": selected["score"],
            "plate": plate_result,
            "plate_ocr": plate_result["ocr"],
        }
        if track_id in attr_by_track:
            entry["attributes"] = attr_by_track[track_id]
        elif attributes is not None:
            entry["attributes"] = attributes.classify(selected["crop"])
            attr_by_track[track_id] = entry["attributes"]
        observations.append(entry)

    # Second pass: burn attrs + plate text onto annotated video without re-inference.
    writer = cv2.VideoWriter(
        str(annotated_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        info.fps or 15.0,
        (info.width, info.height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"cannot open annotated writer: {annotated_path}")
    try:
        for frame_index, frame in video.frames(source):
            if frame_index >= frames_processed:
                break
            elapsed = max(time.perf_counter() - started, 1e-6)
            fps = (frame_index + 1) / elapsed
            annotated = _draw_frame(
                frame,
                frame_snapshots[frame_index],
                line,
                counter.crossed,
                frame_index,
                detector.backend_name,
                hud_extra=f"{hud_base} fps={fps:.1f}".strip(),
                attr_by_track=attr_by_track,
                plate_by_track=plate_by_track,
            )
            writer.write(annotated)
    finally:
        writer.release()

    gif_meta = _write_gif_from_video(annotated_path, gif_path, fps=gif_fps)
    compressed = compress_video(annotated_path, compressed_path, prefer_nvenc=False)
    compressed["sha256"] = sha256_file(compressed_path)

    uses_paddle = str(detector.backend_name).startswith("paddle")
    result = {
        "schema_version": "gpu-result-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_sha256": sha256_file(source),
        "video": asdict(info),
        "frames_processed": frames_processed,
        "detector_backend": detector.backend_name,
        "tracker_backend": tracker.backend_name,
        "crossing_count": len(counter.crossed),
        "tracks": observations,
        "artifacts": {
            "annotated_video": {
                "path": str(annotated_path),
                "sha256": sha256_file(annotated_path),
                "size_bytes": annotated_path.stat().st_size,
            },
            "progress_gif": gif_meta | {"sha256": sha256_file(gif_path)},
            "compressed_video": compressed,
        },
        "limitations": {
            "production_vehicle_detection": uses_paddle,
            "production_russian_ocr": False,
            "production_size_taxonomy": False,
            "ocr_mode": ocr.mode,
            "ocr_translation": "latin_to_russian_plate_lookalikes",
            "attribute_taxonomy": "veri_color_body_style",
            "uses_downloaded_baseline_models": True,
            "visual_demo": True,
        },
        "database_access": False,
    }
    if paddle_meta:
        result["paddle"] = paddle_meta
    write_immutable_manifest(result_path, result)
    return {
        "ok": True,
        "manifest": str(result_path),
        "annotated_video": str(annotated_path),
        "progress_gif": str(gif_path),
        "compressed_video": str(compressed_path),
        "crossing_count": result["crossing_count"],
        "frames_processed": frames_processed,
        "detector_backend": result["detector_backend"],
        "track_count": len(observations),
    }
