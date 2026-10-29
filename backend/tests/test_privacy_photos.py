import io
from datetime import datetime, timezone

import pytest
from PIL import Image

from models.incoming_report import IncomingReport, Photo
from privacy.detectors import PatternDetector
from privacy.graph import build_privacy_graph
from privacy.photo_store import InMemoryPhotoStore, split_ref
from privacy.pseudonyms import InMemoryPseudonymStore
from privacy.photos import strip_exif, strip_photo_metadata
from tests.image_helpers import make_heic, make_jpeg, make_png


# ---------------------------------------------------------------------------
# PhotoStore
# ---------------------------------------------------------------------------


def test_split_ref_separates_bucket_and_path():
    """The bucket is the first part of the ref."""
    assert split_ref("raw/7c9e/p1.jpg") == ("raw", "7c9e/p1.jpg")


def test_split_ref_rejects_a_ref_without_bucket():
    """A bare file name has no bucket and cannot be stored."""
    with pytest.raises(ValueError):
        split_ref("p1.jpg")


def test_in_memory_store_saves_loads_and_deletes():
    """The test store behaves like the real one."""
    store = InMemoryPhotoStore()
    store.save("raw/a/p1.jpg", b"data", "image/jpeg")
    assert store.load("raw/a/p1.jpg") == b"data"
    store.delete("raw/a/p1.jpg")
    with pytest.raises(KeyError):
        store.load("raw/a/p1.jpg")


# ---------------------------------------------------------------------------
# strip_exif / strip_photo_metadata
# ---------------------------------------------------------------------------


def exif_of(data: bytes) -> dict:
    with Image.open(io.BytesIO(data)) as image:
        return dict(image.getexif())


def test_strip_exif_removes_the_metadata():
    """GPS and camera model are gone after stripping, the picture itself remains."""
    original = make_jpeg(with_exif=True)
    assert exif_of(original)  # the test image really has EXIF
    stripped, had_exif = strip_exif(original, "image/jpeg")
    assert had_exif is True
    assert exif_of(stripped) == {}
    with Image.open(io.BytesIO(stripped)) as image:
        assert image.size == (40, 20)


def test_strip_exif_reports_an_image_without_exif():
    """An image that had no metadata is reported as such, so it is not logged."""
    _, had_exif = strip_exif(make_jpeg(with_exif=False), "image/jpeg")
    assert had_exif is False


def test_strip_exif_rejects_unsupported_types():
    """Unsupported types (e.g. WebP) raise, so the report fails closed."""
    with pytest.raises(ValueError):
        strip_exif(b"anything", "image/webp")


def test_heic_is_stripped_and_converted_to_jpeg():
    """iPhone photos (HEIC) lose their EXIF and come out as JPEG."""
    original = make_heic(with_exif=True)
    assert exif_of(original)  # the test image really has EXIF
    stripped, had_exif = strip_exif(original, "image/heic")
    assert had_exif is True
    assert exif_of(stripped) == {}
    with Image.open(io.BytesIO(stripped)) as image:
        assert image.format == "JPEG"
        assert image.size == (40, 20)


def test_heic_photo_gets_a_jpeg_reference_and_mime_type():
    """The clean copy of a HEIC photo is a .jpg with the type image/jpeg."""
    store = InMemoryPhotoStore()
    store.save("raw/7c9e/p1.heic", make_heic(with_exif=True), "image/heic")
    photos = [Photo(id="p1", mime_type="image/heic", ref="raw/7c9e/p1.heic")]
    clean, log = strip_photo_metadata(photos, "7c9e", store)
    assert (clean[0].ref, clean[0].mime_type) == ("clean/7c9e/p1.jpg", "image/jpeg")
    assert [(e.kind, e.count) for e in log] == [("exif", 1)]


def test_strip_photo_metadata_copies_to_the_clean_bucket_and_logs():
    """The clean copy lands in the clean bucket, the log counts photos that had EXIF."""
    store = InMemoryPhotoStore()
    store.save("raw/7c9e/p1.jpg", make_jpeg(with_exif=True), "image/jpeg")
    store.save("raw/7c9e/p2.png", make_png(), "image/png")
    photos = [
        Photo(id="p1", mime_type="image/jpeg", ref="raw/7c9e/p1.jpg"),
        Photo(id="p2", mime_type="image/png", ref="raw/7c9e/p2.png"),
    ]
    clean, log = strip_photo_metadata(photos, "7c9e", store)
    assert [p.ref for p in clean] == ["clean/7c9e/p1.jpg", "clean/7c9e/p2.png"]
    assert exif_of(store.load("clean/7c9e/p1.jpg")) == {}
    assert [(e.kind, e.count) for e in log] == [("exif", 1)]


