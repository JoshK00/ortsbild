import logging

from fastapi.testclient import TestClient
from PIL import Image

from api.health import HealthCheckError, model_checks, run_checks
from api.main import create_app


def ok():
    return None


def failing():
    raise RuntimeError("secret sb_secret_123 max@example.com")


# ---------------------------------------------------------------------------
# run_checks
# ---------------------------------------------------------------------------


def test_run_checks_reports_ok_and_failed():
    """A check passes if it does not raise."""
    results = {r.name: r for r in run_checks({"a": ok, "b": failing})}
    assert results["a"].ok and not results["b"].ok


def test_failed_check_shows_only_the_error_type_not_the_message():
    """A secret in an error message must never reach the health output or the log."""
    [result] = run_checks({"b": failing})
    assert result.detail == "RuntimeError"


def test_failed_check_with_a_safe_message_shows_it():
    """Our own messages (missing bucket) are shown, they help to fix the problem."""
    def missing():
        raise HealthCheckError("missing bucket: clean")

    assert run_checks({"storage": missing})[0].detail == "missing bucket: clean"


def test_failed_check_is_logged_without_the_message(caplog):
    """The log names the check and the error type only."""
    with caplog.at_level(logging.WARNING, logger="ortsbild.api"):
        run_checks({"models": failing})
    assert "name=models detail=RuntimeError" in caplog.text
    assert "sb_secret_123" not in caplog.text


# ---------------------------------------------------------------------------
# model_checks
# ---------------------------------------------------------------------------


class FakeFaceDetector:
    def detect(self, image):
        assert isinstance(image, Image.Image)
        return []


class BrokenFaceDetector:
    def detect(self, image):
        raise RuntimeError("model file missing")


class FakeTextDetector:
    def detect(self, text):
        return []


def test_model_checks_pass_for_working_models():
    """Every model answers on a tiny input."""
    checks = model_checks(FakeFaceDetector(), [FakeTextDetector()], None)
    assert all(r.ok for r in run_checks(checks))
    assert set(checks) == {"face_detector", "text_detector_0_FakeTextDetector"}  # no OCR check when it is off


def test_model_checks_fail_for_a_broken_model():
    """A model that cannot run makes its check fail."""
    results = {r.name: r for r in run_checks(model_checks(BrokenFaceDetector(), [], None))}
    assert not results["face_detector"].ok


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


KEY = {"X-API-Key": "k"}


def make_client(checks):
    return TestClient(create_app(checks, api_key="k", configure_logging=False))


def test_health_is_200_when_everything_works():
    """The endpoint reports ok with one entry per check, for a caller with the API key."""
    with make_client({"models": ok, "storage": ok}) as client:
        response = client.get("/health", headers=KEY)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"]["models"] == {"ok": True, "detail": "ok"}


def test_health_is_503_and_names_the_failing_part():
    """One broken part makes the whole answer 503, so a monitor notices it."""
    with make_client({"models": ok, "storage": failing}) as client:
        response = client.get("/health", headers=KEY)
    body = response.json()
    assert response.status_code == 503 and body["status"] == "degraded"
    assert body["checks"]["storage"] == {"ok": False, "detail": "RuntimeError"}
    assert "sb_secret_123" not in response.text


def test_health_without_the_key_shows_only_the_status():
    """A stranger learns that the system is up, not how it is built or what is wrong."""
    with make_client({"models": ok, "storage": failing}) as client:
        anonymous = client.get("/health")
        wrong_key = client.get("/health", headers={"X-API-Key": "wrong"})
    for response in (anonymous, wrong_key):
        assert response.status_code == 503  # a monitor still sees the problem
        assert response.json() == {"status": "degraded"}


def test_health_shows_no_details_when_no_key_is_configured():
    """Fail closed: without a configured key nobody gets the details."""
    with TestClient(create_app({"models": ok}, api_key="", configure_logging=False)) as client:
        assert client.get("/health", headers={"X-API-Key": ""}).json() == {"status": "ok"}


def test_health_checks_are_not_repeated_for_every_request():
    """A flood of requests must not trigger the model and storage checks each time."""
    calls = []

    def counting():
        calls.append(1)

    with make_client({"models": counting}) as client:
        calls.clear()  # forget the run at startup
        for _ in range(5):
            client.get("/health")
    assert len(calls) <= 1


def test_app_starts_even_if_a_check_fails():
    """A missing model must not stop the app, /health shows it instead."""
    with make_client({"models": failing}) as client:
        assert client.get("/health").status_code == 503
