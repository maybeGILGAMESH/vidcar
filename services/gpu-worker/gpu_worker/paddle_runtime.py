"""Paddle Inference helpers for approved PPVehicle / OCR models."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import yaml

from .core import Detection


class PaddleRuntimeError(RuntimeError):
    pass


def require_paddle_gpu() -> Any:
    try:
        import paddle
        from paddle import inference
    except ImportError as exc:
        raise PaddleRuntimeError(
            "paddlepaddle-gpu is not installed in the project environment"
        ) from exc
    if not paddle.device.is_compiled_with_cuda():
        raise PaddleRuntimeError("paddle is not compiled with CUDA")
    try:
        count = paddle.device.cuda.device_count()
    except Exception as exc:  # noqa: BLE001
        raise PaddleRuntimeError(f"cannot query CUDA devices: {exc}") from exc
    if count < 1:
        raise PaddleRuntimeError("no CUDA device visible to paddle")
    return inference


def resolve_model_files(unpacked_dir: Path, prefix: str = "model") -> tuple[Path, Path]:
    model = unpacked_dir / f"{prefix}.pdmodel"
    params = unpacked_dir / f"{prefix}.pdiparams"
    if not model.is_file() or not params.is_file():
        # OCR archives use inference.* names
        alt_model = unpacked_dir / "inference.pdmodel"
        alt_params = unpacked_dir / "inference.pdiparams"
        if alt_model.is_file() and alt_params.is_file():
            return alt_model, alt_params
        raise PaddleRuntimeError(f"missing paddle model files under {unpacked_dir}")
    return model, params


def load_infer_cfg(unpacked_dir: Path) -> dict[str, Any]:
    cfg_path = unpacked_dir / "infer_cfg.yml"
    if not cfg_path.is_file():
        return {}
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise PaddleRuntimeError(f"invalid infer_cfg.yml in {unpacked_dir}")
    return data


def create_predictor(unpacked_dir: Path, prefix: str = "model", *, use_gpu: bool = True) -> Any:
    inference = require_paddle_gpu()
    model, params = resolve_model_files(unpacked_dir, prefix)
    config = inference.Config(str(model), str(params))
    if use_gpu:
        config.enable_use_gpu(256, 0)
    else:
        config.disable_gpu()
    config.switch_ir_optim(True)
    config.enable_memory_optim()
    config.disable_glog_info()
    return inference.create_predictor(config)


def _resize_image(image: np.ndarray, target_size: Sequence[int], keep_ratio: bool) -> tuple[np.ndarray, float, float]:
    import cv2

    height, width = image.shape[:2]
    tw, th = int(target_size[0]), int(target_size[1])
    if keep_ratio:
        scale = min(tw / width, th / height)
        nw, nh = max(1, int(round(width * scale))), max(1, int(round(height * scale)))
        resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.zeros((th, tw, 3), dtype=resized.dtype)
        canvas[:nh, :nw] = resized
        return canvas, scale, scale
    resized = cv2.resize(image, (tw, th), interpolation=cv2.INTER_LINEAR)
    return resized, tw / width, th / height


def preprocess_bgr(
    image: np.ndarray,
    cfg: dict[str, Any],
    *,
    default_size: tuple[int, int] = (640, 640),
) -> tuple[np.ndarray, dict[str, float]]:
    """Return NCHW float32 batch and scale metadata for YOLO-style detectors.

    PaddleDetection deploy preprocess: Resize (+ optional NormalizeImage) then Permute.
    PPVehicle infer_cfg has only Resize+Permute — keep BGR float32 in 0..255 (no /255).
    """
    ops = cfg.get("Preprocess") or []
    target_size = list(default_size)
    keep_ratio = False
    normalize: dict[str, Any] | None = None
    for op in ops:
        if not isinstance(op, dict):
            continue
        if op.get("type") == "Resize":
            target_size = list(op.get("target_size") or target_size)
            keep_ratio = bool(op.get("keep_ratio", False))
        elif op.get("type") == "NormalizeImage":
            normalize = op

    # PaddleDetection Resize target_size is [h, w]
    if len(target_size) == 2:
        th, tw = int(target_size[0]), int(target_size[1])
    else:
        th = tw = 640

    resized, scale_x, scale_y = _resize_image(image, (tw, th), keep_ratio)
    if normalize is not None:
        # NormalizeImage operates on RGB in PaddleDetection when is_scale is set
        rgb = resized[:, :, ::-1].astype(np.float32)
        if bool(normalize.get("is_scale", True)):
            rgb = rgb / 255.0
        mean = np.array(normalize.get("mean") or [0.0, 0.0, 0.0], dtype=np.float32)
        std = np.array(normalize.get("std") or [1.0, 1.0, 1.0], dtype=np.float32)
        rgb = (rgb - mean) / std
        nchw = np.transpose(rgb, (2, 0, 1))[None, ...].astype(np.float32)
    else:
        # Permute only: BGR HWC -> CHW, keep 0..255
        nchw = np.transpose(resized.astype(np.float32), (2, 0, 1))[None, ...]
    meta = {
        "scale_x": float(scale_x),
        "scale_y": float(scale_y),
        "orig_w": float(image.shape[1]),
        "orig_h": float(image.shape[0]),
        "input_w": float(tw),
        "input_h": float(th),
    }
    return nchw, meta


def run_predictor(predictor: Any, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
    input_names = predictor.get_input_names()
    for name in input_names:
        handle = predictor.get_input_handle(name)
        if name not in feeds:
            # common aliases
            if "image" in feeds and ("image" in name or name.endswith("image")):
                handle.copy_from_cpu(feeds["image"])
            elif "im_shape" in feeds and "im_shape" in name:
                handle.copy_from_cpu(feeds["im_shape"])
            elif "scale_factor" in feeds and "scale_factor" in name:
                handle.copy_from_cpu(feeds["scale_factor"])
            else:
                raise PaddleRuntimeError(f"no feed provided for input {name}")
        else:
            handle.copy_from_cpu(feeds[name])
    predictor.run()
    outputs = []
    for name in predictor.get_output_names():
        outputs.append(predictor.get_output_handle(name).copy_to_cpu())
    return outputs


@dataclass
class PaddleVehicleDetector:
    unpacked_dir: Path
    threshold: float = 0.5
    backend_name: str = "paddle_ppvehicle"

    def __post_init__(self) -> None:
        self.cfg = load_infer_cfg(self.unpacked_dir)
        self.threshold = float(self.cfg.get("draw_threshold", self.threshold))
        labels = self.cfg.get("label_list") or ["vehicle"]
        self.labels = [str(x) for x in labels]
        self.predictor = create_predictor(self.unpacked_dir, prefix="model")

    def detect(self, frame: Any, frame_index: int) -> Sequence[Detection]:
        del frame_index
        image = np.asarray(frame)
        batch, meta = preprocess_bgr(image, self.cfg, default_size=(640, 640))
        im_shape = np.array([[meta["input_h"], meta["input_w"]]], dtype=np.float32)
        scale_factor = np.array([[meta["scale_y"], meta["scale_x"]]], dtype=np.float32)
        feeds = {
            "image": batch,
            "im_shape": im_shape,
            "scale_factor": scale_factor,
        }
        # Map to actual input names
        names = self.predictor.get_input_names()
        named_feeds: dict[str, np.ndarray] = {}
        for name in names:
            key = name.split(":")[-1]
            if "image" in key:
                named_feeds[name] = batch
            elif "im_shape" in key:
                named_feeds[name] = im_shape
            elif "scale_factor" in key:
                named_feeds[name] = scale_factor
            elif name in feeds:
                named_feeds[name] = feeds[name]
        outputs = run_predictor(self.predictor, named_feeds)
        return self._parse_yolo_outputs(outputs, meta)

    def _parse_yolo_outputs(self, outputs: list[np.ndarray], meta: dict[str, float]) -> list[Detection]:
        if not outputs:
            return []
        # PaddleDetection deploy YOLO usually returns [N, 6] => cls, score, x1,y1,x2,y2 in original image space
        # or [N, 6] with scale already applied when scale_factor fed.
        arr = outputs[0]
        if arr.ndim == 1:
            if arr.size == 0:
                return []
            arr = arr.reshape(-1, arr.size if arr.size <= 6 else 6)
        if arr.ndim != 2 or arr.shape[1] < 6:
            # fallback: try second output
            for candidate in outputs[1:]:
                if candidate.ndim == 2 and candidate.shape[1] >= 6:
                    arr = candidate
                    break
            else:
                return []

        detections: list[Detection] = []
        ow, oh = int(meta["orig_w"]), int(meta["orig_h"])
        for row in arr:
            if row.shape[0] >= 6:
                cls_id, score, x1, y1, x2, y2 = row[:6]
            else:
                continue
            score_f = float(score)
            if score_f < self.threshold or not math.isfinite(score_f):
                continue
            # If boxes look normalized to input size, map back
            if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= meta["input_w"] + 1 and ow > meta["input_w"]:
                # likely already in original coords from paddle det; keep
                pass
            bx1 = int(max(0, min(ow - 1, round(float(x1)))))
            by1 = int(max(0, min(oh - 1, round(float(y1)))))
            bx2 = int(max(0, min(ow - 1, round(float(x2)))))
            by2 = int(max(0, min(oh - 1, round(float(y2)))))
            if bx2 <= bx1 or by2 <= by1:
                continue
            label = self.labels[int(cls_id)] if 0 <= int(cls_id) < len(self.labels) else "vehicle"
            detections.append(Detection((bx1, by1, bx2, by2), score_f, label))
        return detections


@dataclass
class PlateDetection:
    crop: Any
    bbox: tuple[int, int, int, int] | None
    confidence: float
    fallback_full_crop: bool = False


@dataclass
class PaddlePlateDetector:
    unpacked_dir: Path
    threshold: float = 0.3

    def __post_init__(self) -> None:
        self.predictor = create_predictor(self.unpacked_dir, prefix="inference")

    def __call__(self, vehicle_crop: Any) -> PlateDetection | None:
        import cv2

        image = np.asarray(vehicle_crop)
        if image.size == 0:
            return None
        h, w = image.shape[:2]
        # DB det expects image + ratio; use simple resized feed
        target = 640
        scale = min(target / max(h, w), 1.0)
        nh, nw = max(1, int(h * scale)), max(1, int(w * scale))
        resized = cv2.resize(image, (nw, nh))
        canvas = np.zeros((target, target, 3), dtype=np.uint8)
        canvas[:nh, :nw] = resized
        rgb = canvas[:, :, ::-1].astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        rgb = (rgb - mean) / std
        nchw = np.transpose(rgb, (2, 0, 1))[None, ...]
        names = self.predictor.get_input_names()
        feeds = {names[0]: nchw.astype(np.float32)}
        outputs = run_predictor(self.predictor, feeds)
        box = self._largest_box(outputs, scale, w, h, nh, nw)
        if box is None:
            return PlateDetection(
                crop=image,
                bbox=(0, 0, w - 1, h - 1),
                confidence=0.05,
                fallback_full_crop=True,
            )
        x1, y1, x2, y2, score = box
        if score < self.threshold:
            return PlateDetection(
                crop=image,
                bbox=(x1, y1, x2, y2),
                confidence=float(score),
                fallback_full_crop=True,
            )
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        return PlateDetection(
            crop=crop,
            bbox=(x1, y1, x2, y2),
            confidence=float(score),
            fallback_full_crop=False,
        )

    def _largest_box(
        self,
        outputs: list[np.ndarray],
        scale: float,
        orig_w: int,
        orig_h: int,
        nh: int,
        nw: int,
    ) -> tuple[int, int, int, int, float] | None:
        # OCR det output varies; try to interpret as bitmap or boxes
        if not outputs:
            return None
        arr = outputs[0]
        if arr.ndim >= 2 and arr.shape[-1] != 4:
            # probability map -> bbox via threshold
            heat = arr.squeeze()
            if heat.ndim != 2:
                return None
            mask = heat > 0.3
            if not mask.any():
                return None
            ys, xs = np.where(mask)
            x1, x2 = int(xs.min()), int(xs.max())
            y1, y2 = int(ys.min()), int(ys.max())
            score = float(heat[mask].mean())
        elif arr.ndim == 2 and arr.shape[1] >= 4:
            # boxes
            areas = []
            for row in arr:
                x1, y1, x2, y2 = [float(v) for v in row[:4]]
                areas.append(((x2 - x1) * (y2 - y1), x1, y1, x2, y2, float(row[4] if row.shape[0] > 4 else 0.5)))
            if not areas:
                return None
            _, x1, y1, x2, y2, score = max(areas, key=lambda item: item[0])
        else:
            return None

        # map from resized canvas coords back
        if scale <= 0:
            scale = 1.0
        bx1 = int(max(0, min(orig_w - 1, round(x1 / scale))))
        by1 = int(max(0, min(orig_h - 1, round(y1 / scale))))
        bx2 = int(max(0, min(orig_w - 1, round(x2 / scale))))
        by2 = int(max(0, min(orig_h - 1, round(y2 / scale))))
        if bx2 <= bx1 or by2 <= by1:
            return None
        return bx1, by1, bx2, by2, score


@dataclass
class PaddlePlateRecognizer:
    """Returns (raw_text, confidence) for PlateOCRAdapter."""

    unpacked_dir: Path

    def __post_init__(self) -> None:
        self.predictor = create_predictor(self.unpacked_dir, prefix="inference")
        # PP-OCRv3 latin/chinese dictionary subset: digits + upper letters commonly used
        self.charset = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def __call__(self, crop: Any) -> tuple[str, float]:
        import cv2

        image = np.asarray(crop)
        if image.size == 0:
            return "", 0.0
        h, w = image.shape[:2]
        target_h = 48
        scale = target_h / max(h, 1)
        nw = max(1, int(round(w * scale)))
        resized = cv2.resize(image, (nw, target_h))
        # pad/truncate width to 320
        target_w = 320
        canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        use_w = min(nw, target_w)
        canvas[:, :use_w] = resized[:, :use_w]
        rgb = canvas[:, :, ::-1].astype(np.float32) / 255.0
        rgb = (rgb - 0.5) / 0.5
        nchw = np.transpose(rgb, (2, 0, 1))[None, ...]
        names = self.predictor.get_input_names()
        outputs = run_predictor(self.predictor, {names[0]: nchw.astype(np.float32)})
        return self._decode(outputs)

    def _decode(self, outputs: list[np.ndarray]) -> tuple[str, float]:
        if not outputs:
            return "", 0.0
        arr = outputs[0]
        # CTC: [1, T, C] or [T, C]
        if arr.ndim == 3:
            arr = arr[0]
        if arr.ndim != 2:
            return "", 0.0
        probs = arr
        ids = probs.argmax(axis=1)
        confs = probs.max(axis=1)
        chars: list[str] = []
        scores: list[float] = []
        prev = -1
        blank = 0
        for idx, conf in zip(ids.tolist(), confs.tolist()):
            if idx == blank or idx == prev:
                prev = idx
                continue
            prev = idx
            # index 1.. maps into charset roughly; clamp
            symbol_index = int(idx) - 1
            if 0 <= symbol_index < len(self.charset):
                chars.append(self.charset[symbol_index])
                scores.append(float(conf))
        text = "".join(chars)
        confidence = float(sum(scores) / len(scores)) if scores else 0.0
        return text, confidence


# Upstream PPVehicle / PULC VehicleAttr (VeRi): single 19-d vector.
COLOR_LABELS = (
    "yellow",
    "orange",
    "green",
    "gray",
    "red",
    "blue",
    "white",
    "golden",
    "brown",
    "black",
)
TYPE_LABELS = (
    "sedan",
    "suv",
    "van",
    "hatchback",
    "mpv",
    "pickup",
    "bus",
    "truck",
    "estate",
)


def decode_vehicle_attributes(
    vector: np.ndarray,
    *,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Decode a length-19 VehicleAttr logit/prob vector into color + type labels."""
    vec = np.asarray(vector, dtype=np.float32).reshape(-1)
    if vec.size < 19:
        raise PaddleRuntimeError(f"expected >=19 attribute scores, got {vec.size}")
    color_slice = vec[:10]
    type_slice = vec[10:19]
    color_idx = int(color_slice.argmax())
    type_idx = int(type_slice.argmax())
    color_score = float(color_slice[color_idx])
    type_score = float(type_slice[type_idx])
    values: dict[str, Any] = {
        "color": {
            "label": COLOR_LABELS[color_idx] if color_score >= threshold else "unknown",
            "argmax": color_idx,
            "score": color_score,
        },
        "type": {
            "label": TYPE_LABELS[type_idx] if type_score >= threshold else "unknown",
            "argmax": type_idx,
            "score": type_score,
        },
    }
    return {
        "backend": "paddle_attributes",
        "production_size_taxonomy": False,
        "taxonomy": "veri_color_body_style",
        "values": values,
    }


