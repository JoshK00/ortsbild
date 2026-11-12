"""The app channel: POST /v1/reports as the app sends it, handed to the backend in its format."""

import re

import pytest

from tests.conftest import FORM, TOKEN, make_heic, make_image


def post(client, data=None, photo: bytes | None = None, headers=None, filename="photo.jpg", mime="image/jpeg"):
    files = {"photo": (filename, photo, mime)} if photo is not None else None
    return client.post(
        "/v1/reports", data={**FORM, **(data or {})}, files=files, headers=TOKEN if headers is None else headers
    )


# --------------------------------------------------------------------------- what the backend gets


def test_a_report_with_photo_is_handed_over_in_the_format_of_the_backend(client, store, backend):
    place = {"country_code": "DE", "municipality": "Stuttgart", "street": "Königstraße", "house_number": "1"}
    response = post(client, {"text": "  Schlagloch  ", "accuracy_m": "6.5", **place}, photo=make_image())

    assert response.status_code == 200
    ((submission, authorization),) = backend.calls
    report_id = submission["id"]
    assert re.fullmatch(r"[0-9a-f]{32}", report_id)
    assert authorization == TOKEN["Authorization"]  # passed on unchanged, the backend checks the user
    assert submission["client_report_id"] == FORM["client_report_id"]
    assert submission["source"] == {"type": "app", "connector": "gateway-app", "raw_ref": f"raw/{report_id}/"}
    assert submission["location"] == {
        "lat": 48.7758, "lon": 9.1829, "accuracy_m": 6.5, "origin": "device_gps", "place": place,
    }  # fmt: skip
    assert submission["text"] == "Schlagloch"
    assert submission["photos"] == [{"id": "p1", "mime_type": "image/jpeg", "ref": f"raw/{report_id}/p1.jpg"}]
    assert "user" not in submission  # the user is the one of the login, the gateway never sends one
    assert submission["received_at"].endswith("+00:00")
    # the photo lies where the privacy layer of the backend reads it, unchanged
    assert store.files[f"raw/{report_id}/p1.jpg"] == (make_image(), "image/jpeg")


def test_the_answer_of_the_backend_goes_to_the_app_as_it_is(client, backend):
    backend.body = {"id": None, "status": "sanitized", "classification": {"category": "pothole"}}
    response = post(client, {"text": "Schlagloch"})
    assert response.status_code == 200
    assert response.json()["classification"] == {"category": "pothole"}


def test_a_text_only_report_has_no_photo(client, store, backend):
    assert post(client, {"text": "Laterne kaputt"}).status_code == 200
    submission = backend.calls[0][0]
    assert submission["photos"] == [] and store.files == {}


def test_empty_address_parts_are_dropped_and_no_address_is_null(client, backend):
    post(client, {"text": "x", "municipality": "  ", "street": "Marktplatz"})
    post(client, {"text": "y"})
    assert backend.calls[0][0]["location"]["place"] == {"street": "Marktplatz"}
    assert backend.calls[1][0]["location"]["place"] is None


@pytest.mark.parametrize(("photo", "mime", "extension"), [
    (make_image("PNG"), "image/png", "png"),
    (make_heic(), "image/heic", "heic"),
])  # fmt: skip
def test_png_and_heic_keep_their_type(client, store, backend, photo, mime, extension):
    # the type is read from the file, not from what the client claims
    assert post(client, photo=photo, mime="image/jpeg").status_code == 200
    ref = backend.calls[0][0]["photos"][0]["ref"]
    assert ref.endswith(f"/p1.{extension}") and store.files[ref][1] == mime


# --------------------------------------------------------------------------- checks of the channel


def test_without_a_token_nothing_is_stored_or_sent(client, store, backend):
    response = post(client, {"text": "x"}, photo=make_image(), headers={})
    assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
    assert store.files == {} and backend.calls == []


@pytest.mark.parametrize(("data", "photo", "status"), [
    ({}, None, 422),  # neither photo nor text
    ({"text": "   "}, None, 422),
    ({}, b"not an image", 422),
    ({}, make_image("GIF"), 415),
    ({"client_report_id": "short"}, make_image(), 422),
    ({"client_report_id": "has spaces in it"}, make_image(), 422),
    ({"lat": "91"}, make_image(), 422),
    ({"country_code": "DEU"}, make_image(), 422),
    ({"text": "x" * 5001}, None, 422),
])  # fmt: skip
def test_invalid_input_is_refused_before_anything_is_stored(client, store, backend, data, photo, status):
    assert post(client, data, photo=photo).status_code == status
    assert store.files == {} and backend.calls == []


def test_a_photo_that_is_too_big_is_refused(client, store, backend, monkeypatch):
    monkeypatch.setattr("gateway.app_channel.MAX_PHOTO_BYTES", 100)
    assert post(client, photo=make_image(size=(400, 400))).status_code == 413
    assert store.files == {} and backend.calls == []


# --------------------------------------------------------------------------- who owns the raw photo


@pytest.mark.parametrize("status", [401, 403, 409, 413, 422, 429])
def test_when_the_backend_does_not_take_the_report_the_photo_is_deleted(client, store, backend, status):
    backend.status_code, backend.body = status, {"detail": "no"}
    response = post(client, photo=make_image())
    assert response.status_code == status and response.json() == {"detail": "no"}
    assert store.files == {}


def test_a_401_of_the_backend_keeps_its_header_so_the_app_signs_in_again(client, backend):
    backend.status_code, backend.body = 401, {"detail": "not signed in"}
    assert post(client, {"text": "x"}).headers["www-authenticate"] == "Bearer"


def test_a_retry_gets_the_first_report_and_the_new_photo_is_deleted(client, store, backend):
    backend.body = {"id": "f" * 32, "status": "sanitized"}  # the backend knows this client_report_id already
    response = post(client, photo=make_image())
    assert response.status_code == 200 and response.json()["id"] == "f" * 32
    assert store.files == {}


def test_when_the_backend_fails_the_photo_stays_for_the_operator(client, store, backend):
    backend.status_code, backend.body = 500, {"detail": "Internal Server Error"}
    assert post(client, photo=make_image()).status_code == 500
    assert len(store.files) == 1


def test_an_unreachable_backend_gives_503_and_the_photo_is_deleted(client, store, backend, unreachable):
    backend.error = unreachable
    assert post(client, photo=make_image()).status_code == 503
    assert store.files == {}


def test_a_backend_that_answers_too_late_gives_504_and_the_photo_stays(client, store, backend, timeout):
    backend.error = timeout  # it may still be working on the report, its privacy layer deletes the photo
    assert post(client, photo=make_image()).status_code == 504
    assert len(store.files) == 1


def test_the_gateway_offers_only_the_new_report(client):
    """Every other request of the app goes straight to the backend (deploy/Caddyfile)."""
    assert client.get("/v1/reports/" + "a" * 32, headers=TOKEN).status_code == 404
    assert client.get("/health").json() == {"status": "ok"}
