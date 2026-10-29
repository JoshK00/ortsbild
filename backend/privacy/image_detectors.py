from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from PIL import Image

from models.sanitized_report import RedactionKind


@dataclass(frozen=True)
class Box:
    """A rectangle in an image (pixel positions, right and bottom exclusive) and what is in it."""

    left: int
    top: int
    right: int
    bottom: int
    kind: RedactionKind
    confidence: float | None = None


class FaceDetector(Protocol):
    """Anything that can find faces in an image. Detectors are interchangeable."""

    def detect(self, image: Image.Image) -> list[Box]: ...


def _overlap_ratio(a: Box, b: Box) -> float:
    """Intersection over union of two boxes, 0 if they do not touch."""
    inter_w = max(0, min(a.right, b.right) - max(a.left, b.left))
    inter_h = max(0, min(a.bottom, b.bottom) - max(a.top, b.top))
    inter = inter_w * inter_h
    union = (a.right - a.left) * (a.bottom - a.top) + (b.right - b.left) * (b.bottom - b.top) - inter
    return inter / union if union else 0.0


def merge_overlapping(boxes: list[Box], min_overlap: float = 0.3) -> list[Box]:
    """Keep one box per spot: of boxes that overlap strongly the most confident one stays.

    The full image pass and the overlapping tiles find the same face several times. Without this the
    redaction log would count one face many times.
    """
    kept: list[Box] = []
    for box in sorted(boxes, key=lambda b: -(b.confidence or 0.0)):
        if all(_overlap_ratio(box, other) < min_overlap for other in kept):
            kept.append(box)
    return kept


YUNET_MODEL_PATH = Path(__file__).resolve().parent.parent / "assets" / "face_detection_yunet_2023mar.onnx"


class YuNetFaceDetector:
    """Finds faces with the small YuNet model (227 KB, CPU, about 80 ms for a 12 MP photo).

    Recall counts more than precision here, a missed face is worse than a box too many.
    Therefore: low score threshold, and big images are also searched in overlapping tiles,
    so small faces in the background are found too.

    TODO: Check that the detector is safe to call from several threads at once.
    TODO: Measure the recall on realistic photos (faces far away, turned away, partly covered).
    """

    def __init__(
        self,
        model_path: Path = YUNET_MODEL_PATH,
        score_threshold: float = 0.3,
        tile_size: int = 1280,
        tile_overlap: float = 0.25,
    ) -> None:
        self.score_threshold = score_threshold
        self.tile_size = tile_size
        self.tile_overlap = tile_overlap
        self._detector = cv2.FaceDetectorYN.create(str(model_path), "", (320, 320), score_threshold)

    def _detect_in(self, bgr: np.ndarray, offset_x: int = 0, offset_y: int = 0) -> list[Box]:
        height, width = bgr.shape[:2]
        self._detector.setInputSize((width, height))
        _, faces = self._detector.detect(bgr)
        boxes = []
        for face in faces if faces is not None else []:
            x, y, w, h, score = face[0], face[1], face[2], face[3], face[-1]
            boxes.append(
                Box(
                    offset_x + int(x), offset_y + int(y),
                    offset_x + int(x + w), offset_y + int(y + h),
                    "face", float(score),
                )
            )
        return boxes

    def detect(self, image: Image.Image) -> list[Box]:
        bgr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        height, width = bgr.shape[:2]
        boxes = self._detect_in(bgr)  # the whole image first
        if max(width, height) > self.tile_size:
            step = max(1, int(self.tile_size * (1 - self.tile_overlap)))
            for top in range(0, max(1, height - self.tile_size) + step, step):
                for left in range(0, max(1, width - self.tile_size) + step, step):
                    tile = bgr[top : top + self.tile_size, left : left + self.tile_size]
                    boxes.extend(self._detect_in(tile, left, top))
        return merge_overlapping(boxes)
