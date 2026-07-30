"""Streaming video worker primitives with optional acceleration."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol, Sequence


@dataclass(frozen=True)
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    frame_count: int
    duration_seconds: float


@dataclass(frozen=True)
class Detection:
    bbox: tuple[int, int, int, int]
    confidence: float
    class_name: str = "vehicle"


@dataclass(frozen=True)
class Track:
    track_id: int
    bbox: tuple[int, int, int, int]
    confidence: float
    class_name: str

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)


class Detector(Protocol):
    backend_name: str

    def detect(self, frame: Any, frame_index: int) -> Sequence[Detection]: ...


class Tracker(Protocol):
    backend_name: str

    def update(self, detections: Sequence[Detection], frame_index: int) -> Sequence[Track]: ...


class OpenCVVideo:
    """Probe and yield frames without retaining the full video."""

    @staticmethod
    def _cv2() -> Any:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("OpenCV is required for video decode") from exc
        return cv2

    def probe(self, path: Path) -> VideoInfo:
        cv2 = self._cv2()
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise ValueError(f"cannot open video: {path}")
        try:
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        finally:
            capture.release()
        if width <= 0 or height <= 0:
            raise ValueError("video has invalid dimensions")
        if not math.isfinite(fps) or fps <= 0:
            fps = 0.0
        return VideoInfo(str(path), width, height, fps, frames, frames / fps if fps else 0.0)

    def frames(self, path: Path) -> Iterator[tuple[int, Any]]:
        cv2 = self._cv2()
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise ValueError(f"cannot open video: {path}")
        index = 0
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                yield index, frame
                index += 1
        finally:
            capture.release()


class DeterministicMockDetector:
    """Test/baseline detector; outputs are explicitly non-production."""

    backend_name = "deterministic_mock"

    def detect(self, frame: Any, frame_index: int) -> Sequence[Detection]:
        height, width = frame.shape[:2]
        box_w, box_h = max(8, width // 5), max(8, height // 5)
        travel = max(1, width - box_w)
        x1 = min(travel, frame_index * max(1, width // 30))
        y1 = max(0, height // 2 - box_h // 2)
        return [Detection((x1, y1, x1 + box_w, y1 + box_h), 0.25, "vehicle")]


class OpenCVForegroundDetector:
    backend_name = "opencv_cpu_mog2"

    def __init__(self, min_area: int = 100) -> None:
        import cv2
        self._cv2 = cv2
        self._subtractor = cv2.createBackgroundSubtractorMOG2()
        self._min_area = min_area

    def detect(self, frame: Any, frame_index: int) -> Sequence[Detection]:
        mask = self._subtractor.apply(frame)
        contours, _ = self._cv2.findContours(mask, self._cv2.RETR_EXTERNAL, self._cv2.CHAIN_APPROX_SIMPLE)
        found = []
        for contour in contours:
            x, y, width, height = self._cv2.boundingRect(contour)
            if width * height >= self._min_area:
                found.append(Detection((x, y, x + width, y + height), 0.35))
        return found


class PaddleDetector:
    """Optional adapter; model construction is deferred and never downloaded."""

    backend_name = "paddle_local"

    def __init__(self, predictor: Any) -> None:
        try:
            import paddle  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("Paddle backend requested but paddle is unavailable") from exc
        if predictor is None or not callable(predictor):
            raise ValueError("a configured local Paddle predictor callable is required")
        self._predictor = predictor

    def detect(self, frame: Any, frame_index: int) -> Sequence[Detection]:
        return self._predictor(frame)


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0


class ByteTrackStyleTracker:
    """Small ByteTrack-compatible interface using deterministic IoU association."""

    backend_name = "iou_bytetrack_style"

    def __init__(self, match_threshold: float = 0.2, max_age: int = 30) -> None:
        self.match_threshold = match_threshold
        self.max_age = max_age
        self._next_id = 1
        self._state: dict[int, tuple[Track, int]] = {}

    def update(self, detections: Sequence[Detection], frame_index: int) -> Sequence[Track]:
        candidates = set(self._state)
        tracks: list[Track] = []
        for detection in sorted(detections, key=lambda item: item.confidence, reverse=True):
            best_id = max(candidates, key=lambda item: _iou(detection.bbox, self._state[item][0].bbox), default=None)
            if best_id is None or _iou(detection.bbox, self._state[best_id][0].bbox) < self.match_threshold:
                best_id, self._next_id = self._next_id, self._next_id + 1
            else:
                candidates.remove(best_id)
            track = Track(best_id, detection.bbox, detection.confidence, detection.class_name)
            self._state[best_id] = (track, frame_index)
            tracks.append(track)
        self._state = {
            key: value for key, value in self._state.items()
            if frame_index - value[1] <= self.max_age
        }
        return tracks


@dataclass
class LineCrossingCounter:
    start: tuple[float, float]
    end: tuple[float, float]
    _sides: dict[int, float] = field(default_factory=dict)
    crossed: set[int] = field(default_factory=set)

    def observe(self, track: Track) -> bool:
        px, py = track.center
        side = (self.end[0] - self.start[0]) * (py - self.start[1]) - (self.end[1] - self.start[1]) * (px - self.start[0])
        previous = self._sides.get(track.track_id)
        self._sides[track.track_id] = side
        if previous is not None and previous * side < 0 and track.track_id not in self.crossed:
            self.crossed.add(track.track_id)
            return True
        return False


class BestFrameSelector:
    def __init__(self) -> None:
        self.best: dict[int, dict[str, Any]] = {}

    def observe(self, track: Track, frame: Any, frame_index: int) -> None:
        x1, y1, x2, y2 = track.bbox
        crop = frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
        if getattr(crop, "size", 0) == 0:
            return
        try:
            import cv2
            sharpness = float(cv2.Laplacian(crop, cv2.CV_64F).var())
        except ImportError:
            sharpness = float((x2 - x1) * (y2 - y1))
        score = sharpness * max(0.0, track.confidence)
        if score > self.best.get(track.track_id, {}).get("score", -1):
            self.best[track.track_id] = {"frame_index": frame_index, "score": score, "crop": crop.copy()}


@dataclass(frozen=True)
class OCRResult:
    raw: str
    normalized: str
    confidence: float
    mode: str
    production_russian_ocr: bool = False
    normalized_latin: str = ""
    translation: str = "latin_to_russian_plate_lookalikes"


# Official Russian plate letters that visually match Latin glyphs.
# Recognition runs on the downloaded latin/chinese baseline model; output is
# translated locally into the Russian plate alphabet without claiming HF Cyrillic OCR.
LATIN_TO_RUSSIAN_PLATE = {
    "0": "0",
    "1": "1",
    "2": "2",
    "3": "3",
    "4": "4",
    "5": "5",
    "6": "6",
    "7": "7",
    "8": "8",
    "9": "9",
    "A": "А",
    "B": "В",
    "C": "С",
    "E": "Е",
    "H": "Н",
    "K": "К",
    "M": "М",
    "O": "О",
    "P": "Р",
    "T": "Т",
    "X": "Х",
    "Y": "У",
}
RUSSIAN_TO_LATIN_PLATE = {value: key for key, value in LATIN_TO_RUSSIAN_PLATE.items() if not key.isdigit()}


def normalize_latin_plate(raw: str) -> str:
    """Keep only Latin plate lookalike glyphs and digits from OCR output."""
    latin_chars: list[str] = []
    for char in str(raw).upper():
        if char in LATIN_TO_RUSSIAN_PLATE:
            latin_chars.append(char)
        elif char in RUSSIAN_TO_LATIN_PLATE:
            latin_chars.append(RUSSIAN_TO_LATIN_PLATE[char])
    return "".join(latin_chars)


def translate_latin_plate_to_russian(latin: str) -> str:
    """Map Latin OCR glyphs to the Russian plate alphabet by visual similarity."""
    return "".join(LATIN_TO_RUSSIAN_PLATE[char] for char in latin if char in LATIN_TO_RUSSIAN_PLATE)


class PlateOCRAdapter:
    """Latin-baseline OCR with local Russian plate transliteration."""

    ALLOWLIST = frozenset(LATIN_TO_RUSSIAN_PLATE)

    def __init__(self, recognizer: Any | None = None, mode: str = "latin") -> None:
        if mode not in {"baseline", "latin", "local_allowlist"}:
            raise ValueError("OCR mode must be baseline, latin, or local_allowlist")
        self.recognizer, self.mode = recognizer, mode

    def recognize(self, crop: Any) -> OCRResult:
        if self.recognizer is None:
            return OCRResult("", "", 0.0, self.mode, normalized_latin="")
        raw, confidence = self.recognizer(crop)
        latin = normalize_latin_plate(str(raw))
        russian = translate_latin_plate_to_russian(latin)
        return OCRResult(
            str(raw),
            russian,
            float(confidence),
            self.mode,
            production_russian_ocr=False,
            normalized_latin=latin,
        )


class PlateAdapter:
    """Optional local plate detector followed by an explicit OCR adapter."""

    def __init__(self, ocr: PlateOCRAdapter, detector: Any | None = None) -> None:
        self.ocr, self.detector = ocr, detector

    def analyze(self, vehicle_crop: Any) -> dict[str, Any]:
        if self.detector is None:
            plate_crop, bbox, confidence = vehicle_crop, None, 0.0
        else:
            detected = self.detector(vehicle_crop)
            if detected is None:
                return {
                    "bbox": None,
                    "detection_confidence": 0.0,
                    "ocr": asdict(OCRResult("", "", 0.0, self.ocr.mode)),
                }
            plate_crop, bbox, confidence = detected
        return {
            "bbox": bbox,
            "detection_confidence": float(confidence),
            "ocr": asdict(self.ocr.recognize(plate_crop)),
        }


def compress_video(source: Path, destination: Path, prefer_nvenc: bool = True) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is unavailable")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    codecs = ["h264_nvenc", "libx264"] if prefer_nvenc else ["libx264"]
    errors = []
    for codec in codecs:
        command = [ffmpeg, "-nostdin", "-v", "error", "-i", str(source), "-c:v", codec, "-an", str(destination)]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode == 0:
            return {"codec": codec, "path": str(destination), "size_bytes": destination.stat().st_size}
        destination.unlink(missing_ok=True)
        errors.append(f"{codec}: {completed.stderr.strip()}")
    raise RuntimeError("; ".join(errors))


def write_immutable_manifest(path: Path, payload: dict[str, Any]) -> None:
    """Atomically creates a canonical result and refuses replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