# ---------------------------------------------------------------------------
# strip_metadata inside the graph, including fail closed
# ---------------------------------------------------------------------------


def make_report(photos, text="Pothole near the school"):
    return IncomingReport(
        id="7c9e",
        received_at=datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc),
        source={"type": "app", "connector": "ortsbild-ios", "raw_ref": "raw/7c9e/"},
        location={"lat": 48.1371, "lon": 11.5754},
        text=text,
        photos=photos,
        user={"identifier": "device-1", "identifier_type": "device_id"},
    )


def test_graph_strips_metadata_then_sanitizes_text():
    """Both steps run in order and the log collects the entries of both."""
    store = InMemoryPhotoStore()
    store.save("raw/7c9e/p1.jpg", make_jpeg(with_exif=True), "image/jpeg")
    report = make_report(
        [{"id": "p1", "mime_type": "image/jpeg", "ref": "raw/7c9e/p1.jpg"}],
        text="Call 0151 2345678",
    )
    graph = build_privacy_graph([PatternDetector()], store, InMemoryPseudonymStore("test-secret"))
    result = graph.invoke({"report": report})
    assert result["status"] == "running"
    assert result["photos"][0].ref == "clean/7c9e/p1.jpg"
    assert result["text"] == "Call <PHONE>"
    assert {e.kind for e in result["redactions"]} == {"exif", "phone", "user_identifier"}


def test_graph_blocks_and_stops_when_a_photo_cannot_be_read():
    """A missing file blocks the report, and the text step is not even reached."""
    report = make_report(
        [{"id": "p1", "mime_type": "image/jpeg", "ref": "raw/7c9e/missing.jpg"}],
        text="Call 0151 2345678",
    )
    graph = build_privacy_graph([PatternDetector()], InMemoryPhotoStore(), InMemoryPseudonymStore("test-secret"))
    result = graph.invoke({"report": report})
    assert result["status"] == "blocked_privacy"
    assert result["block_reason"].startswith("strip_metadata")
    assert "text" not in result  # sanitize_text never ran


# ---------------------------------------------------------------------------
# Steps only run when their input exists
# ---------------------------------------------------------------------------


class CountingStore(InMemoryPhotoStore):
    """Counts how often a file is loaded, to see whether the photo step ran."""

    def __init__(self):
        super().__init__()
        self.loads = 0

    def load(self, ref):
        self.loads += 1
        return super().load(ref)


class CountingDetector:
    """Counts the calls, to see whether the text step ran."""

    def __init__(self):
        self.calls = 0

    def detect(self, text):
        self.calls += 1
        return []


def test_report_without_photos_skips_the_photo_step():
    """No photo, no photo step: the store is never touched."""
    store, detector = CountingStore(), CountingDetector()
    result = build_privacy_graph([detector], store, InMemoryPseudonymStore("test-secret")).invoke({"report": make_report([], text="Pothole")})
    assert store.loads == 0
    assert "photos" not in result
    assert detector.calls == 1  # the text step still ran


def test_report_without_text_skips_the_text_step():
    """No text, no text step: no detector is called."""
    store, detector = CountingStore(), CountingDetector()
    store.save("raw/7c9e/p1.jpg", make_jpeg(), "image/jpeg")
    report = make_report([{"id": "p1", "mime_type": "image/jpeg", "ref": "raw/7c9e/p1.jpg"}], text=None)
    result = build_privacy_graph([detector], store, InMemoryPseudonymStore("test-secret")).invoke({"report": report})
    assert detector.calls == 0
    assert "text" not in result
    assert store.loads == 2  # both photo steps still ran: strip_metadata and sanitize_photos


def test_report_with_neither_photos_nor_text_runs_no_sanitizing_step():
    """Nothing to sanitize: both steps are skipped and the report is not blocked."""
    store, detector = CountingStore(), CountingDetector()
    result = build_privacy_graph([detector], store, InMemoryPseudonymStore("test-secret")).invoke({"report": make_report([], text=None)})
    assert (store.loads, detector.calls) == (0, 0)
    assert result["status"] == "running"
