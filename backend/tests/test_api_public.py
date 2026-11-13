import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.public import CACHE_SECONDS, case_id_of, create_public_router, key_prefixes_of
from api.reports import Services
from privacy.report_status import InMemoryReportStatusStore
from research.models import Channel, ResearchResult
from research.provider import ScriptedResearchProvider
from tests.image_helpers import make_jpeg
from tests.test_api_reports import FOUND, PLACE, BrokenDetector, Env, OneFace

POTHOLE = {"text": "Großes Schlagloch auf dem Radweg, ruf mich an unter 0151 2345678", "lat": "48.1371", "lon": "11.5754", **PLACE}


def reporter_id(env: Env, user: str) -> str:
    response = env.client.post("/v1/auth/apple", json={"identity_token": f"apple:{user}", "nonce": "n"})
    return response.json()["reporter_id"]


def cases(env: Env, response=None) -> list[dict]:
    response = response or env.client.get("/v1/public/cases")
    assert response.status_code == 200
    return response.json()["cases"]


# ---------------------------------------------------------------------------
# Who is visible
# ---------------------------------------------------------------------------


def test_without_an_allow_list_there_is_nothing_to_see():
    """The endpoint has no login, so an empty allow list shows nothing, however many reports exist."""
    with Env() as env:
        env.post_released(POTHOLE)
        assert cases(env) == []


def test_the_reports_of_an_allowed_user_are_shown_without_login_and_foreign_ones_are_not():
    with Env() as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        env.post_released(POTHOLE, user="anna")
        env.post_released({**POTHOLE, "client_report_id": "report-ben-1"}, user="ben")
        shown = cases(env)  # no Authorization header
    assert len(shown) == 1 and shown[0]["category"] == "pothole"


def test_an_entry_that_is_no_reporter_id_matches_nobody():
    """An empty or short entry must not become a prefix that matches every user."""
    with Env(demo_reporters=["", "usr-", "usr-abc", " ", "anna"]) as env:
        env.post_released(POTHOLE)
        assert cases(env) == []
    assert key_prefixes_of(["", "usr-", "usr-abc", "usr-0123456789ab", " usr-0123456789AB ", "usr-0123456789abc"]) == ["0123456789ab"]


def test_blocked_rejected_and_unclear_reports_are_not_shown():
    with Env(text_detector=BrokenDetector()) as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        assert env.post(POTHOLE).json()["status"] == "blocked"
        assert cases(env) == []
    with Env() as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        env.post({"text": "Da stimmt etwas nicht", "lat": "48.1", "lon": "11.5"})  # the user is asked, so no category yet
        assert cases(env) == []


# ---------------------------------------------------------------------------
# What is in a case
# ---------------------------------------------------------------------------


def test_a_case_has_the_exact_location_the_address_the_clean_text_and_the_draft():
    with Env(research_provider=ScriptedResearchProvider(FOUND)) as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        created = env.post_released(POTHOLE).json()
        (case,) = cases(env)
    assert (case["lat"], case["lon"]) == (48.1371, 11.5754)  # exact, an authority cannot act on less
    assert case["address"] == "Hauptstraße 12, München"
    assert case["text"] == "Großes Schlagloch auf dem Radweg, ruf mich an unter <PHONE>"  # sanitized, the number is gone
    assert case["lane"] in ("hazard", "nuisance") and case["status"] == "received"
    assert case["authority"] == "Baureferat Tiefbau"
    assert case["draft"]["subject"] and case["draft"]["contact"] == {"type": "email", "target": "tiefbau@muenchen.de"}
    assert case["id"] == case_id_of(created["id"]) and case["id"] != created["id"]


def test_nothing_else_about_a_report_leaves_through_the_door():
    """A fixed list of fields: no user key, no real report id, no pseudonym, no reference to the raw photo."""
    with Env(face_detector=OneFace(), research_provider=ScriptedResearchProvider(FOUND)) as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        headers = env.login("anna")
        created = env.post_released(POTHOLE, files={"photo": ("p.jpg", make_jpeg(), "image/jpeg")}, headers=headers).json()
        response = env.client.get("/v1/public/cases")
        user_key = env.status_store.owners[created["id"]]
    assert sorted(cases(env, response)[0]) == sorted(
        ["id", "category", "lane", "status", "created_at", "last_reported_at", "reports_count", "lat", "lon", "accuracy_m", "address", "text", "photo_url", "authority", "draft"]
    )
    for secret in (user_key, user_key[:12], created["id"], created["report"]["pseudonym"], "raw/"):
        assert secret not in response.text


