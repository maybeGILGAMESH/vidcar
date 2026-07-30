"""Render annotated demo video + progress GIF for pipeline inspection."""
from __future__ import annotations

import json
import shutil
import subprocess
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
    BestFrameSelector,
    compress_video,
    write_immutable_manifest,
)
from .models import sha256_file


def _cv2() -> Any:
    import cv2

    return cv2


def _draw_frame(
    frame: Any,
    tracks: list[Any],
    line: tuple[tuple[float, float], tuple[float, float]],
    crossed: set[int],
    frame_index: int,
    backend: str,
) -> Any:
    cv2 = _cv2()
    canvas = frame.copy()
    (x1, y1), (x2, y2) = line
    cv2.line(canvas, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 255), 2)
    for track in tracks:
        bx1, by1, bx2, by2 = track.bbox
        color = (0, 200, 0) if track.track_id in crossed else (255, 160, 0)
        cv2.rectangle(canvas, (bx1, by1), (bx2, by2), color, 2)
        label = f"id={track.track_id} {track.confidence:.2f}"
        cv2.putText(
            canvas,
            label,
            (bx1, max(16, by1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )
    hud = (
        f"frame={frame_index} backend={backend} tracks={len(tracks)} "
        f"crossed={len(crossed)}"
    )
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 28), (0, 0, 0), -1)
    cv2.putText(
        canvas,
        hud,
        (8, 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 255, 255),
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
    # Intermediate progress GIF: low FPS, scaled, palette-optimized.
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


def run_visual_demo(
    source: Path,
    output_dir: Path,
    *,
    backend: str = "opencv",
    ocr_mode: str = "latin",
    line_position: float = 0.5,
    max_frames: int | None = 240,
    gif_fps: float = 4.0,
) -> dict[str, Any]:
    """Process a fixture video and write annotated mp4 + progress gif + manifest."""
    cv2 = _cv2()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    annotated_path = output_dir / f"{stem}.annotated.mp4"
    gif_path = output_dir / f"{stem}.progress.gif"
    compressed_path = output_dir / f"{stem}.compressed.mp4"
    manifest_path = output_dir / f"{stem}.result.json"
    for path in (annotated_path, gif_path, compressed_path, manifest_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite {path}")

    detector = OpenCVForegroundDetector() if backend == "opencv" else DeterministicMockDetector()
    tracker = ByteTrackStyleTracker()
    ocr = PlateOCRAdapter(mode=ocr_mode)
    video = OpenCVVideo()
    info = video.probe(source)
    line = ((info.width * line_position, 0.0), (info.width * line_position, float(info.height)))
    counter = LineCrossingCounter(*line)
    selector = BestFrameSelector()

    writer = cv2.VideoWriter(
        str(annotated_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        info.fps or 15.0,
        (info.width, info.height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"cannot open annotated writer: {annotated_path}")

    frames_processed = 0
    try:
        for frame_index, frame in video.frames(source):
            if max_frames is not None and frame_index >= max_frames:
                break
            detections = detector.detect(frame, frame_index)
            tracks = list(tracker.update(detections, frame_index))
            for track in tracks:
                counter.observe(track)
                selector.observe(track, frame, frame_index)
            annotated = _draw_frame(
                frame,
                tracks,
                line,
                counter.crossed,
                frame_index,
                detector.backend_name,
            )
            writer.write(annotated)
            frames_processed += 1
    finally:
        writer.release()

    observations = []
    for track_id, selected in sorted(selector.best.items()):
        plate = {"bbox": None, "detection_confidence": 0.0, "ocr": asdict(ocr.recognize(selected["crop"]))}
        observations.append(
            {
                "track_id": track_id,
                "best_frame_index": selected["frame_index"],
                "best_frame_score": selected["score"],
                "plate": plate,
                "plate_ocr": plate["ocr"],
            }
        )

    gif_meta = _write_gif_from_video(annotated_path, gif_path, fps=gif_fps)
    compressed = compress_video(annotated_path, compressed_path, prefer_nvenc=False)
    compressed["sha256"] = sha256_file(compressed_path)

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
            "production_vehicle_detection": False,
            "production_russian_ocr": False,
            "ocr_mode": ocr.mode,
            "ocr_translation": "latin_to_russian_plate_lookalikes",
            "uses_downloaded_baseline_models": True,
            "visual_demo": True,
        },
        "database_access": False,
    }
    write_immutable_manifest(manifest_path, result)
    return {
        "ok": True,
        "manifest": str(manifest_path),
        "annotated_video": str(annotated_path),
        "progress_gif": str(gif_path),
        "compressed_video": str(compressed_path),
        "crossing_count": result["crossing_count"],
        "frames_processed": frames_processed,
    }
