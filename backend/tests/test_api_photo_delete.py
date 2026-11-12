from api.public import case_id_of
from research.provider import ScriptedResearchProvider
from tests.image_helpers import make_jpeg
from tests.test_api_reports import FOUND, PLACE, Env, OneFace

POTHOLE = {"text": "Großes Schlagloch auf dem Radweg", "lat": "48.1371", "lon": "11.5754", **PLACE}
PHOTO = {"photo": ("p.jpg", make_jpeg(), "image/jpeg")}


def with_photo(env: Env, user="anna") -> dict:
    return env.post(POTHOLE, files=PHOTO, user=user).json()


def remove(env: Env, report_id: str, user="anna"):
    return env.client.delete(f"/v1/reports/{report_id}/photo", headers=env.login(user))


def test_removing_the_photo_deletes_the_raw_and_the_clean_file():
    with Env(face_detector=OneFace(), research_provider=ScriptedResearchProvider(FOUND)) as env:
        created = with_photo(env)
        assert created["photo_urls"] and "Anhang" not in created["draft"]["body"]
        answer = remove(env, created["id"])
        body = answer.json()
        for ref in (f"raw/{created['id']}/p1.jpg", f"clean/{created['id']}/p1.jpg"):
            try:
                env.photo_store.load(ref)
                raise AssertionError(f"{ref} is still there")
            except KeyError:
                pass
        gone = env.client.get(f"/v1/reports/{created['id']}/photos/p1", headers=env.login())
    assert answer.status_code == 200 and body["photo_urls"] == [] and body["report"]["photos"] == []
    assert body["draft"]["body"] == created["draft"]["body"]  # the letter has no attachment line, so nothing changes in it
    assert gone.status_code == 404
    assert body["classification"] == created["classification"]  # the report itself stays


def test_removing_twice_is_fine():
    with Env(face_detector=OneFace()) as env:
        created = with_photo(env)
        assert remove(env, created["id"]).status_code == 200
        assert remove(env, created["id"]).status_code == 200


def test_removing_the_photo_of_a_report_without_a_photo_is_fine():
    with Env() as env:
        created = env.post(POTHOLE).json()
        assert remove(env, created["id"]).status_code == 200


def test_a_foreign_or_unknown_report_cannot_be_touched():
    with Env(face_detector=OneFace()) as env:
        created = with_photo(env, user="anna")
        assert remove(env, created["id"], user="ben").status_code == 404
        assert remove(env, "0" * 32).status_code == 404
        assert env.client.delete(f"/v1/reports/{created['id']}/photo").status_code == 401
        assert env.photo_store.load(f"clean/{created['id']}/p1.jpg")  # still there


def test_a_photo_that_cannot_be_deleted_stays_in_the_report_and_the_user_is_told():
    with Env(face_detector=OneFace()) as env:
        created = with_photo(env)

        def broken(ref):
            raise RuntimeError("storage down")

        env.photo_store.delete = broken
        answer = remove(env, created["id"])
        again = env.client.get(f"/v1/reports/{created['id']}", headers=env.login()).json()
    assert answer.status_code == 503 and again["photo_urls"]


def test_after_the_release_the_dashboard_has_no_photo_any_more():
    with Env(face_detector=OneFace()) as env:
        env.demo_reporters.append(env.client.post("/v1/auth/apple", json={"identity_token": "apple:anna", "nonce": "n"}).json()["reporter_id"])
        created = env.post_released(POTHOLE, files=PHOTO).json()
        (case,) = env.client.get("/v1/public/cases").json()["cases"]
        assert env.client.get(case["photo_url"]).status_code == 200
        remove(env, created["id"])
        assert env.client.get(case["photo_url"]).status_code == 404  # the answer of the list may be 30 s old, the file is gone
    assert case["id"] == case_id_of(created["id"])
