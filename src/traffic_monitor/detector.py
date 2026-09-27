"""YOLO26 detection with persistent Ultralytics tracking."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .geometry import point_in_polygon


COCO_VEHICLES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


@dataclass(slots=True)
class Track:
    track_id: int
    bbox: tuple[float, float, float, float]
    last_seen: float
    confidence: float
    class_name: str
    hits: int = 1
    first_seen: float = 0.0

    @property
    def anchor(self) -> tuple[float, float]:
        return ((self.bbox[0] + self.bbox[2]) / 2, self.bbox[3])


class Yolo26Tracker:
    """One YOLO26 model and one persistent tracker per analysis session."""

    def __init__(
        self,
        model_path: str | Path,
        confidence: float = 0.20,
        tracker: str = "fasttrack.yaml",
        image_size: int = 640,
        backend: str = "ultralytics_auto",
    ) -> None:
        from ultralytics import YOLO

        self.model_path = Path(model_path)
        self.confidence = confidence
        self.track_high_thresh = 0.25
        self.track_low_thresh = 0.10
        self.new_track_thresh = 0.25
        self.tracker_config = tracker
        self.image_size = image_size
        self.model = YOLO(str(self.model_path))
        self.model_format = "pytorch"
        self.backend_requested = "ultralytics_auto"
        self.backend_active = "ultralytics_cpu"
        self.backend_error = ""
        self.device = "cpu"
        self.hits: Counter[int] = Counter()
        self.first_seen: dict[int, float] = {}
        self.configure_backend(backend)

    def configure_thresholds(self, high: float, low: float, new: float) -> None:
        """Apply session thresholds to the active Ultralytics tracker in memory."""
        self.track_high_thresh = float(high)
        self.track_low_thresh = float(low)
        self.new_track_thresh = float(new)
        predictor = getattr(self.model, "predictor", None)
        for tracker in getattr(predictor, "trackers", []) or []:
            tracker.args.track_high_thresh = self.track_high_thresh
            tracker.args.track_low_thresh = self.track_low_thresh
            tracker.args.new_track_thresh = self.new_track_thresh

    def configure_backend(self, backend: str) -> bool:
        """Select CUDA/CPU and return True when the active device changed."""
        import torch
        from ultralytics import YOLO

        if backend not in {"ultralytics_auto", "ultralytics_cuda", "openvino_intel_gpu", "ultralytics_cpu"}:
            raise ValueError(f"Nieznany backend: {backend}")
        previous = (self.device, self.model_format)
        self.backend_requested = backend
        if backend == "openvino_intel_gpu":
            try:
                import openvino as ov
                devices = ov.Core().available_devices
                if not any(device == "GPU" or device.startswith("GPU.") for device in devices):
                    raise RuntimeError(f"OpenVINO nie widzi Intel GPU (dostepne: {', '.join(devices) or 'brak'}).")
                exported = self.model_path.with_name(f"{self.model_path.stem}_openvino_model")
                if not exported.is_dir():
                    source = YOLO(str(self.model_path))
                    exported = Path(source.export(format="openvino", imgsz=self.image_size, quantize=16, device="cpu"))
                self.model = YOLO(str(exported), task="detect")
                self.model_format = "openvino"
                self.device = "intel:gpu"
                self.backend_active = "openvino_intel_gpu"
                self.backend_error = ""
            except Exception as error:
                if self.model_format != "pytorch":
                    self.model = YOLO(str(self.model_path))
                    self.model_format = "pytorch"
                self.device = "cpu"
                self.backend_active = "ultralytics_cpu"
                self.backend_error = f"Intel GPU/OpenVINO niedostepne - uzywam CPU: {error}"
            changed = (self.device, self.model_format) != previous
            if changed:
                self.reset()
            return changed

        if self.model_format != "pytorch":
            self.model = YOLO(str(self.model_path))
            self.model_format = "pytorch"
        wants_cuda = backend in {"ultralytics_auto", "ultralytics_cuda"}
        if wants_cuda and torch.cuda.is_available():
            self.device = "0"
            self.backend_active = "ultralytics_cuda"
            self.backend_error = ""
        else:
            self.device = "cpu"
            self.backend_active = "ultralytics_cpu"
            self.backend_error = (
                "CUDA niedostepna - uzywam CPU. Uruchom ponownie run.py po instalacji PyTorch CUDA."
                if backend == "ultralytics_cuda" else ""
            )
        changed = (self.device, self.model_format) != previous
        if changed:
            self.reset()
        return changed

    @staticmethod
    def analysis_crop(
        frame: np.ndarray,
        lanes: list[dict],
        measurement_lines: list[list] | None = None,
        roi: list | None = None,
        margin: float = 0.10,
    ) -> tuple[int, int, int, int]:
        height, width = frame.shape[:2]
        line_points = [point for line in (measurement_lines or []) for point in line]
        points = (roi or []) or line_points or [point for lane in lanes for point in lane.get("polygon", [])]
        if not points:
            return 0, 0, width, height
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        return (
            max(0, math.floor((min(xs) - margin) * width)),
            max(0, math.floor((min(ys) - margin) * height)),
            min(width, math.ceil((max(xs) + margin) * width)),
            min(height, math.ceil((max(ys) + margin) * height)),
        )

    def reset(self) -> None:
        self.hits.clear()
        self.first_seen.clear()
        # Ultralytics creates tracker state lazily in the predictor.
        self.model.predictor = None

    def process(
        self,
        frame: np.ndarray,
        timestamp: float,
        lanes: list[dict],
        line_a: list | None = None,
        line_b: list | None = None,
        roi: list | None = None,
    ) -> list[Track]:
        lines = [line for line in (line_a, line_b) if line and len(line) == 2]
        x1, y1, x2, y2 = self.analysis_crop(frame, lanes, lines, roi)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return []
        result = self.model.track(
            crop,
            persist=True,
            tracker=self.tracker_config,
            conf=self.confidence,
            iou=0.7,
            classes=list(COCO_VEHICLES),
            imgsz=self.image_size,
            device=self.device,
            verbose=False,
        )[0]
        self.configure_thresholds(self.track_high_thresh, self.track_low_thresh, self.new_track_thresh)
        boxes = result.boxes
        if boxes is None or boxes.id is None:
            return []
        xyxy = boxes.xyxy.cpu().numpy()
        ids = boxes.id.int().cpu().tolist()
        classes = boxes.cls.int().cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        height, width = frame.shape[:2]
        tracks: list[Track] = []
        for box, track_id, class_id, confidence in zip(xyxy, ids, classes, confidences):
            bbox = (float(box[0] + x1), float(box[1] + y1),
                    float(box[2] + x1), float(box[3] + y1))
            anchor = ((bbox[0] + bbox[2]) / (2 * width), bbox[3] / height)
            if roi and not point_in_polygon(anchor, [tuple(point) for point in roi]):
                continue
            if lanes and not any(
                point_in_polygon(anchor, [tuple(point) for point in lane.get("polygon", [])])
                for lane in lanes
            ):
                continue
            self.hits[track_id] += 1
            self.first_seen.setdefault(track_id, timestamp)
            tracks.append(Track(
                track_id=track_id,
                bbox=bbox,
                last_seen=timestamp,
                confidence=float(confidence),
                class_name=COCO_VEHICLES.get(class_id, "unknown"),
                hits=self.hits[track_id],
                first_seen=self.first_seen[track_id],
            ))
        return tracks
