import io
from datetime import datetime, timezone

import pytest
from PIL import Image, ImageDraw, ImageFont

from models.incoming_report import IncomingReport
from privacy.detectors import PatternDetector
from privacy.graph import build_privacy_graph
from privacy.image_detectors import Box, YuNetFaceDetector
from privacy.image_redact import blackout
from privacy.image_text import OcrLine, RapidOcrEngine, find_personal_text_boxes
from privacy.photo_sanitize import ImageOptions, entries_from_boxes, sanitize_image
from privacy.photo_store import InMemoryPhotoStore
from privacy.pseudonyms import InMemoryPseudonymStore
from tests.image_helpers import make_jpeg


class FakeFaceDetector:
    """Finds one fixed face, so the tests do not depend on the real model."""

    def __init__(self, boxes=None):
        self.boxes = boxes if boxes is not None else [Box(10, 5, 20, 15, "face", 0.9)]

    def detect(self, image):
        return self.boxes


class BrokenFaceDetector:
    def detect(self, image):
        raise RuntimeError("detector down")


class FakeOcr:
    """Reads fixed lines and counts the calls."""

    def __init__(self, lines):
        self.lines = lines
        self.calls = 0

    def read(self, image):
        self.calls += 1
        return self.lines


def pixel(data: bytes, xy):
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGB").getpixel(xy)


# ---------------------------------------------------------------------------
# blackout
# ---------------------------------------------------------------------------


def test_blackout_covers_the_box_and_leaves_the_rest():
    """Inside the box everything is black, outside the picture is untouched."""
    image = Image.new("RGB", (40, 20), (200, 30, 30))
    result = blackout(image, [Box(10, 5, 20, 15, "face")], padding=0)
    assert result.getpixel((15, 10)) == (0, 0, 0)
    assert result.getpixel((2, 2)) == (200, 30, 30)
    assert image.getpixel((15, 10)) == (200, 30, 30)  # the original is not changed


def test_blackout_padding_makes_the_bar_bigger():
    """With padding the bar reaches over the box, the detector may cut the edges."""
    image = Image.new("RGB", (100, 100), (255, 255, 255))
    result = blackout(image, [Box(40, 40, 60, 60, "face")], padding=0.5)
    assert result.getpixel((35, 50)) == (0, 0, 0)  # 10 px left of the box
    assert result.getpixel((20, 50)) == (255, 255, 255)


def test_blackout_clips_to_the_image_edge():
    """A box at the edge does not break and does not draw outside."""
    image = Image.new("RGB", (30, 30), (255, 255, 255))
    result = blackout(image, [Box(-5, -5, 10, 10, "face"), Box(25, 25, 60, 60, "face")])
    assert result.size == (30, 30)


# ---------------------------------------------------------------------------
# YuNet (the real model)
# ---------------------------------------------------------------------------


def test_yunet_finds_no_face_in_a_plain_image():
    """The real model loads and finds nothing where there is nothing."""
    assert YuNetFaceDetector().detect(Image.new("RGB", (640, 480), (120, 120, 120))) == []


def test_yunet_handles_a_big_photo_with_tiles():
    """A full size iPhone photo runs through the tiling without error."""
    assert YuNetFaceDetector().detect(Image.new("RGB", (4032, 3024), (90, 90, 90))) == []


# ---------------------------------------------------------------------------
# sanitize_image / log
# ---------------------------------------------------------------------------


def test_sanitize_image_blacks_out_the_face_box():
    """A found face is covered in the returned image."""
    data = make_jpeg(size=(40, 20))
    new, boxes = sanitize_image(data, "image/jpeg", FakeFaceDetector(), ImageOptions(), None, [])
    assert len(boxes) == 1
    assert sum(pixel(new, (15, 10))) < 30  # almost black (JPEG is not exact)


