from api.public import case_id_of
from tests.image_helpers import make_jpeg
from tests.test_api_reports import PLACE, Env, OneFace

POTHOLE = {"text": "Großes Schlagloch auf dem Radweg", "lat": "48.1371", "lon": "11.5754", **PLACE}
PHOTO = {"photo": ("p.jpg", make_jpeg(), "image/jpeg")}


def delete(env: Env, report_id: str, user="anna"):
    return env.client.delete(f"/v1/reports/{report_id}", headers=env.login(user))


def test_deleting_a_report_removes_the_report_and_its_photo():
    with Env(face_detector=OneFace()) as env:
        created = env.post(POTHOLE, files=PHOTO).json()
        assert delete(env, created["id"]).status_code == 204
        gone = env.client.get(f"/v1/reports/{created['id']}", headers=env.login())
        try:
            env.photo_store.load(f"clean/{created['id']}/p1.jpg")
            still_there = True
        except KeyError:
            still_there = False
    assert gone.status_code == 404 and not still_there
    assert env.status_store.get(created["id"]) is None


def test_deleting_twice_or_a_foreign_report_is_404_and_touches_nothing():
    with Env(face_detector=OneFace()) as env:
        created = env.post(POTHOLE, files=PHOTO, user="anna").json()
        assert delete(env, created["id"], user="ben").status_code == 404
        assert delete(env, "0" * 32).status_code == 404
        assert env.client.delete(f"/v1/reports/{created['id']}").status_code == 401
        assert env.status_store.get(created["id"]) is not None
        assert delete(env, created["id"]).status_code == 204
        assert delete(env, created["id"]).status_code == 404


def test_a_photo_that_cannot_be_deleted_keeps_the_report_and_says_so():
    with Env(face_detector=OneFace()) as env:
        created = env.post(POTHOLE, files=PHOTO).json()

        def broken(ref):
            raise RuntimeError("storage down")

        env.photo_store.delete = broken
        answer = delete(env, created["id"])
    assert answer.status_code == 503 and env.status_store.get(created["id"]) is not None


def test_a_released_report_leaves_the_dashboard_list_after_the_deletion():
    from api.public import key_prefixes_of

    with Env() as env:
        reporter = env.client.post("/v1/auth/apple", json={"identity_token": "apple:anna", "nonce": "n"}).json()["reporter_id"]
        env.demo_reporters.append(reporter)
        created = env.post_released(POTHOLE).json()
        prefixes = key_prefixes_of([reporter])
        assert [case["id"] for case in env.client.get("/v1/public/cases").json()["cases"]] == [case_id_of(created["id"])]
        assert len(env.status_store.list_visible(prefixes, 10)) == 1
        delete(env, created["id"])
        # the router keeps its list for 30 seconds, the database no longer has the report
        assert env.status_store.list_visible(prefixes, 10) == []
