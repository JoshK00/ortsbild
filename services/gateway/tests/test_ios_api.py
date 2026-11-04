import io
import uuid

from PIL import Image

from tests.conftest import API_KEY, make_jpeg

HEADERS = {"X-API-Key": API_KEY}


def form(**overrides):
    data = {
        "client_report_id": str(uuid.uuid4()),
        "device_id": "device-1",
        "created_at": "2026-11-01T19:30:00Z",
        "lat": "47.0667",
        "lon": "15.4333",
        "accuracy_m": "8",
        "text": "Schlagloch vor dem Eingang",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_with_photo_stores_anonymized_jpeg_without_metadata(client, settings, storage):
    photo = make_jpeg(gps=(47.5, 15.5))
    res = client.post("/v1/reports", data=form(), files={"photo": ("p.jpg", photo, "image/jpeg")}, headers=HEADERS)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "received"

    report = client.app.state.repo.get(uuid.UUID(body["id"]))
    assert report.tenant == "test-town"
    assert report.location.source == "gps"  # device GPS wins over EXIF
    assert report.location.lat == 47.0667
    assert report.reply_channel == "app_status" and report.reply_address == "device-1"

    (media,) = report.media
    assert media.bucket == settings.storage_bucket_anonymized and media.anonymized is True
    stored = Image.open(io.BytesIO(storage.get(media.bucket, media.key)))
    assert max(stored.size) == settings.max_photo_edge_px
    assert len(stored.getexif()) == 0  # camera model and GPS are gone


def test_retry_with_same_client_report_id_returns_existing_report(client):
    data = form()
    first = client.post("/v1/reports", data=data, headers=HEADERS)
    second = client.post("/v1/reports", data=data, headers=HEADERS)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_text_only_report_is_accepted(client):
    res = client.post("/v1/reports", data=form(), headers=HEADERS)
    assert res.status_code == 201


def test_photo_only_report_is_accepted(client):
    res = client.post(
        "/v1/reports", data=form(text=None), files={"photo": ("p.jpg", make_jpeg(), "image/jpeg")}, headers=HEADERS
    )
    assert res.status_code == 201


def test_report_without_photo_and_text_is_rejected(client):
    res = client.post("/v1/reports", data=form(text="   "), headers=HEADERS)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "empty_report"


def test_missing_location_is_rejected_with_field_names(client):
    res = client.post("/v1/reports", data=form(lat=None), headers=HEADERS)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["code"] == "validation_error" and "lat" in detail["fields"]


def test_imprecise_location_is_rejected(client):
    res = client.post("/v1/reports", data=form(accuracy_m="5000"), headers=HEADERS)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "location_too_imprecise"


def test_invalid_photo_is_rejected(client):
    res = client.post(
        "/v1/reports", data=form(), files={"photo": ("p.jpg", b"not an image", "image/jpeg")}, headers=HEADERS
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_photo"


def test_missing_api_key_is_rejected(client):
    res = client.post("/v1/reports", data=form())
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "invalid_api_key"


def test_get_status(client):
    created = client.post("/v1/reports", data=form(), headers=HEADERS).json()
    res = client.get(f"/v1/reports/{created['id']}", headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["status"] == "received"


def test_get_unknown_report_returns_404(client):
    res = client.get(f"/v1/reports/{uuid.uuid4()}", headers=HEADERS)
    assert res.status_code == 404