def test_sanitize_image_without_a_hit_returns_the_original_bytes():
    """No hit, no re-encoding: the quality stays as it was."""
    data = make_jpeg()
    new, boxes = sanitize_image(data, "image/jpeg", FakeFaceDetector([]), ImageOptions(), None, [])
    assert new == data and boxes == []


def test_sanitize_image_text_in_image_needs_an_ocr_engine():
    """Switching on text in images without an engine is a setup error and must not pass silently."""
    with pytest.raises(ValueError):
        sanitize_image(make_jpeg(), "image/jpeg", FakeFaceDetector([]), ImageOptions(text_in_image=True), None, [])


def test_entries_count_per_kind_and_keep_the_lowest_confidence():
    """The log says how many faces and how sure, nothing about the content."""
    boxes = [Box(0, 0, 5, 5, "face", 0.9), Box(10, 0, 15, 5, "face", 0.6), Box(0, 10, 5, 15, "phone")]
    entries = {e.kind: e for e in entries_from_boxes(boxes)}
    assert entries["face"].count == 2 and entries["face"].confidence == 0.6
    assert entries["phone"].count == 1 and entries["phone"].confidence is None


# ---------------------------------------------------------------------------
# Text in images
# ---------------------------------------------------------------------------


def test_only_personal_text_lines_are_covered():
    """The phone number is covered, the graffiti text and the street stay."""
    lines = [
        OcrLine("DOWN WITH THE BANKS", 0, 0, 200, 20, 0.99),
        OcrLine("Call 0151 2345678", 0, 30, 200, 50, 0.99),
        OcrLine("Hauptstr. 5", 0, 60, 200, 80, 0.99),
    ]
    boxes = find_personal_text_boxes(lines, [PatternDetector()])
    assert [(b.kind, b.top) for b in boxes] == [("phone", 30)]


def test_license_plate_text_is_covered():
    """A plate that the OCR can read is found by the plate pattern."""
    boxes = find_personal_text_boxes([OcrLine("M-AB 1234", 5, 5, 100, 30, 0.9)], [PatternDetector()])
    assert [b.kind for b in boxes] == ["plate"]


def test_real_ocr_reads_a_generated_image():
    """The real OCR engine reads a phone number. It splits the line in two pieces, both are covered."""
    image = Image.new("RGB", (900, 200), "white")
    ImageDraw.Draw(image).text((30, 40), "Call 0151 2345678", fill="black", font=ImageFont.load_default(size=60))
    lines = RapidOcrEngine().read(image)
    boxes = find_personal_text_boxes(lines, [PatternDetector()])
    assert boxes and {b.kind for b in boxes} == {"phone"}


# ---------------------------------------------------------------------------
# sanitize_photos inside the graph
# ---------------------------------------------------------------------------


def make_report(text=None):
    return IncomingReport(
        id="7c9e",
        received_at=datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc),
        source={"type": "app", "connector": "ortsbild-ios", "raw_ref": "raw/7c9e/"},
        location={"lat": 48.1371, "lon": 11.5754},
        text=text,
        photos=[{"id": "p1", "mime_type": "image/jpeg", "ref": "raw/7c9e/p1.jpg"}],
        user={"identifier": "device-1", "identifier_type": "device_id"},
    )


def run(face_detector, options=None, ocr=None):
    store = InMemoryPhotoStore()
    store.save("raw/7c9e/p1.jpg", make_jpeg(size=(40, 20)), "image/jpeg")
    graph = build_privacy_graph(
        [PatternDetector()], store, InMemoryPseudonymStore("secret"),
        face_detector=face_detector, image_options=options, ocr_engine=ocr,
    )
    return graph.invoke({"report": make_report()}), store


def test_graph_blacks_out_faces_and_logs_them():
    """The clean photo has the face covered, the log counts it, the raw photo is deleted."""
    result, store = run(FakeFaceDetector())
    assert sum(pixel(store.load("clean/7c9e/p1.jpg"), (15, 10))) < 30
    assert [(e.kind, e.count) for e in result["sanitized_report"].redaction_log.entries if e.kind == "face"] == [("face", 1)]
    assert "raw/7c9e/p1.jpg" not in store.files


