import io
from datetime import datetime, timezone

import pytest
from PIL import Image

from models.incoming_report import IncomingReport, Photo
from privacy.detectors import PatternDetector
from privacy.graph import build_privacy_graph
from privacy.photo_store import InMemoryPhotoStore, split_ref
from privacy.photos import strip_exif, strip_photo_metadata
from tests.image_helpers import make_jpeg, make_png


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
    """Unsupported types (e.g. HEIC) raise, so the report fails closed."""
    with pytest.raises(ValueError):
        strip_exif(b"anything", "image/heic")


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
    graph = build_privacy_graph([PatternDetector()], store)
    result = graph.invoke({"report": report})
    assert result["status"] == "running"
    assert result["photos"][0].ref == "clean/7c9e/p1.jpg"
    assert result["text"] == "Call <PHONE>"
    assert {e.kind for e in result["redactions"]} == {"exif", "phone"}


def test_graph_blocks_and_stops_when_a_photo_cannot_be_read():
    """A missing file blocks the report, and the text step is not even reached."""
    report = make_report(
        [{"id": "p1", "mime_type": "image/jpeg", "ref": "raw/7c9e/missing.jpg"}],
        text="Call 0151 2345678",
    )
    graph = build_privacy_graph([PatternDetector()], InMemoryPhotoStore())
    result = graph.invoke({"report": report})
    assert result["status"] == "blocked_privacy"
    assert result["block_reason"].startswith("strip_metadata")
    assert "text" not in result  # sanitize_text never ran