class VideoPipeline:
    def __init__(
        self,
        detector: Detector,
        tracker: Tracker,
        ocr: PlateOCRAdapter,
        plate_detector: Any | None = None,
    ) -> None:
        self.detector, self.tracker, self.ocr = detector, tracker, ocr
        self.plate = PlateAdapter(ocr, plate_detector)
        self.video = OpenCVVideo()

    def process(self, source: Path, line: tuple[tuple[float, float], tuple[float, float]]) -> dict[str, Any]:
        info = self.video.probe(source)
        counter, selector = LineCrossingCounter(*line), BestFrameSelector()
        frame_total = 0
        for frame_index, frame in self.video.frames(source):
            frame_total += 1
            for track in self.tracker.update(self.detector.detect(frame, frame_index), frame_index):
                counter.observe(track)
                selector.observe(track, frame, frame_index)
        observations = []
        for track_id, selected in sorted(selector.best.items()):
            plate = self.plate.analyze(selected["crop"])
            observations.append({
                "track_id": track_id,
                "best_frame_index": selected["frame_index"],
                "best_frame_score": selected["score"],
                "plate": plate,
                "plate_ocr": plate["ocr"],
            })
        return {
            "schema_version": "gpu-result-1",
            "video": asdict(info),
            "frames_processed": frame_total,
            "detector_backend": self.detector.backend_name,
            "tracker_backend": self.tracker.backend_name,
            "crossing_count": len(counter.crossed),
            "tracks": observations,
            "limitations": {
                "production_vehicle_detection": self.detector.backend_name not in {"deterministic_mock", "opencv_cpu_mog2"},
                "production_russian_ocr": False,
                "ocr_mode": self.ocr.mode,
                "ocr_translation": "latin_to_russian_plate_lookalikes",
                "uses_downloaded_baseline_models": True,
            },
        }
