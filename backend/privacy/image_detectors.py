from dataclasses import dataclass
import os
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


def _area(box: Box) -> int:
    return max(0, box.right - box.left) * max(0, box.bottom - box.top)


def _inside_share(small: Box, big: Box) -> float:
    """How much of the small box lies inside the big one (0 to 1)."""
    inter_w = max(0, min(small.right, big.right) - max(small.left, big.left))
    inter_h = max(0, min(small.bottom, big.bottom) - max(small.top, big.top))
    return inter_w * inter_h / _area(small) if _area(small) else 0.0


def merge_overlapping(
    boxes: list[Box], min_overlap: float = 0.3, inside_share: float = 0.8, sure_score: float = 0.5
) -> list[Box]:
    """Keep one box per spot.

    1. Of boxes that overlap strongly the most confident one stays (the full image pass, the
       scaled down copies and the tiles find the same face several times).
    2. A small box that lies inside a bigger, confident box is dropped: it is a part of the same face
       (a huge face is found as several parts at the tile scale) and it is covered anyway.
    Without this the redaction log would count one face many times.
    """
    kept: list[Box] = []
    for box in sorted(boxes, key=lambda b: -(b.confidence or 0.0)):
        if all(_overlap_ratio(box, other) < min_overlap for other in kept):
            kept.append(box)
    big_and_sure = [b for b in kept if (b.confidence or 0.0) >= sure_score]
    return [
        box
        for box in kept
        if not any(_area(big) > _area(box) and _inside_share(box, big) >= inside_share for big in big_and_sure)
    ]


DEFAULT_FACE_SCORE_THRESHOLD = 0.7  # decided 2026-11-11 after looking at test photos: the faces a person can recognise score 0.85 or more


def face_score_threshold_from_env() -> float:
    """The score from which a box counts as a face: `FACE_SCORE_THRESHOLD`, default 0.7.

    Lower finds more weak faces and more false boxes (a patch on the road, a leg), higher the other way round. A value outside
    0.1 to 0.95 stops the start of the server, so a typo cannot switch the face cover off by accident.
    """
    raw = os.getenv("FACE_SCORE_THRESHOLD", "").strip()
    value = float(raw) if raw else DEFAULT_FACE_SCORE_THRESHOLD
    if not 0.1 <= value <= 0.95:
        raise ValueError("FACE_SCORE_THRESHOLD must be between 0.1 and 0.95")
    return value


YUNET_MODEL_PATH = Path(__file__).resolve().parent.parent / "assets" / "face_detection_yunet_2023mar.onnx"


class YuNetFaceDetector:
    """Finds faces with the small YuNet model (227 KB, CPU, about 80 ms for a 12 MP photo).

    Recall counts more than precision here, a missed face is worse than a box too many.
    Therefore: low score threshold, big images are also searched in overlapping tiles (small faces in the
    background) and in scaled down copies (huge close-up faces).

    TODO: Check that the detector is safe to call from several threads at once.
    TODO: Measure the recall on realistic photos (faces far away, turned away, partly covered).
    """

    def __init__(
        self,
        model_path: Path = YUNET_MODEL_PATH,
        score_threshold: float = 0.3,
        tile_size: int = 1280,
        tile_overlap: float = 0.25,
        pyramid_sizes: tuple[int, ...] = (640, 1280),
    ) -> None:
        self.score_threshold = score_threshold
        self.tile_size = tile_size
        self.tile_overlap = tile_overlap
        self.pyramid_sizes = pyramid_sizes
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
        long_side = max(width, height)
        boxes: list[Box] = []

        # Image pyramid: YuNet only knows faces up to about 300 pixels. A close-up face of 1600 pixels
        # is found as several small parts at full size, so the image also runs scaled down.
        for target in self.pyramid_sizes:
            if long_side > target:
                scale = target / long_side
                small = cv2.resize(bgr, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
                for box in self._detect_in(small):
                    boxes.append(
                        Box(
                            round(box.left / scale), round(box.top / scale),
                            round(box.right / scale), round(box.bottom / scale),
                            box.kind, box.confidence,
                        )
                    )

        boxes.extend(self._detect_in(bgr))  # full size: small faces
        if long_side > self.tile_size:
            step = max(1, int(self.tile_size * (1 - self.tile_overlap)))
            for top in range(0, max(1, height - self.tile_size) + step, step):
                for left in range(0, max(1, width - self.tile_size) + step, step):
                    tile = bgr[top : top + self.tile_size, left : left + self.tile_size]
                    boxes.extend(self._detect_in(tile, left, top))
        return merge_overlapping(boxes)
