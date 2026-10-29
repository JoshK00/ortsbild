import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.main import create_app
from api.reports import MAX_PHOTO_BYTES, Services
from privacy.detectors import PatternDetector
from privacy.graph import build_privacy_graph
from privacy.image_detectors import Box
from privacy.photo_store import InMemoryPhotoStore
from privacy.pseudonyms import InMemoryPseudonymStore
from privacy.report_status import InMemoryReportStatusStore
from tests.image_helpers import make_heic, make_jpeg, make_png

KEY = {"X-API-Key": "test-key"}
FORM = {"lat": "48.1371", "lon": "11.5754", "device_id": "device-abc-123"}


class OneFace:
    """Finds one fixed face, so the tests do not need the real model."""

    def detect(self, image):
        return [Box(10, 5, 20, 15, "face", 0.9)]


class NoFace:
    def detect(self, image):
        return []


class BrokenDetector:
    def detect(self, text):
        raise RuntimeError("detector down: secret text")


def make_client(face_detector=None, text_detector=None, api_key="test-key"):
    photo_store, status_store = InMemoryPhotoStore(), InMemoryReportStatusStore()
    graph = build_privacy_graph(
        [text_detector or PatternDetector()], photo_store, InMemoryPseudonymStore("s"),
        face_detector=face_detector or NoFace(),
    )
    app = create_app(checks={}, services=Services(graph, photo_store, status_store), api_key=api_key, configure_logging=False)
    return TestClient(app), photo_store, status_store


def post(client, data=None, files=None, headers=KEY):
    return client.post("/reports", data={**FORM, **(data or {})}, files=files, headers=headers)


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------


def test_request_without_key_is_rejected():
    """No key, no access: the endpoint is public on the internet."""
    with make_client()[0] as client:
        assert post(client, {"text": "Pothole"}, headers={}).status_code == 401


def test_request_with_wrong_key_is_rejected():
    with make_client()[0] as client:
        assert post(client, {"text": "Pothole"}, headers={"X-API-Key": "wrong"}).status_code == 401


def test_without_a_configured_key_everything_is_rejected():
    """Fail closed: a server without an API key does not become open."""
    with make_client(api_key="")[0] as client:
        assert post(client, {"text": "Pothole"}).status_code == 503


def test_health_needs_no_key():
    """Monitoring must work without the key."""
    with make_client()[0] as client:
        assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# POST /reports
# ---------------------------------------------------------------------------


def test_text_report_is_sanitized_and_returned():
    """A text with a phone number comes back with the number replaced, and a pseudonym."""
    client, _, status_store = make_client()
    with client:
        response = post(client, {"text": "Pothole, call 0151 2345678"})
    body = response.json()
    assert response.status_code == 200 and body["status"] == "sanitized"
    assert body["report"]["text"] == "Pothole, call <PHONE>"
    assert body["report"]["pseudonym"].startswith("rep-")
    assert status_store.rows[body["id"]].status == "sanitized"


def test_the_device_id_never_comes_back():
    """The plain identifier of the reporter appears nowhere in the answer."""
    with make_client()[0] as client:
        response = post(client, {"text": "Pothole"})
    assert "device-abc-123" not in response.text


def test_photo_report_returns_a_clean_photo_and_deletes_the_raw_one():
    """Faces are covered, the metadata is gone, and the raw photo is deleted."""
    client, photo_store, _ = make_client(face_detector=OneFace())
    with client:
        response = post(client, files={"photo": ("p.jpg", make_jpeg(with_exif=True, size=(40, 20)), "image/jpeg")})
        body = response.json()
        photo = client.get(body["photo_urls"][0], headers=KEY)
    assert response.status_code == 200 and body["status"] == "sanitized"
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(photo.content)) as image:
        assert not dict(image.getexif())  # no EXIF
        assert sum(image.convert("RGB").getpixel((15, 10))) < 30  # face covered
    assert not [ref for ref in photo_store.files if ref.startswith("raw/")]


