from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image

from models.sanitized_report import RedactionKind
from privacy.detectors import TextDetector
from privacy.image_detectors import Box
from privacy.text import DEFAULT_REDACT_KINDS, merge_entities


@dataclass(frozen=True)
class OcrLine:
    """One line of text found in an image, with its position."""

    text: str
    left: int
    top: int
    right: int
    bottom: int
    confidence: float


class OcrEngine(Protocol):
    """Anything that can read text in an image. Engines are interchangeable."""

    def read(self, image: Image.Image) -> list[OcrLine]: ...


class RapidOcrEngine:
    """Reads text with RapidOCR (PP-OCRv6 small on ONNX Runtime, CPU, models ship with the package).

    TODO: Use word boxes instead of line boxes, so only the personal word is covered.
    TODO: Check that the engine is safe to call from several threads at once.
    """

    def __init__(self) -> None:
        self._engine = None

    def read(self, image: Image.Image) -> list[OcrLine]:
        if self._engine is None:
            from rapidocr import RapidOCR  # imported here, it logs and loads models

            self._engine = RapidOCR()
        result = self._engine(np.array(image.convert("RGB")))
        if result.txts is None:
            return []
        lines = []
        for text, polygon, score in zip(result.txts, result.boxes, result.scores):
            xs, ys = polygon[:, 0], polygon[:, 1]
            lines.append(
                OcrLine(text, int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()), float(score))
            )
        return lines


def find_personal_text_boxes(
    lines: list[OcrLine],
    detectors: list[TextDetector],
    redact_kinds: frozenset[RedactionKind] = DEFAULT_REDACT_KINDS,
) -> list[Box]:
    """Run the text detectors over the text of the image and return the boxes to cover.

    Only text that is personal data is covered. Graffiti, street signs and other text stay,
    they are often the very thing that is reported. The whole line is covered (coarse but safe).
    """
    text = "\n".join(line.text for line in lines)
    starts, position = [], 0
    for line in lines:
        starts.append((position, position + len(line.text)))
        position += len(line.text) + 1  # +1 for the line break

    entities = []
    for detector in detectors:
        entities.extend(detector.detect(text))

    boxes = []
    for entity in merge_entities(entities):
        if entity.kind not in redact_kinds:
            continue
        for line, (start, end) in zip(lines, starts):
            if entity.start < end and entity.end > start:  # the hit touches this line
                boxes.append(Box(line.left, line.top, line.right, line.bottom, entity.kind, entity.confidence))
    return boxes
