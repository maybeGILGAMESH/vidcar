from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np

from gpu_worker.core import (
    ByteTrackStyleTracker,
    DeterministicMockDetector,
    PlateOCRAdapter,
    VideoPipeline,
    compress_video,
    write_immutable_manifest,
)


@pytest.fixture
def tiny_video(tmp_path: Path) -> Path:
    path = tmp_path / "tiny.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (96, 64))
    if not writer.isOpened():
        pytest.skip("OpenCV video writer codec is unavailable")
    for index in range(40):
        frame = np.zeros((64, 96, 3), dtype=np.uint8)
        cv2.rectangle(frame, (index * 2, 24), (min(95, index * 2 + 18), 40), (255, 255, 255), -1)
        writer.write(frame)
    writer.release()
    return path


def test_generated_video_pipeline_marks_baseline_limitations(tiny_video: Path) -> None:
    pipeline = VideoPipeline(
        DeterministicMockDetector(),
        ByteTrackStyleTracker(),
        PlateOCRAdapter(mode="latin"),
    )

    result = pipeline.process(tiny_video, ((48.0, 0.0), (48.0, 64.0)))

    assert result["frames_processed"] == 40
    assert result["crossing_count"] == 1
    assert result["limitations"] == {
        "production_vehicle_detection": False,
        "production_russian_ocr": False,
        "ocr_mode": "latin",
        "ocr_translation": "latin_to_russian_plate_lookalikes",
        "uses_downloaded_baseline_models": True,
    }
    assert result["tracks"][0]["plate_ocr"]["confidence"] == 0.0


def test_ocr_translates_latin_lookalikes_to_russian_plate() -> None:
    ocr = PlateOCRAdapter(lambda crop: ("аB-12ZxY", 0.71), mode="latin")

    result = ocr.recognize(object())

    assert result.raw == "аB-12ZxY"
    assert result.normalized_latin == "AB12XY"
    assert result.normalized == "АВ12ХУ"
    assert result.confidence == pytest.approx(0.71)
    assert result.production_russian_ocr is False
    assert result.translation == "latin_to_russian_plate_lookalikes"


def test_manifest_is_canonical_and_immutable(tmp_path: Path) -> None:
    target = tmp_path / "result.json"
    write_immutable_manifest(target, {"z": 1, "a": 2})

    assert target.read_text() == '{"a":2,"z":1}\n'
    with pytest.raises(FileExistsError):
        write_immutable_manifest(target, {"replacement": True})


def test_ffmpeg_cpu_compression(tiny_video: Path, tmp_path: Path) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is unavailable")
    destination = tmp_path / "compressed.mp4"

    metadata = compress_video(tiny_video, destination, prefer_nvenc=False)

    assert metadata["codec"] == "libx264"
    assert destination.stat().st_size > 0
    with pytest.raises(FileExistsError):
        compress_video(tiny_video, destination, prefer_nvenc=False)
