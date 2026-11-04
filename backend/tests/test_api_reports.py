import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.main import create_app
from api.reports import MAX_PHOTO_BYTES, Services
from classification.provider import RuleBasedProvider
from classification.service import Classifier
from drafting.provider import TemplateDraftProvider
from drafting.service import Drafter
from orchestrator.graph import build_followup_graph, build_report_graph
from privacy.detectors import PatternDetector
from privacy.graph import build_privacy_graph
from privacy.image_detectors import Box
from privacy.photo_store import InMemoryPhotoStore
from privacy.pseudonyms import InMemoryPseudonymStore
from privacy.report_status import InMemoryReportStatusStore
from research.registry import InMemoryRegistryStore
from research.service import Researcher
from tests.auth_helpers import make_auth_manager, sign_in
from tests.image_helpers import make_heic, make_jpeg, make_png

FORM = {"client_report_id": "report-0001", "lat": "48.1371", "lon": "11.5754"}


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


class Env:
    """The app with in-memory parts, and the parts to look into."""

    def __init__(self, face_detector=None, text_detector=None, reports_per_hour=None, provider=None, research_provider=None, draft_provider=None, min_confidence=0.6):
        self.photo_store, self.status_store = InMemoryPhotoStore(), InMemoryReportStatusStore()
        self.pseudonym_store = InMemoryPseudonymStore("s")
        self.auth, self.token_store = make_auth_manager()
        privacy_graph = build_privacy_graph(
            [text_detector or PatternDetector()], self.photo_store, self.pseudonym_store,
            face_detector=face_detector or NoFace(),
        )
        self.registry = InMemoryRegistryStore()
        researcher = Researcher(self.registry, research_provider)
        drafter = Drafter(draft_provider or TemplateDraftProvider())
        graph = build_report_graph(privacy_graph, Classifier(provider or RuleBasedProvider(), self.photo_store), researcher, drafter, self.status_store, min_confidence)
        followup = build_followup_graph(researcher, drafter, self.status_store)
        services = Services(graph, self.photo_store, self.status_store, self.pseudonym_store, self.auth, followup)
        self.client = TestClient(create_app(checks={}, services=services, api_key="k", configure_logging=False, reports_per_hour=reports_per_hour))

    def __enter__(self):
        self.client.__enter__()
        return self

    def __exit__(self, *args):
        self.client.__exit__(*args)

    def login(self, user="anna"):
        return sign_in(self.client, user)

    def post(self, data=None, files=None, headers=None, user="anna"):
        headers = self.login(user) if headers is None else headers
        return self.client.post("/v1/reports", data={**FORM, **(data or {})}, files=files, headers=headers)


# ---------------------------------------------------------------------------
# Sign in
# ---------------------------------------------------------------------------


def test_request_without_a_token_is_rejected():
    """No sign-in, no access: the endpoint is public on the internet."""
    with Env() as env:
        assert env.post({"text": "Pothole"}, headers={}).status_code == 401


