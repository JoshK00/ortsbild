from tests.test_api_reports import PLACE, Env

POTHOLE = {"text": "Großes Schlagloch auf dem Radweg", "lat": "48.1371", "lon": "11.5754", **PLACE}


def test_the_first_report_of_a_defect_is_not_a_duplicate():
    with Env() as env:
        body = env.post(POTHOLE).json()
    assert body["case"]["votes"] == 1 and body["case"]["is_duplicate"] is False and body["case"]["first_reported_at"]
    assert len(body["case"]["case_id"]) == 16


def test_a_second_report_of_the_same_defect_is_a_duplicate_with_two_votes():
    """The answer says it was reported before, and the first reporter sees the new vote once the second one is released."""
    with Env() as env:
        first = env.post_released(POTHOLE, user="anna").json()
        second = env.post({**POTHOLE, "client_report_id": "report-0002", "lat": "48.13715"}, user="ben").json()
        env.release(second["id"], "ben")
        again = env.client.get(f"/v1/reports/{first['id']}", headers=env.login("anna")).json()
    assert second["case"]["votes"] == 2 and second["case"]["is_duplicate"] is True
    assert second["case"]["first_reported_at"] == first["case"]["first_reported_at"]
    assert second["case"]["case_id"] == first["case"]["case_id"]
    assert again["case"]["votes"] == 2 and again["case"]["is_duplicate"] is False  # anna was first


def test_the_same_user_reporting_again_also_adds_a_vote():
    with Env() as env:
        env.post_released(POTHOLE)
        second = env.post({**POTHOLE, "client_report_id": "report-0002"}).json()
    assert second["case"]["votes"] == 2 and second["case"]["is_duplicate"] is True


def test_a_report_that_was_not_released_is_no_vote_and_no_duplicate():
    """Only released reports are in the dashboard, so only they count. The own report counts, because the number is what the case has after the release."""
    with Env() as env:
        env.post(POTHOLE, user="anna")  # not released
        second = env.post({**POTHOLE, "client_report_id": "report-0002"}, user="ben").json()
    assert second["case"]["votes"] == 1 and second["case"]["is_duplicate"] is False


def test_another_place_or_category_is_not_a_duplicate():
    with Env() as env:
        env.post_released(POTHOLE, user="anna")
        far = env.post({**POTHOLE, "client_report_id": "report-0002", "lat": "48.1385"}, user="ben").json()  # about 150 m away
        other = env.post({**POTHOLE, "client_report_id": "report-0003", "text": "Graffiti an der Wand"}, user="ben").json()
    assert far["case"]["votes"] == 1 and far["case"]["is_duplicate"] is False
    assert other["case"]["votes"] == 1 and other["case"]["is_duplicate"] is False


def test_the_case_holds_only_counts_and_a_time_nothing_of_another_user():
    with Env() as env:
        env.post_released(POTHOLE, user="anna")
        second = env.post({**POTHOLE, "client_report_id": "report-0002"}, user="ben").json()
    assert sorted(second["case"]) == ["case_id", "first_reported_at", "is_duplicate", "votes"]


def test_a_report_without_a_category_yet_has_no_case():
    with Env() as env:
        body = env.post({"text": "Da stimmt etwas nicht", "lat": "48.1371", "lon": "11.5754"}).json()  # the user is asked first
    assert body["case"] is None


def test_a_failing_duplicate_check_does_not_break_the_answer():
    with Env() as env:
        def broken(*args, **kwargs):
            raise RuntimeError("database down")
        env.status_store.list_nearby = broken
        response = env.post(POTHOLE)
    assert response.status_code == 200 and response.json()["case"] is None and response.json()["status"] == "sanitized"