def test_png_and_heic_photos_are_accepted():
    """The type is detected from the content, so an iPhone photo (HEIC) works too."""
    with make_client()[0] as client:
        assert post(client, files={"photo": ("p.png", make_png(), "image/png")}).status_code == 200
        heic = post(client, files={"photo": ("p.heic", make_heic(), "application/octet-stream")})
    assert heic.status_code == 200
    assert heic.json()["report"]["photos"][0]["mime_type"] == "image/jpeg"  # converted


def test_a_fake_image_is_rejected_even_with_an_image_content_type():
    """The claim of the client counts for nothing, the file itself is checked."""
    with make_client()[0] as client:
        response = post(client, files={"photo": ("p.jpg", b"this is not an image", "image/jpeg")})
    assert response.status_code == 422


def test_unsupported_image_format_is_rejected():
    """Only JPEG, PNG and HEIC."""
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="GIF")
    with make_client()[0] as client:
        assert post(client, files={"photo": ("p.gif", buffer.getvalue(), "image/gif")}).status_code == 415


def test_too_big_photo_is_rejected():
    with make_client()[0] as client:
        big = b"\xff\xd8" + b"0" * MAX_PHOTO_BYTES
        assert post(client, files={"photo": ("p.jpg", big, "image/jpeg")}).status_code == 413


def test_a_report_without_location_is_rejected():
    """The location is mandatory (decision in the data contract)."""
    with make_client()[0] as client:
        response = client.post("/reports", data={"device_id": "d", "text": "x"}, headers=KEY)
    assert response.status_code == 422


def test_an_invalid_coordinate_is_rejected():
    with make_client()[0] as client:
        assert post(client, {"text": "x", "lat": "200"}).status_code == 422


def test_a_report_with_neither_photo_nor_text_is_rejected():
    with make_client()[0] as client:
        assert post(client, {"text": "   "}).status_code == 422


def test_blocked_report_gets_no_details_and_keeps_the_raw_photo():
    """If the privacy layer stops the report the client learns nothing, the operator finds it in the table."""
    client, photo_store, status_store = make_client(text_detector=BrokenDetector())
    with client:
        response = post(client, {"text": "secret text"}, files={"photo": ("p.jpg", make_jpeg(), "image/jpeg")})
    body = response.json()
    assert response.status_code == 200 and body["status"] == "blocked" and body["report"] is None
    assert "secret" not in response.text
    assert status_store.list_blocked()[0].report_id == body["id"]
    assert [ref for ref in photo_store.files if ref.startswith("raw/")]  # kept for the operator


# ---------------------------------------------------------------------------
# GET /reports/{id}/photos/{photo}
# ---------------------------------------------------------------------------


def test_photo_of_an_unknown_report_is_404():
    with make_client()[0] as client:
        assert client.get(f"/reports/{'a' * 32}/photos/p1", headers=KEY).status_code == 404


def test_photo_ids_must_have_the_expected_form():
    """Nothing that looks like a path gets to the storage."""
    with make_client()[0] as client:
        assert client.get("/reports/..%2F..%2Fraw/photos/p1", headers=KEY).status_code in (404, 422)
        assert client.get(f"/reports/{'a' * 32}/photos/..", headers=KEY).status_code in (404, 422)


def test_photo_needs_the_key_too():
    with make_client()[0] as client:
        assert client.get(f"/reports/{'a' * 32}/photos/p1").status_code == 401


def test_the_raw_photo_cannot_be_fetched():
    """Only the clean copy is reachable, never the raw one."""
    client, photo_store, _ = make_client()
    photo_store.save(f"raw/{'b' * 32}/p1.jpg", make_jpeg(), "image/jpeg")
    with client:
        assert client.get(f"/reports/{'b' * 32}/photos/p1", headers=KEY).status_code == 404
