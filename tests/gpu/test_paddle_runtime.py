from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from gpu_worker.paddle_runtime import (
    PaddleRuntimeError,
    decode_vehicle_attributes,
    load_infer_cfg,
    preprocess_bgr,
    require_paddle_gpu,
    resolve_unpacked_dir,
)


REPO = Path(__file__).resolve().parents[2]
APPROVED = REPO / ".runtime" / "model-registry" / "approved"
MANIFEST = REPO / "models" / "manifests" / "vehicle-pipeline-0.1.0.yaml"
VEHICLE_UNPACKED = APPROVED / "vehicle-detector" / "0.1.0" / "unpacked"
FIXTURE = REPO / "tests" / "fixtures" / "videos" / "car-detection.mp4"


def test_decode_vehicle_attributes_splits_color_and_type() -> None:
    vec = np.zeros(19, dtype=np.float32)
    vec[6] = 0.91  # white
    vec[10 + 0] = 0.88  # sedan
    decoded = decode_vehicle_attributes(vec, threshold=0.5)
    assert decoded["production_size_taxonomy"] is False
    assert decoded["values"]["color"]["label"] == "white"
    assert decoded["values"]["type"]["label"] == "sedan"
    assert decoded["values"]["color"]["argmax"] == 6
    assert decoded["values"]["type"]["argmax"] == 0


def test_decode_vehicle_attributes_unknown_below_threshold() -> None:
    vec = np.zeros(19, dtype=np.float32)
    vec[4] = 0.2
    vec[15] = 0.3
    decoded = decode_vehicle_attributes(vec, threshold=0.5)
    assert decoded["values"]["color"]["label"] == "unknown"
    assert decoded["values"]["type"]["label"] == "unknown"


def test_decode_vehicle_attributes_rejects_short_vector() -> None:
    with pytest.raises(PaddleRuntimeError):
        decode_vehicle_attributes(np.zeros(10, dtype=np.float32))


def test_resolve_unpacked_dir_from_manifest_meta() -> None:
    meta = {"unpacked_dir": "vehicle-detector/0.1.0/unpacked", "path": "vehicle-detector/0.1.0/model.zip"}
    if not APPROVED.is_dir():
        pytest.skip("approved models not present")
    path = resolve_unpacked_dir(APPROVED, meta)
    assert path == VEHICLE_UNPACKED.resolve()
    assert (path / "model.pdmodel").is_file()


def test_resolve_unpacked_dir_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(PaddleRuntimeError):
        resolve_unpacked_dir(tmp_path, {"unpacked_dir": "../escape"})


def test_preprocess_ppvehicle_keeps_0_255_without_normalize() -> None:
    if not VEHICLE_UNPACKED.is_dir():
        pytest.skip("vehicle unpacked model missing")
    cfg = load_infer_cfg(VEHICLE_UNPACKED)
    frame = np.zeros((432, 768, 3), dtype=np.uint8)
    frame[100:300, 200:500] = 180
    batch, meta = preprocess_bgr(frame, cfg)
    assert batch.shape == (1, 3, 640, 640)
    assert float(batch.max()) > 1.0  # not /255 normalized
    assert meta["orig_w"] == 768.0


def test_paddle_gpu_preflight_and_detection_smoke() -> None:
    if not FIXTURE.is_file() or not MANIFEST.is_file() or not APPROVED.is_dir():
        pytest.skip("paddle demo fixtures/models unavailable")
    try:
        require_paddle_gpu()
    except PaddleRuntimeError as exc:
        pytest.skip(str(exc))

    import cv2

    from gpu_worker.paddle_runtime import PaddleVehicleDetector, build_paddle_backends

    bundle = build_paddle_backends(APPROVED, MANIFEST)
    assert bundle.detector.backend_name == "paddle_ppvehicle"

    detector = PaddleVehicleDetector(VEHICLE_UNPACKED)
    cap = cv2.VideoCapture(str(FIXTURE))
    assert cap.isOpened()
    found = 0
    for index in range(0, 120, 5):
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok:
            break
        found = max(found, len(detector.detect(frame, index)))
        if found >= 1:
            break
    cap.release()
    assert found >= 1
