from api.public import case_id_of
from tests.test_api_reports import PLACE, Env

POTHOLE = {"text": "Großes Schlagloch auf dem Radweg", "lat": "48.1371", "lon": "11.5754", **PLACE}


def reporter_id(env: Env, user: str) -> str:
    return env.client.post("/v1/auth/apple", json={"identity_token": f"apple:{user}", "nonce": "n"}).json()["reporter_id"]


def test_a_new_report_is_not_released_and_not_in_the_dashboard():
    with Env() as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        created = env.post(POTHOLE).json()
        assert created["approved"] is False
        assert env.client.get("/v1/public/cases").json()["cases"] == []


def test_releasing_a_report_shows_it_in_the_dashboard():
    with Env() as env:
        env.demo_reporters.append(reporter_id(env, "anna"))
        created = env.post(POTHOLE).json()
        released = env.release(created["id"])
        assert released.status_code == 200 and released.json()["approved"] is True
        assert env.client.get(f"/v1/reports/{created['id']}", headers=env.login("anna")).json()["approved"] is True
        shown = env.client.get("/v1/public/cases").json()["cases"]
    assert [case["id"] for case in shown] == [case_id_of(created["id"])]
    assert released.json()["case"]["case_id"] == shown[0]["id"]


def test_releasing_twice_is_fine_and_keeps_the_first_time():
    with Env() as env:
        created = env.post(POTHOLE).json()
        env.release(created["id"])
        first = env.status_store.get(created["id"]).approved_at
        again = env.release(created["id"])
        second = env.status_store.get(created["id"]).approved_at
    assert again.status_code == 200 and first is not None and first == second


def test_a_report_that_waits_for_an_answer_cannot_be_released():
    with Env() as env:
        created = env.post({"text": "Da stimmt etwas nicht", "lat": "48.1371", "lon": "11.5754"}).json()  # the user is asked first
        assert env.release(created["id"]).status_code == 409
        assert env.status_store.get(created["id"]).approved_at is None


def test_a_foreign_or_unknown_report_cannot_be_released():
    with Env() as env:
        created = env.post(POTHOLE, user="anna").json()
        assert env.release(created["id"], user="ben").status_code == 404
        assert env.release("0" * 32).status_code == 404
        assert env.status_store.get(created["id"]).approved_at is None


def test_releasing_needs_a_login():
    with Env() as env:
        created = env.post(POTHOLE).json()
        assert env.client.post(f"/v1/reports/{created['id']}/approve").status_code == 401
