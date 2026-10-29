import io
from collections import defaultdict
from dataclasses import dataclass

from PIL import Image

from models.incoming_report import Photo
from models.sanitized_report import RedactionEntry, RedactionKind
from privacy.detectors import TextDetector
from privacy.image_detectors import Box, FaceDetector
from privacy.image_redact import blackout
from privacy.image_text import OcrEngine, find_personal_text_boxes
from privacy.photo_store import PhotoStore
from privacy.photos import SUPPORTED_FORMATS


@dataclass(frozen=True)
class ImageOptions:
    """What the photo step covers. Faces are always on, the rest can be switched on.

    TODO: Add a license plate detector if text recognition misses too many plates (needs a test
          with realistic photos). Plates that the OCR can read are covered by text_in_image.
    TODO: Open for the data protection sign-off: blur or keep a plate that is the evidence.
    """

    faces: bool = True
    text_in_image: bool = False  # off by default, OCR costs time


def entries_from_boxes(boxes: list[Box]) -> list[RedactionEntry]:
    """Count the boxes per kind. The log never contains what was covered."""
    grouped: dict[RedactionKind, list[Box]] = defaultdict(list)
    for box in boxes:
        grouped[box.kind].append(box)
    entries = []
    for kind, group in grouped.items():
        scores = [b.confidence for b in group if b.confidence is not None]
        entries.append(
            RedactionEntry(
                step="sanitize_photos",
                kind=kind,
                count=len(group),
                confidence=min(scores) if scores else None,
            )
        )
    return entries


def sanitize_image(
    data: bytes,
    mime_type: str,
    face_detector: FaceDetector,
    options: ImageOptions,
    ocr_engine: OcrEngine | None,
    text_detectors: list[TextDetector],
) -> tuple[bytes, list[Box]]:
    """Find faces (and personal text) in one image and black them out.

    Returns the new image bytes and the boxes. Without a hit the original bytes come back
    unchanged, so the image is not re-encoded for nothing.
    """
    image_format = SUPPORTED_FORMATS[mime_type][0]
    with Image.open(io.BytesIO(data)) as opened:
        image = opened.convert("RGB")
    boxes: list[Box] = []
    if options.faces:
        boxes.extend(face_detector.detect(image))
    if options.text_in_image:
        if ocr_engine is None:
            raise ValueError("text_in_image is on, but there is no OCR engine")
        boxes.extend(find_personal_text_boxes(ocr_engine.read(image), text_detectors))
    if not boxes:
        return data, []
    output = io.BytesIO()
    save_options = {"quality": 95} if image_format == "JPEG" else {}
    blackout(image, boxes).save(output, format=image_format, **save_options)
    return output.getvalue(), boxes


def sanitize_photos(
    photos: list[Photo],
    store: PhotoStore,
    face_detector: FaceDetector,
    options: ImageOptions,
    ocr_engine: OcrEngine | None,
    text_detectors: list[TextDetector],
) -> list[RedactionEntry]:
    """Black out faces (and personal text) in the clean copies, in place. Returns the log entries."""
    all_boxes: list[Box] = []
    for photo in photos:
        data, boxes = sanitize_image(
            store.load(photo.ref), photo.mime_type, face_detector, options, ocr_engine, text_detectors
        )
        if boxes:
            store.save(photo.ref, data, photo.mime_type)
            all_boxes.extend(boxes)
    return entries_from_boxes(all_boxes)