@dataclass
class PaddleAttributeClassifier:
    unpacked_dir: Path
    threshold: float = 0.5

    def __post_init__(self) -> None:
        self.cfg = load_infer_cfg(self.unpacked_dir)
        self.predictor = create_predictor(self.unpacked_dir, prefix="model")

    def classify(self, crop: Any) -> dict[str, Any]:
        image = np.asarray(crop)
        if image.size == 0:
            return {
                "backend": "paddle_attributes",
                "production_size_taxonomy": False,
                "taxonomy": "veri_color_body_style",
                "values": {},
            }
        batch, _meta = preprocess_bgr(image, self.cfg, default_size=(192, 256))
        names = self.predictor.get_input_names()
        outputs = run_predictor(self.predictor, {names[0]: batch})
        if not outputs:
            return {
                "backend": "paddle_attributes",
                "production_size_taxonomy": False,
                "taxonomy": "veri_color_body_style",
                "values": {},
            }
        # Prefer concatenated 19-d vector (single output); else concat heads.
        if len(outputs) == 1:
            vec = outputs[0].reshape(-1)
        else:
            vec = np.concatenate([o.reshape(-1) for o in outputs], axis=0)
        return decode_vehicle_attributes(vec, threshold=self.threshold)


def _load_manifest_dict(manifest_path: Path) -> dict[str, Any]:
    text = manifest_path.read_text(encoding="utf-8")
    if manifest_path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        import json

        data = json.loads(text)
    if not isinstance(data, dict):
        raise PaddleRuntimeError(f"invalid manifest: {manifest_path}")
    return data