def test_request_with_a_wrong_token_is_rejected():
    with Env() as env:
        assert env.post({"text": "Pothole"}, headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_the_old_api_key_does_not_open_the_report_endpoints():
    """The shared key is gone from the reports, only a user session works."""
    with Env() as env:
        assert env.post({"text": "Pothole"}, headers={"X-API-Key": "k"}).status_code == 401


def test_a_token_stops_working_after_logout():
    """Logout ends the session at once, the access token does not live on for its hour."""
    with Env() as env:
        pair = env.client.post("/v1/auth/apple", json={"identity_token": "apple:anna", "nonce": "n"}).json()
        headers = {"Authorization": f"Bearer {pair['access_token']}"}
        assert env.post({"text": "x"}, headers=headers).status_code == 200
        env.client.post("/v1/auth/logout", json={"refresh_token": pair["refresh_token"]})
        assert env.post({"text": "y", "client_report_id": "report-0002"}, headers=headers).status_code == 401


def test_a_refused_apple_token_gives_401_without_details():
    with Env() as env:
        env.auth.verifier.fail = True
        response = env.client.post("/v1/auth/apple", json={"identity_token": "forged", "nonce": "n"})
    assert response.status_code == 401 and "forged" not in response.text


def test_refresh_gives_new_tokens_and_the_old_refresh_token_dies():
    with Env() as env:
        pair = env.client.post("/v1/auth/apple", json={"identity_token": "apple:anna", "nonce": "n"}).json()
        first = env.client.post("/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        again = env.client.post("/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert first.status_code == 200 and first.json()["refresh_token"] != pair["refresh_token"]
    assert again.status_code == 401


def test_the_apple_id_never_appears_in_a_response():
    with Env() as env:
        login = env.client.post("/v1/auth/apple", json={"identity_token": "apple:001234.secret-apple-id.5678", "nonce": "n"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        report = env.post({"text": "Pothole"}, headers=headers)
    assert "secret-apple-id" not in login.text + report.text


def test_health_needs_no_login():
    """Monitoring must work without a session."""
    with Env() as env:
        assert env.client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# POST /v1/reports
# ---------------------------------------------------------------------------


def test_text_report_is_sanitized_and_returned():
    """A text with a phone number comes back with the number replaced, and a pseudonym."""
    with Env() as env:
        response = env.post({"text": "Pothole, call 0151 2345678"})
        body = response.json()
        assert response.status_code == 200 and body["status"] == "sanitized"
        assert body["report"]["text"] == "Pothole, call <PHONE>"
        assert body["report"]["pseudonym"].startswith("rep-")
        assert env.status_store.rows[body["id"]].status == "needs_input"  # category other: the user is asked, nothing is researched


def test_photo_report_returns_a_clean_photo_and_deletes_the_raw_one():
    """Faces are covered, the metadata is gone, and the raw photo is deleted."""
    with Env(face_detector=OneFace()) as env:
        headers = env.login()
        response = env.post(files={"photo": ("p.jpg", make_jpeg(with_exif=True, size=(40, 20)), "image/jpeg")}, headers=headers)
        body = response.json()
        photo = env.client.get(body["photo_urls"][0], headers=headers)
    assert response.status_code == 200 and body["status"] == "sanitized"
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(photo.content)) as image:
        assert not dict(image.getexif())  # no EXIF
        assert sum(image.convert("RGB").getpixel((15, 10))) < 30  # face covered
    assert not [ref for ref in env.photo_store.files if ref.startswith("raw/")]


def test_png_and_heic_photos_are_accepted():
    """The type is detected from the content, so an iPhone photo (HEIC) works too."""
    with Env() as env:
        headers = env.login()
        png = env.post(files={"photo": ("p.png", make_png(), "image/png")}, headers=headers)
        heic = env.post({"client_report_id": "report-0002"}, files={"photo": ("p.heic", make_heic(), "application/octet-stream")}, headers=headers)
    assert png.status_code == 200
    assert heic.status_code == 200
    assert heic.json()["report"]["photos"][0]["mime_type"] == "image/jpeg"  # converted


def test_a_fake_image_is_rejected_even_with_an_image_content_type():
    """The claim of the client counts for nothing, the file itself is checked."""
    with Env() as env:
        response = env.post(files={"photo": ("p.jpg", b"this is not an image", "image/jpeg")})
    assert response.status_code == 422


def test_unsupported_image_format_is_rejected():
    """Only JPEG, PNG and HEIC."""
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="GIF")
    with Env() as env:
        assert env.post(files={"photo": ("p.gif", buffer.getvalue(), "image/gif")}).status_code == 415


def test_too_big_photo_is_rejected():
    with Env() as env:
        big = b"\xff\xd8" + b"0" * MAX_PHOTO_BYTES
        assert env.post(files={"photo": ("p.jpg", big, "image/jpeg")}).status_code == 413


def test_a_report_without_location_is_rejected():
    """The location is mandatory (decision in the data contract)."""
    with Env() as env:
        response = env.client.post("/v1/reports", data={"client_report_id": "report-0001", "text": "x"}, headers=env.login())
    assert response.status_code == 422


def test_an_invalid_coordinate_is_rejected():
    with Env() as env:
        assert env.post({"text": "x", "lat": "200"}).status_code == 422


def test_a_report_with_neither_photo_nor_text_is_rejected():
    with Env() as env:
        assert env.post({"text": "   "}).status_code == 422


def test_a_report_without_client_report_id_is_rejected():
    with Env() as env:
        response = env.client.post("/v1/reports", data={"lat": "48.1", "lon": "11.5", "text": "x"}, headers=env.login())
    assert response.status_code == 422


def test_blocked_report_gets_no_details_and_keeps_the_raw_photo():
    """If the privacy layer stops the report the client learns nothing, the operator finds it in the table."""
    with Env(text_detector=BrokenDetector()) as env:
        response = env.post({"text": "secret text"}, files={"photo": ("p.jpg", make_jpeg(), "image/jpeg")})
        body = response.json()
        assert response.status_code == 200 and body["status"] == "blocked" and body["report"] is None
        assert "secret" not in response.text
        assert env.status_store.list_blocked()[0].report_id == body["id"]
        assert [ref for ref in env.photo_store.files if ref.startswith("raw/")]  # kept for the operator


# ---------------------------------------------------------------------------
# Retry and limit
# ---------------------------------------------------------------------------


def test_a_retry_with_the_same_client_report_id_creates_nothing_new():
    """The app lost the answer and sends the same report again: same id back, one report only."""
    with Env() as env:
        headers = env.login()
        first = env.post({"text": "Pothole"}, headers=headers).json()
        second = env.post({"text": "Pothole"}, headers=headers).json()
    assert second == first
    assert len(env.status_store.owners) == 1


def test_the_same_client_report_id_of_two_users_are_two_reports():
    with Env() as env:
        anna = env.post({"text": "Pothole"}, user="anna").json()
        ben = env.post({"text": "Pothole"}, user="ben").json()
    assert anna["id"] != ben["id"]


def test_too_many_reports_in_an_hour_are_refused():
    """A signed-in user cannot flood the server with photos that need a lot of computing."""
    with Env(reports_per_hour=2) as env:
        headers = env.login()
        codes = [env.post({"text": "x", "client_report_id": f"report-000{i}"}, headers=headers).status_code for i in range(3)]
        other_user = env.post({"text": "x"}, user="ben").status_code
    assert codes == [200, 200, 429]
    assert other_user == 200  # the limit is per user


# ---------------------------------------------------------------------------
# GET /v1/reports/{id} and the photos
# ---------------------------------------------------------------------------


def test_the_owner_can_read_the_report_again():
    with Env() as env:
        headers = env.login()
        created = env.post({"text": "Pothole"}, headers=headers).json()
        read = env.client.get(f"/v1/reports/{created['id']}", headers=headers)
    assert read.status_code == 200 and read.json() == created


def test_a_foreign_report_looks_like_a_missing_one():
    """Another user gets 404, not 403, so report ids cannot be probed."""
    with Env(face_detector=OneFace()) as env:
        anna = env.login("anna")
        created = env.post(files={"photo": ("p.jpg", make_jpeg(size=(40, 20)), "image/jpeg")}, headers=anna).json()
        ben = env.login("ben")
        report = env.client.get(f"/v1/reports/{created['id']}", headers=ben)
        photo = env.client.get(created["photo_urls"][0], headers=ben)
        unknown = env.client.get(f"/v1/reports/{'a' * 32}", headers=ben)
    assert report.status_code == photo.status_code == 404
    assert report.json() == unknown.json()


def test_photo_of_an_unknown_report_is_404():
    with Env() as env:
        assert env.client.get(f"/v1/reports/{'a' * 32}/photos/p1", headers=env.login()).status_code == 404


def test_photo_ids_must_have_the_expected_form():
    """Nothing that looks like a path gets to the storage."""
    with Env() as env:
        headers = env.login()
        assert env.client.get("/v1/reports/..%2F..%2Fraw/photos/p1", headers=headers).status_code in (404, 422)
        assert env.client.get(f"/v1/reports/{'a' * 32}/photos/..", headers=headers).status_code in (404, 422)


def test_photo_and_report_need_a_login():
    with Env() as env:
        assert env.client.get(f"/v1/reports/{'a' * 32}/photos/p1").status_code == 401
        assert env.client.get(f"/v1/reports/{'a' * 32}").status_code == 401


def test_the_raw_photo_cannot_be_fetched():
    """Only the clean copy is reachable, never the raw one."""
    with Env() as env:
        headers = env.login()
        created = env.post({"text": "x"}, headers=headers).json()
        env.photo_store.save(f"raw/{created['id']}/p1.jpg", make_jpeg(), "image/jpeg")
        assert env.client.get(f"/v1/reports/{created['id']}/photos/p1", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# DELETE /v1/account
# ---------------------------------------------------------------------------


def test_deleting_the_account_removes_reports_photos_pseudonym_and_sessions():
    """Everything we hold about the user is gone, and the old token no longer works."""
    with Env(face_detector=OneFace()) as env:
        headers = env.login("anna")
        created = env.post({"text": "Pothole"}, files={"photo": ("p.jpg", make_jpeg(size=(40, 20)), "image/jpeg")}, headers=headers).json()
        assert env.photo_store.files and env.pseudonym_store.pseudonyms
        response = env.client.delete("/v1/account", headers=headers)
        after = env.client.get(f"/v1/reports/{created['id']}", headers=headers)
    assert response.status_code == 204
    assert env.photo_store.files == {} and env.status_store.rows == {} and env.pseudonym_store.pseudonyms == {}
    assert env.token_store.records == {}
    assert after.status_code == 401


def test_deleting_the_account_does_not_touch_other_users():
    with Env() as env:
        env.post({"text": "Anna"}, user="anna")
        ben_headers = env.login("ben")
        ben_report = env.post({"text": "Ben"}, headers=ben_headers).json()
        env.client.delete("/v1/account", headers=env.login("anna"))
        still_there = env.client.get(f"/v1/reports/{ben_report['id']}", headers=ben_headers)
    assert still_there.status_code == 200


def test_deleting_the_account_removes_the_raw_photo_of_a_blocked_report_too():
    with Env(text_detector=BrokenDetector()) as env:
        headers = env.login()
        env.post({"text": "x"}, files={"photo": ("p.jpg", make_jpeg(), "image/jpeg")}, headers=headers)
        assert env.photo_store.files
        env.client.delete("/v1/account", headers=headers)
    assert env.photo_store.files == {}


def test_deleting_the_account_needs_a_login():
    with Env() as env:
        assert env.client.delete("/v1/account").status_code == 401


# ---------------------------------------------------------------------------
# Classification in the chain
# ---------------------------------------------------------------------------


class BrokenProvider:
    def classify(self, data):
        raise RuntimeError("provider down: secret text")


class RecordingProvider:
    """Remembers what it was sent, so the tests can look at what leaves the server."""

    def __init__(self):
        self.seen = []

    def classify(self, data):
        self.seen.append(data)
        return RuleBasedProvider().classify(data)


def test_a_report_comes_back_with_its_classification():
    with Env() as env:
        body = env.post({"text": "Großes Schlagloch auf dem Radweg"}).json()
    assert body["status"] == "sanitized"
    assert body["classification"]["category"] == "pothole"
    assert set(body["classification"]) == {"category", "lane", "emergency", "confidence"}
    assert env.status_store.rows[body["id"]].status == "drafted"  # the chain ends with the draft


def test_the_classification_is_stored_and_read_again_by_the_owner():
    with Env() as env:
        headers = env.login()
        created = env.post({"text": "Graffiti an der Wand"}, headers=headers).json()
        read = env.client.get(f"/v1/reports/{created['id']}", headers=headers).json()
    assert read["classification"] == created["classification"] and read["classification"]["category"] == "graffiti"


def test_a_failing_provider_does_not_break_the_report():
    """The privacy result is delivered, the classification is null and the status stays sanitized."""
    with Env(provider=BrokenProvider()) as env:
        response = env.post({"text": "Schlagloch"})
        body = response.json()
    assert response.status_code == 200 and body["status"] == "sanitized"
    assert body["classification"] is None and body["report"]["text"] == "Schlagloch"
    assert env.status_store.rows[body["id"]].status == "sanitized"
    assert "secret text" not in response.text


def test_the_provider_gets_the_sanitized_text_and_nothing_about_the_person_or_the_place():
    provider = RecordingProvider()
    with Env(provider=provider) as env:
        env.post({"text": "Schlagloch, ruf mich an unter 0151 2345678", "lat": "48.13", "lon": "11.57"}, user="anna")
    [data] = provider.seen
    assert data.text == "Schlagloch, ruf mich an unter <PHONE>"
    everything = repr(data)
    assert "0151" not in everything and "48.13" not in everything and "anna" not in everything


def test_the_provider_gets_the_clean_photo_never_the_raw_one():
    provider = RecordingProvider()
    with Env(face_detector=OneFace(), provider=provider) as env:
        env.post(files={"photo": ("p.jpg", make_jpeg(size=(40, 20)), "image/jpeg")})
    [data] = provider.seen
    with Image.open(io.BytesIO(data.photo)) as image:
        assert sum(image.convert("RGB").getpixel((15, 10))) < 30  # the face is already covered


def test_an_emergency_text_is_flagged():
    with Env() as env:
        body = env.post({"text": "Auto brennt vor dem Haus"}).json()
    assert body["classification"]["emergency"] is True


def test_a_blocked_or_rejected_report_is_never_classified():
    provider = RecordingProvider()
    with Env(text_detector=BrokenDetector(), provider=provider) as env:
        body = env.post({"text": "secret text"}).json()
    assert body["status"] == "blocked" and body["classification"] is None
    assert provider.seen == []


def test_a_retry_returns_the_classification_of_the_first_answer():
    provider = RecordingProvider()
    with Env(provider=provider) as env:
        headers = env.login()
        first = env.post({"text": "Schlagloch"}, headers=headers).json()
        second = env.post({"text": "Schlagloch"}, headers=headers).json()
    assert second == first and len(provider.seen) == 1  # the model is not called twice


# ---------------------------------------------------------------------------
# Research in the chain
# ---------------------------------------------------------------------------

from research.models import Channel, ResearchResult  # noqa: E402
from research.provider import ScriptedResearchProvider  # noqa: E402

PLACE = {"country_code": "DE", "municipality": "München", "district": "Altstadt", "street": "Hauptstraße", "house_number": "12"}
FOUND = ResearchResult(
    authority="Baureferat Tiefbau", channel=Channel(type="email", target="tiefbau@muenchen.de"), language="de",
    sources=["https://www.muenchen.de/kontakt"], confidence=0.7,
)


def test_the_authority_comes_back_with_the_report():
    provider = ScriptedResearchProvider(FOUND)
    with Env(research_provider=provider) as env:
        body = env.post({"text": "Großes Schlagloch auf dem Radweg", **PLACE}).json()
    assert body["research"]["authority"] == "Baureferat Tiefbau" and body["research"]["channel"]["target"] == "tiefbau@muenchen.de"
    assert body["research"]["sources"] == ["https://www.muenchen.de/kontakt"]
    assert env.status_store.rows[body["id"]].status == "drafted"


def test_the_place_is_stored_with_the_location_and_returned():
    with Env(research_provider=ScriptedResearchProvider(FOUND)) as env:
        body = env.post({"text": "Schlagloch", **PLACE}).json()
    place = body["report"]["location"]["place"]
    assert {name: value for name, value in place.items() if value} == PLACE


def test_the_research_gets_only_the_place_and_the_category():
    provider = ScriptedResearchProvider(FOUND)
    with Env(research_provider=provider) as env:
        env.post({"text": "Schlagloch, ruf mich an unter 0151 2345678", "lat": "48.13", "lon": "11.57", **PLACE}, user="anna")
    [query] = provider.queries
    assert query.model_dump() == {"category": "pothole", "country_code": "DE", "municipality": "München", "district": "Altstadt", "exclude": []}


def test_the_second_report_from_the_same_place_needs_no_new_research():
    provider = ScriptedResearchProvider(FOUND)
    with Env(research_provider=provider) as env:
        env.post({"text": "Schlagloch", **PLACE}, user="anna")
        second = env.post({"text": "Schlagloch", "client_report_id": "report-0002", **PLACE}, user="ben").json()
    assert len(provider.queries) == 1 and second["research"]["origin"] == "registry"


def test_without_a_provider_or_a_place_the_research_is_null_and_the_report_still_works():
    with Env() as env:  # no research provider
        without_provider = env.post({"text": "Schlagloch", **PLACE}).json()
    with Env(research_provider=ScriptedResearchProvider(FOUND)) as env:
        without_place = env.post({"text": "Schlagloch"}).json()
    for body in (without_provider, without_place):
        assert body["status"] == "sanitized" and body["classification"] and body["research"] is None


def test_an_emergency_is_not_researched():
    provider = ScriptedResearchProvider(FOUND)
    with Env(research_provider=provider) as env:
        body = env.post({"text": "Auto brennt vor dem Haus", **PLACE}).json()
    assert body["classification"]["emergency"] is True and body["research"] is None and provider.queries == []


def test_a_failing_research_does_not_break_the_report():
    class Broken:
        def research(self, query):
            raise RuntimeError("search down: secret")

    with Env(research_provider=Broken()) as env:
        response = env.post({"text": "Schlagloch", **PLACE})
    assert response.status_code == 200 and response.json()["research"] is None and "secret" not in response.text


def test_the_owner_reads_the_authority_again_and_a_foreign_user_does_not():
    with Env(research_provider=ScriptedResearchProvider(FOUND)) as env:
        anna = env.login("anna")
        created = env.post({"text": "Schlagloch", **PLACE}, headers=anna).json()
        again = env.client.get(f"/v1/reports/{created['id']}", headers=anna).json()
        foreign = env.client.get(f"/v1/reports/{created['id']}", headers=env.login("ben"))
    assert again["research"] == created["research"] and foreign.status_code == 404


def test_an_invalid_place_is_rejected():
    with Env() as env:
        assert env.post({"text": "x", "country_code": "Deutschland"}).status_code == 422
        assert env.post({"text": "x", "municipality": "x" * 121}).status_code == 422


def test_empty_parts_of_the_place_are_dropped():
    with Env() as env:
        body = env.post({"text": "Schlagloch", "municipality": "  ", "street": "Hauptstraße"}).json()
    assert body["report"]["location"]["place"] == {"street": "Hauptstraße", "country_code": None, "state": None, "municipality": None, "district": None, "postal_code": None, "house_number": None}


def test_deleting_the_account_removes_the_research_of_the_user_but_keeps_the_registry():
    """The registry holds no report and no user, only a place and a public authority."""
    with Env(research_provider=ScriptedResearchProvider(FOUND)) as env:
        headers = env.login()
        env.post({"text": "Schlagloch", **PLACE}, headers=headers)
        env.client.delete("/v1/account", headers=headers)
    assert env.status_store.research == {} and len(env.registry.entries) == 1


# ---------------------------------------------------------------------------
# The draft in the chain
# ---------------------------------------------------------------------------


class RecordingDraftProvider:
    """Remembers what it was sent, so the tests can look at what leaves the server."""

    def __init__(self):
        self.seen = []

    def draft(self, data):
        self.seen.append(data)
        return TemplateDraftProvider().draft(data)


def test_the_draft_comes_back_with_the_report_and_holds_authority_contact_and_location():
    with Env(research_provider=ScriptedResearchProvider(FOUND)) as env:
        body = env.post({"text": "Großes Schlagloch auf dem Radweg", "lat": "48.13712", "lon": "11.57541", **PLACE}).json()
    draft = body["draft"]
    assert draft["authority"] == "Baureferat Tiefbau" and draft["contact"]["target"] == "tiefbau@muenchen.de" and draft["language"] == "de"
    assert "Standort / Location: Hauptstraße 12, München, DE | 48.13712, 11.57541" in draft["body"] and draft["subject"] and draft["summary_de"]
    assert env.status_store.rows[body["id"]].status == "drafted"


def test_the_draft_is_written_even_without_an_authority():
    with Env() as env:  # no research provider
        body = env.post({"text": "Großes Schlagloch auf dem Radweg", **PLACE}).json()
    assert body["research"] is None and body["draft"]["authority"] is None and body["draft"]["contact"] is None


def test_no_draft_for_an_emergency_or_for_a_report_that_is_no_defect():
    provider = RecordingDraftProvider()
    with Env(draft_provider=provider) as env:
        emergency = env.post({"text": "Auto brennt vor dem Haus", **PLACE}).json()
        other = env.post({"text": "Wann fährt der nächste Bus?", "client_report_id": "report-0002"}).json()
    assert emergency["draft"] is None and other["draft"] is None and provider.seen == []


def test_the_drafting_model_gets_only_the_sanitized_text_the_category_and_the_authority():
    provider = RecordingDraftProvider()
    with Env(research_provider=ScriptedResearchProvider(FOUND), draft_provider=provider) as env:
        env.post({"text": "Großes Schlagloch, ruf mich an unter 0151 2345678", "lat": "48.13712", "lon": "11.57541", **PLACE}, user="anna")
    [data] = provider.seen
    assert data.text == "Großes Schlagloch, ruf mich an unter <PHONE>" and data.authority == "Baureferat Tiefbau"
    seen = repr(data)
    assert "0151" not in seen and "Hauptstraße" not in seen and "48.137" not in seen and "anna" not in seen


def test_a_failing_draft_does_not_break_the_report():
    class Broken:
        def draft(self, data):
            raise RuntimeError("model down: secret")

    with Env(draft_provider=Broken(), research_provider=ScriptedResearchProvider(FOUND)) as env:
        response = env.post({"text": "Großes Schlagloch auf dem Radweg", **PLACE})
    body = response.json()
    assert response.status_code == 200 and body["draft"] is None and body["research"] is not None and "secret" not in response.text


def test_the_owner_reads_the_draft_again_and_a_retry_does_not_write_a_second_one():
    provider = RecordingDraftProvider()
    with Env(draft_provider=provider) as env:
        headers = env.login()
        first = env.post({"text": "Großes Schlagloch auf dem Radweg", **PLACE}, headers=headers).json()
        again = env.post({"text": "Großes Schlagloch auf dem Radweg", **PLACE}, headers=headers).json()
        read = env.client.get(f"/v1/reports/{first['id']}", headers=headers).json()
    assert again == first and read["draft"] == first["draft"] and len(provider.seen) == 1


def test_deleting_the_account_removes_the_draft():
    with Env() as env:
        headers = env.login()
        env.post({"text": "Großes Schlagloch auf dem Radweg", **PLACE}, headers=headers)
        env.client.delete("/v1/account", headers=headers)
    assert env.status_store.drafts == {}


# ---------------------------------------------------------------------------
# A picture that cannot be assigned: the user is asked, nothing is researched on a guess
# ---------------------------------------------------------------------------

from classification.models import CLARIFICATION_CATEGORIES, Classification  # noqa: E402


class FixedClassification:
    """A classification provider that always gives the same answer."""

    def __init__(self, **values):
        self.values = {"category": "pothole", "lane": "hazard", "emergency": False, "confidence": 0.3, **values}

    def classify(self, data):
        return Classification(**self.values)


def unsure(**values):
    """An environment whose classification doubts, with a recording research and draft provider."""
    research, draft = ScriptedResearchProvider(FOUND), RecordingDraftProvider()
    return Env(provider=FixedClassification(**values), research_provider=research, draft_provider=draft), research, draft


def test_an_unsure_classification_asks_and_researches_and_drafts_nothing():
    env, research, draft = unsure(confidence=0.3)
    with env:
        body = env.post({"text": "Etwas liegt auf der Straße", **PLACE}).json()
    assert body["status"] == "sanitized" and body["classification"]["confidence"] == 0.3
    assert body["clarification"] == {"reason": "unclear", "options": list(CLARIFICATION_CATEGORIES)}
    assert body["research"] is None and body["draft"] is None
    assert research.queries == [] and draft.seen == []
    assert env.status_store.rows[body["id"]].status == "needs_input"


def test_a_picture_without_a_known_defect_asks_as_well():
    env, research, draft = unsure(category="other", confidence=0.95)
    with env:
        body = env.post({"text": "Mein Hund im Park", **PLACE}).json()
    assert body["clarification"]["reason"] == "no_defect" and research.queries == [] and draft.seen == []


def test_a_sure_classification_asks_nothing_and_goes_on():
    env, research, _ = unsure(confidence=0.9)
    with env:
        body = env.post({"text": "Großes Schlagloch", **PLACE}).json()
    assert body["clarification"] is None and body["research"] is not None and body["draft"] is not None and len(research.queries) == 1


def test_the_threshold_is_the_one_that_was_set():
    with Env(provider=FixedClassification(confidence=0.7), min_confidence=0.8) as env:
        assert env.post({"text": "x", **PLACE}).json()["clarification"] is not None
    with Env(provider=FixedClassification(confidence=0.7), min_confidence=0.6) as env:
        assert env.post({"text": "x", **PLACE}).json()["clarification"] is None


def test_an_emergency_is_not_asked_about_even_if_unsure():
    env, research, _ = unsure(confidence=0.2, emergency=True)
    with env:
        body = env.post({"text": "Etwas ist passiert", **PLACE}).json()
    assert body["classification"]["emergency"] is True and body["clarification"] is None and research.queries == []


def test_a_failed_classification_is_not_asked_about_and_nothing_is_researched():
    class Broken:
        def classify(self, data):
            raise RuntimeError("model down")

    research = ScriptedResearchProvider(FOUND)
    with Env(provider=Broken(), research_provider=research) as env:
        body = env.post({"text": "Großes Schlagloch", **PLACE}).json()
    assert body["classification"] is None and body["clarification"] is None and body["research"] is None and research.queries == []


def test_the_answer_runs_the_research_and_the_draft_with_the_category_of_the_user():
    env, research, draft = unsure(confidence=0.3, lane="hazard")
    with env:
        headers = env.login()
        asked = env.post({"text": "Etwas liegt auf der Straße", **PLACE}, headers=headers).json()
        response = env.client.post(f"/v1/reports/{asked['id']}/answer", json={"category": "graffiti"}, headers=headers)
    body = response.json()
    assert response.status_code == 200 and body["clarification"] is None
    assert body["classification"] == {"category": "graffiti", "lane": "hazard", "emergency": False, "confidence": 1.0}
    assert body["research"]["authority"] == "Baureferat Tiefbau" and body["draft"]["authority"] == "Baureferat Tiefbau"
    assert research.queries[0].category == "graffiti" and draft.seen[0].category == "graffiti"
    assert env.status_store.rows[asked["id"]].status == "drafted"


def test_the_answer_is_kept_when_the_user_reads_the_report_again():
    env, _, _ = unsure(confidence=0.3)
    with env:
        headers = env.login()
        asked = env.post({"text": "x", **PLACE}, headers=headers).json()
        answered = env.client.post(f"/v1/reports/{asked['id']}/answer", json={"category": "tree"}, headers=headers).json()
        read = env.client.get(f"/v1/reports/{asked['id']}", headers=headers).json()
    assert read == answered and read["classification"]["category"] == "tree"


def test_a_question_can_be_answered_only_once():
    env, research, _ = unsure(confidence=0.3)
    with env:
        headers = env.login()
        asked = env.post({"text": "x", **PLACE}, headers=headers).json()
        url = f"/v1/reports/{asked['id']}/answer"
        first = env.client.post(url, json={"category": "tree"}, headers=headers)
        second = env.client.post(url, json={"category": "litter"}, headers=headers)
    assert first.status_code == 200 and second.status_code == 409 and len(research.queries) == 1


def test_a_report_without_a_question_cannot_be_answered():
    with Env(provider=FixedClassification(confidence=0.9)) as env:
        headers = env.login()
        done = env.post({"text": "x", **PLACE}, headers=headers).json()
        response = env.client.post(f"/v1/reports/{done['id']}/answer", json={"category": "tree"}, headers=headers)
    assert response.status_code == 409


def test_an_answer_needs_a_login_and_belongs_to_the_owner_only():
    env, research, _ = unsure(confidence=0.3)
    with env:
        anna = env.login("anna")
        asked = env.post({"text": "x", **PLACE}, headers=anna).json()
        url = f"/v1/reports/{asked['id']}/answer"
        without = env.client.post(url, json={"category": "tree"})
        foreign = env.client.post(url, json={"category": "tree"}, headers=env.login("ben"))
        unknown = env.client.post(f"/v1/reports/{'a' * 32}/answer", json={"category": "tree"}, headers=anna)
    assert (without.status_code, foreign.status_code, unknown.status_code) == (401, 404, 404)
    assert research.queries == [] and env.status_store.rows[asked["id"]].status == "needs_input"  # the foreign answer changed nothing


@pytest.mark.parametrize("body", [{"category": "other"}, {"category": "dog"}, {}, {"category": "tree", "extra": "x"}, {"category": None}])
def test_only_a_known_category_is_an_answer(body):
    env, research, _ = unsure(confidence=0.3)
    with env:
        headers = env.login()
        asked = env.post({"text": "x", **PLACE}, headers=headers).json()
        response = env.client.post(f"/v1/reports/{asked['id']}/answer", json=body, headers=headers)
    assert response.status_code == 422 and research.queries == []
    assert env.status_store.rows[asked["id"]].status == "needs_input"


def test_the_question_survives_a_new_read_by_the_owner():
    env, _, _ = unsure(confidence=0.3)
    with env:
        headers = env.login()
        asked = env.post({"text": "x", **PLACE}, headers=headers).json()
        read = env.client.get(f"/v1/reports/{asked['id']}", headers=headers).json()
    assert read["clarification"] == asked["clarification"] and read["clarification"]["reason"] == "unclear"