def test_graph_fails_closed_when_the_face_detector_breaks():
    """If the faces cannot be checked, nothing is passed on and the raw photo stays."""
    result, store = run(BrokenFaceDetector())
    assert result["status"] == "blocked_privacy"
    assert result["block_reason"].startswith("sanitize_photos")
    assert "sanitized_report" not in result
    assert "raw/7c9e/p1.jpg" in store.files


def test_graph_does_not_read_text_in_images_by_default():
    """Text in images is off by default, so the OCR is never called."""
    ocr = FakeOcr([OcrLine("Call 0151 2345678", 0, 0, 40, 20, 0.9)])
    run(FakeFaceDetector([]), ocr=ocr)
    assert ocr.calls == 0


def test_graph_covers_personal_text_in_images_when_switched_on():
    """With text_in_image on, the line with the phone number is covered and logged."""
    ocr = FakeOcr([OcrLine("Call 0151 2345678", 0, 0, 40, 20, 0.9)])
    result, store = run(FakeFaceDetector([]), ImageOptions(text_in_image=True), ocr)
    assert ocr.calls == 1
    assert sum(pixel(store.load("clean/7c9e/p1.jpg"), (20, 10))) < 30
    assert "phone" in {e.kind for e in result["sanitized_report"].redaction_log.entries}


# ---------------------------------------------------------------------------
# merge_overlapping
# ---------------------------------------------------------------------------


def test_the_same_face_found_twice_counts_once():
    """The full image pass and a tile find the same face, only the more confident box stays."""
    from privacy.image_detectors import merge_overlapping

    boxes = [Box(100, 100, 200, 200, "face", 0.6), Box(102, 98, 203, 201, "face", 0.9)]
    assert merge_overlapping(boxes) == [boxes[1]]


def test_two_different_faces_stay_two():
    """Boxes that do not overlap are different faces."""
    from privacy.image_detectors import merge_overlapping

    boxes = [Box(0, 0, 50, 50, "face", 0.9), Box(200, 200, 250, 250, "face", 0.8)]
    assert len(merge_overlapping(boxes)) == 2


def test_blackout_ignores_a_box_completely_outside_the_image():
    """A box beyond the edge covers nothing and must not raise."""
    image = Image.new("RGB", (30, 30), (255, 255, 255))
    assert blackout(image, [Box(100, 100, 120, 120, "face")]).getpixel((5, 5)) == (255, 255, 255)


def test_parts_inside_a_big_confident_face_are_dropped():
    """A huge face is found as several small parts too. They lie inside the big box and are not counted."""
    from privacy.image_detectors import merge_overlapping

    big = Box(0, 0, 1000, 1400, "face", 0.95)
    part = Box(200, 100, 500, 400, "face", 0.6)
    assert merge_overlapping([part, big]) == [big]


def test_a_part_inside_an_unsure_big_box_stays():
    """Only a confident big box swallows smaller ones, an unsure one might be wrong."""
    from privacy.image_detectors import merge_overlapping

    big = Box(0, 0, 1000, 1400, "face", 0.4)
    part = Box(200, 100, 500, 400, "face", 0.6)
    assert len(merge_overlapping([part, big])) == 2


def test_a_small_face_next_to_a_big_one_stays():
    """A box that is not inside the big one is another person."""
    from privacy.image_detectors import merge_overlapping

    big = Box(0, 0, 1000, 1400, "face", 0.95)
    other = Box(1200, 100, 1300, 250, "face", 0.7)
    assert len(merge_overlapping([big, other])) == 2


def test_yunet_finds_a_huge_blank_photo_without_error():
    """A very big image runs through the scaled down copies and the tiles without error."""
    assert YuNetFaceDetector().detect(Image.new("RGB", (3974, 5000), (200, 200, 200))) == []