def test_the_dashboard_answer_is_not_cached_by_the_browser():
    with Env() as env:
        assert env.client.get("/v1/public/cases").headers["cache-control"] == "no-store"


# ---------------------------------------------------------------------------
# The photo
# ---------------------------------------------------------------------------


def test_the_photo_route_serves_the_clean_copy_of_a_visible_case():
    with Env(face_detector=OneFace()) as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        created = env.post_released(POTHOLE, files={"photo": ("p.jpg", make_jpeg(), "image/jpeg")}).json()
        (case,) = cases(env)
        photo = env.client.get(case["photo_url"])  # no login
        clean = env.photo_store.load(f"clean/{created['id']}/p1.jpg")
    assert photo.status_code == 200 and photo.content == clean
    assert photo.headers["content-type"] == "image/jpeg"


def test_a_case_without_a_photo_has_no_photo_url():
    with Env() as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        env.post_released(POTHOLE)
        (case,) = cases(env)
        assert case["photo_url"] is None
        assert env.client.get(f"/v1/public/cases/{case['id']}/photo").status_code == 404


def test_the_photo_of_a_report_that_is_not_visible_is_404():
    """The id of a foreign or hidden report answers like an id that does not exist, and the real report id does not work."""
    with Env(face_detector=OneFace()) as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        files = {"photo": ("p.jpg", make_jpeg(), "image/jpeg")}
        ben = env.post_released({**POTHOLE, "client_report_id": "report-ben-1"}, files=files, user="ben").json()
        anna = env.post_released(POTHOLE, files={"photo": ("p.jpg", make_jpeg(), "image/jpeg")}, user="anna").json()
        answers = [
            env.client.get(f"/v1/public/cases/{case_id_of(ben['id'])}/photo"),  # a hidden report
            env.client.get(f"/v1/public/cases/{'0' * 16}/photo"),  # nothing
            env.client.get(f"/v1/public/cases/{anna['id']}/photo"),  # the real id is not a case id (wrong length)
        ]
    assert [answer.status_code for answer in answers[:2]] == [404, 404] and answers[2].status_code == 422
    assert answers[0].json() == answers[1].json()


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------


def test_the_list_is_read_from_the_database_at_most_every_30_seconds():
    class Counting(InMemoryReportStatusStore):
        reads = 0

        def list_visible(self, key_prefixes, limit):
            Counting.reads += 1
            return super().list_visible(key_prefixes, limit)

    now = [1000.0]
    store = Counting()
    app = FastAPI()
    app.include_router(create_public_router(lambda: Services(None, None, store, None, None), lambda: ["usr-0123456789ab"], lambda: now[0]))
    client = TestClient(app)
    for _ in range(5):
        client.get("/v1/public/cases")
    assert Counting.reads == 1
    now[0] += CACHE_SECONDS + 1
    client.get("/v1/public/cases")
    assert Counting.reads == 2


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def test_the_dashboard_page_is_served_next_to_the_api():
    with Env() as env:
        page = env.client.get("/dashboard/")
        script = env.client.get("/dashboard/app.js")
    assert page.status_code == 200 and "Ortsbild" in page.text
    assert script.status_code == 200


# ---------------------------------------------------------------------------
# The map file
# ---------------------------------------------------------------------------

from api.main import create_app  # noqa: E402


def test_the_map_file_is_served_in_pieces(tmp_path):
    """The browser reads the map file with range requests, so the answer has to be 206 with the right piece."""
    (tmp_path / "region.pmtiles").write_bytes(bytes(range(256)) * 4)
    client = TestClient(create_app(checks={}, services=object(), configure_logging=False, tiles_dir=tmp_path))
    piece = client.get("/tiles/region.pmtiles", headers={"Range": "bytes=10-19"})
    assert piece.status_code == 206 and piece.content == bytes(range(10, 20))
    assert piece.headers["content-range"] == "bytes 10-19/1024"
    assert client.get("/tiles/region.pmtiles").headers["accept-ranges"] == "bytes"


def test_the_map_folder_is_not_listed_and_does_not_open_other_files(tmp_path):
    folder = tmp_path / "tiles"
    folder.mkdir()
    (folder / "region.pmtiles").write_bytes(b"x")
    (tmp_path / "secret.txt").write_text("secret")
    client = TestClient(create_app(checks={}, services=object(), configure_logging=False, tiles_dir=folder))
    assert client.get("/tiles/").status_code == 404
    assert client.get("/tiles/../secret.txt").status_code == 404
    assert client.get("/tiles/%2e%2e/secret.txt").status_code == 404