def resolve_unpacked_dir(approved_root: Path, role_meta: dict[str, Any]) -> Path:
    relative = role_meta.get("unpacked_dir")
    if relative:
        path = Path(str(relative))
        if path.is_absolute() or ".." in path.parts:
            raise PaddleRuntimeError(f"invalid unpacked_dir: {relative}")
        candidate = (approved_root / path).resolve()
    else:
        archive_rel = Path(str(role_meta.get("path", "")))
        candidate = (approved_root / archive_rel.parent / "unpacked").resolve()
    if not candidate.is_dir():
        raise PaddleRuntimeError(f"unpacked model dir missing: {candidate}")
    return candidate


@dataclass
class PaddleBackendBundle:
    detector: PaddleVehicleDetector
    plate_detector: PaddlePlateDetector
    plate_recognizer: PaddlePlateRecognizer
    attributes: PaddleAttributeClassifier | None
    model_versions: dict[str, str]
    approved_root: Path
    pipeline_version: str


def build_paddle_backends(
    approved_root: Path,
    manifest_path: Path,
    *,
    include_attributes: bool = True,
) -> PaddleBackendBundle:
    """Fail-closed construction of Paddle GPU backends from approved unpacked models."""
    require_paddle_gpu()
    approved_root = approved_root.resolve()
    manifest = _load_manifest_dict(manifest_path)
    models = manifest.get("models")
    if not isinstance(models, dict):
        raise PaddleRuntimeError("manifest.models must be an object")
    required = ("vehicle_detector", "plate_detector", "plate_ocr")
    missing = [role for role in required if role not in models]
    if missing:
        raise PaddleRuntimeError(f"manifest missing roles: {', '.join(missing)}")

    vehicle_meta = models["vehicle_detector"]
    plate_det_meta = models["plate_detector"]
    plate_ocr_meta = models["plate_ocr"]
    vehicle_dir = resolve_unpacked_dir(approved_root, vehicle_meta)
    plate_det_dir = resolve_unpacked_dir(approved_root, plate_det_meta)
    plate_ocr_dir = resolve_unpacked_dir(approved_root, plate_ocr_meta)

    attributes = None
    attr_version = None
    if include_attributes and "vehicle_attributes" in models:
        attr_meta = models["vehicle_attributes"]
        attributes = PaddleAttributeClassifier(resolve_unpacked_dir(approved_root, attr_meta))
        attr_version = str(attr_meta.get("version", ""))

    versions = {
        "vehicle_detector": str(vehicle_meta.get("version", "")),
        "plate_detector": str(plate_det_meta.get("version", "")),
        "plate_ocr": str(plate_ocr_meta.get("version", "")),
    }
    if attr_version is not None:
        versions["vehicle_attributes"] = attr_version

    return PaddleBackendBundle(
        detector=PaddleVehicleDetector(vehicle_dir),
        plate_detector=PaddlePlateDetector(plate_det_dir),
        plate_recognizer=PaddlePlateRecognizer(plate_ocr_dir),
        attributes=attributes,
        model_versions=versions,
        approved_root=approved_root,
        pipeline_version=str(manifest.get("pipeline_version") or "unknown"),
    )


def gpu_memory_brief() -> str:
    try:
        import paddle

        # Paddle 3.x may expose reserved/allocated differently across builds.
        allocated = 0
        reserved = 0
        try:
            allocated = int(paddle.device.cuda.memory_allocated(0))
            reserved = int(paddle.device.cuda.memory_reserved(0))
        except Exception:  # noqa: BLE001
            pass
        if allocated == 0 and reserved == 0:
            try:
                props = paddle.device.cuda.get_device_properties(0)
                total = getattr(props, "total_memory", 0) or 0
                return f"gpu0_total_mb={total / (1024 ** 2):.0f}"
            except Exception:  # noqa: BLE001
                return "gpu=cuda:0"
        return f"vram_alloc_mb={allocated / (1024 ** 2):.0f} reserved_mb={reserved / (1024 ** 2):.0f}"
    except Exception:  # noqa: BLE001
        return "vram=n/a"
