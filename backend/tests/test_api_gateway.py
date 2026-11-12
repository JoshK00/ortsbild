"""The entrance of the connector gateway: POST /internal/v1/reports (api/gateway.py)."""

import json
import uuid
from datetime import datetime, timezone

import pytest

from tests.image_helpers import make_jpeg
from tests.test_api_reports import Env

KEY = "gateway-key-for-tests"


@pytest.fixture(autouse=True)
def gateway_key(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY", KEY)


def submission(report_id=None, client_report_id="report-0001", photo=True, text="Schlagloch", **changes):
    """What the gateway sends, with its photo already in the raw folder of the report (see `store_photo`)."""
    report_id = report_id or uuid.uuid4().hex
    body = {
        "client_report_id": client_report_id,
        "id": report_id,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "source": {"type": "app", "connector": "gateway-app", "raw_ref": f"raw/{report_id}/"},
        "location": {
            "lat": 48.1371, "lon": 11.5754, "accuracy_m": 8.0, "origin": "device_gps",
            "place": {"country_code": "DE", "municipality": "München", "street": "Marienplatz"},
        },
        "text": text,
        "photos": [{"id": "p1", "mime_type": "image/jpeg", "ref": f"raw/{report_id}/p1.jpg"}] if photo else [],
    }
    body.update(changes)
    return body


def store_photo(env, body):
    """Do what the gateway does before it calls: put the raw photo where the submission points."""
    for photo in body["photos"]:
        env.photo_store.save(photo["ref"], make_jpeg(), photo["mime_type"])


def send(env, body, user="anna", key=KEY, headers=None):
    if headers is None:
        headers = {**env.login(user), "X-Gateway-Key": key, "Content-Type": "application/json"}
    return env.client.post("/internal/v1/reports", content=json.dumps(body), headers=headers)


def test_the_entrance_does_not_exist_without_a_gateway_key(monkeypatch):
    """A backend that runs without a gateway is unchanged: no key, no entrance."""
    monkeypatch.delenv("GATEWAY_KEY")
    with Env() as env:
        assert send(env, submission(), key="anything").status_code == 404


def test_a_caller_without_the_gateway_key_is_refused():
    with Env() as env:
        body = submission()
        store_photo(env, body)
        assert send(env, body, key="wrong").status_code == 403
        headers = {**env.login(), "Content-Type": "application/json"}
        assert send(env, body, headers=headers).status_code == 403


def test_the_user_must_be_signed_in():
    """The gateway passes the token of the user on, the backend checks it. The gateway key alone opens nothing."""
    with Env() as env:
        response = send(env, submission(), headers={"X-Gateway-Key": KEY, "Content-Type": "application/json"})
    assert response.status_code == 401


def test_a_report_of_the_gateway_runs_like_one_from_the_app():
    with Env() as env:
        body = submission()
        store_photo(env, body)
        response = send(env, body)
        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == body["id"]
        assert payload["status"] == "sanitized"
        assert payload["photo_urls"] == [f"/v1/reports/{body['id']}/photos/p1"]
        assert payload["report"]["location"]["place"]["municipality"] == "München"
        # the raw photo is gone after the privacy layer, the clean copy exists
        with pytest.raises(KeyError):
            env.photo_store.load(f"raw/{body['id']}/p1.jpg")
        assert env.photo_store.load(f"clean/{body['id']}/p1.jpg")
        # the report belongs to the signed-in user, the app reaches it on the usual way
        own = env.client.get(f"/v1/reports/{body['id']}", headers=env.login())
        other = env.client.get(f"/v1/reports/{body['id']}", headers=env.login("bob"))
        assert own.status_code == 200 and other.status_code == 404


def test_the_user_is_taken_from_the_login_never_from_the_gateway():
    with Env() as env:
        body = submission(user={"identifier": "someone-else", "identifier_type": "user_key"})
        store_photo(env, body)
        assert send(env, body).status_code == 422


def test_a_retry_answers_with_the_first_report_and_creates_nothing_new():
    with Env() as env:
        first = submission(client_report_id="report-0042")
        store_photo(env, first)
        assert send(env, first).status_code == 200
        retry = submission(client_report_id="report-0042")  # the gateway made a new id and stored the photo again
        store_photo(env, retry)
        response = send(env, retry)
        assert response.status_code == 200 and response.json()["id"] == first["id"]
        assert env.status_store.get(retry["id"]) is None
        # the new raw photo was not touched: it still belongs to the gateway, which deletes it
        assert env.photo_store.load(f"raw/{retry['id']}/p1.jpg")


@pytest.mark.parametrize("ref", ["clean/{other}/p1.jpg", "raw/{other}/p1.jpg", "raw/{own}/../{other}/p1.jpg", "raw/{own}/p1.gif"])
def test_a_ref_outside_the_raw_folder_of_the_report_is_refused(ref):
    """The privacy layer reads and deletes every ref it gets, so a ref to another report's file must never come in."""
    with Env() as env:
        body = submission()
        other = uuid.uuid4().hex
        body["photos"][0]["ref"] = ref.format(own=body["id"], other=other)
        assert send(env, body).status_code == 422
        assert env.status_store.get(body["id"]) is None


def test_the_raw_ref_of_the_source_must_be_the_folder_of_the_report():
    with Env() as env:
        body = submission()
        body["source"]["raw_ref"] = "raw/"
        assert send(env, body).status_code == 422


def test_a_submission_with_unknown_fields_is_refused():
    with Env() as env:
        body = submission(priority="high")
        store_photo(env, body)
        assert send(env, body).status_code == 422


def test_a_report_without_photo_and_text_is_refused():
    with Env() as env:
        assert send(env, submission(photo=False, text=None)).status_code == 422


def test_a_text_only_report_is_accepted():
    with Env() as env:
        response = send(env, submission(photo=False, text="Laterne kaputt"))
    assert response.status_code == 200 and response.json()["photo_urls"] == []


def test_only_the_app_channel_is_accepted_yet():
    with Env() as env:
        body = submission()
        body["source"]["type"] = "email"
        store_photo(env, body)
        assert send(env, body).status_code == 422


def test_the_rate_limit_counts_reports_of_both_ways():
    """The limit is per user, whether the report came straight from the app or through the gateway."""
    with Env(reports_per_hour=2) as env:
        assert env.post({"text": "Pothole"}).status_code == 200
        first = submission(client_report_id="report-0002", photo=False)
        assert send(env, first).status_code == 200
        assert send(env, submission(client_report_id="report-0003", photo=False)).status_code == 429