def test_without_a_map_folder_nothing_is_served_and_the_app_still_starts(tmp_path, monkeypatch):
    monkeypatch.setenv("TILES_DIR", str(tmp_path / "does-not-exist"))
    client = TestClient(create_app(checks={}, services=object(), configure_logging=False))
    assert client.get("/tiles/region.pmtiles").status_code == 404
    assert client.get("/dashboard/").status_code == 200


def test_the_style_and_the_map_files_come_with_the_page():
    """Everything the map needs is ours: the style, the fonts, the symbols. The style names no other server."""
    with Env() as env:
        style = env.client.get("/dashboard/map/style_luftbild.json").text
        font = env.client.get("/dashboard/map/fonts/Noto%20Sans%20Regular/0-255.pbf")
        sprite = env.client.get("/dashboard/map/sprites/dark.json")
    assert font.status_code == 200 and sprite.status_code == 200
    assert "http" not in style.replace("https://www.openstreetmap.org/copyright", "")  # only the link of the attribution
    assert style.count("__ORIGIN__") == 4  # the names, the aerial photos, the fonts, the symbols: all from the address of the page


# ---------------------------------------------------------------------------
# Duplicates are one case
# ---------------------------------------------------------------------------


def test_the_same_defect_reported_twice_is_one_case_with_two_votes():
    """A second report of the same category at the same place does not make a second marker, it is one more vote."""
    with Env() as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        env.post_released(POTHOLE, user="anna")
        env.post_released({**POTHOLE, "client_report_id": "report-0002", "lat": "48.13712", "lon": "11.57541"}, user="anna")
        shown = cases(env)
    assert len(shown) == 1 and shown[0]["reports_count"] == 2


def test_another_category_or_another_place_is_another_case():
    with Env() as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        env.post_released(POTHOLE, user="anna")
        env.post_released({**POTHOLE, "client_report_id": "report-0002", "text": "Graffiti an der Wand"}, user="anna")  # same place, other category
        env.post_released({**POTHOLE, "client_report_id": "report-0003", "lat": "48.1385", "lon": "11.5754"}, user="anna")  # about 150 m away
        shown = cases(env)
    assert len(shown) == 3 and {case["reports_count"] for case in shown} == {1}


def test_the_photo_of_a_case_comes_from_the_report_that_has_one():
    with Env(face_detector=OneFace()) as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        env.post_released(POTHOLE, user="anna")  # the older report has no photo
        newer = env.post_released({**POTHOLE, "client_report_id": "report-0002"}, files={"photo": ("p.jpg", make_jpeg(), "image/jpeg")}, user="anna").json()
        (case,) = cases(env)
        photo = env.client.get(case["photo_url"])
        clean = env.photo_store.load(f"clean/{newer['id']}/p1.jpg")
    assert case["reports_count"] == 2 and photo.status_code == 200 and photo.content == clean


def test_a_star_in_the_allow_list_shows_the_released_reports_of_every_user():
    with Env(demo_reporters=["*"]) as env:
        env.post_released(POTHOLE, user="anna")
        env.post_released({**POTHOLE, "client_report_id": "report-ben-1", "lat": "48.1385"}, user="ben")
        env.post({**POTHOLE, "client_report_id": "report-ben-2", "lat": "48.1400"}, user="ben")  # not released
        assert len(cases(env)) == 2


def test_without_the_star_other_users_stay_hidden():
    with Env() as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        env.post_released(POTHOLE, user="anna")
        env.post_released({**POTHOLE, "client_report_id": "report-ben-1", "lat": "48.1385"}, user="ben")
        assert len(cases(env)) == 1


def test_the_dashboard_files_must_be_revalidated_so_a_deploy_never_mixes_old_and_new_files():
    with Env() as env:
        for path in ("/dashboard/", "/dashboard/app.js", "/dashboard/style.css"):
            answer = env.client.get(path)
            assert answer.status_code == 200 and answer.headers["cache-control"] == "no-cache" and answer.headers.get("etag"), path
            again = env.client.get(path, headers={"If-None-Match": answer.headers["etag"]})
            assert again.status_code == 304, path  # unchanged: one small answer
