import logging

from fastapi.testclient import TestClient
from PIL import Image

from api.health import HealthCheckError, model_checks, run_checks, supabase_checks
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
# model_checks / supabase_checks
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


class FakeBucket:
    def __init__(self, name):
        self.name = name


class FakeSupabase:
    """Pretends to be the Supabase client: given buckets and tables."""

    def __init__(self, buckets, tables):
        self.buckets, self.tables, self.storage, self.current = buckets, tables, self, None

    def list_buckets(self):
        return [FakeBucket(b) for b in self.buckets]

    def table(self, name):
        if name not in self.tables:
            error = RuntimeError("relation does not exist")
            error.code = "PGRST205"
            raise error
        if name in getattr(self, "forbidden", []):
            error = RuntimeError("permission denied")
            error.code = "42501"
            raise error
        return self

    def select(self, columns):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return self


def test_supabase_checks_pass_when_buckets_and_tables_exist():
    """Everything the privacy layer needs is there."""
    checks = supabase_checks(FakeSupabase(["raw", "clean"], ["pseudonyms", "reports"]))
    assert all(r.ok for r in run_checks(checks))


def test_supabase_checks_name_the_missing_bucket_and_table():
    """The output says what to fix: a bucket, or a SQL file that was not run."""
    checks = supabase_checks(FakeSupabase(["raw"], ["pseudonyms"]))
    results = {r.name: r for r in run_checks(checks)}
    assert results["storage"].detail == "missing bucket: clean"
    assert results["table_reports"].detail == "table reports: table does not exist, run its SQL file"
    assert results["table_pseudonyms"].ok


def test_supabase_checks_tell_a_missing_permission_from_a_missing_table():
    """"permission denied" needs the GRANT lines, not a new table, the message says which."""
    client = FakeSupabase(["raw", "clean"], ["pseudonyms", "reports"])
    client.forbidden = ["reports"]
    results = {r.name: r for r in run_checks(supabase_checks(client))}
    assert results["table_reports"].detail == "table reports: permission denied, run the GRANT lines of its SQL file"


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


def test_health_is_200_when_everything_works():
    """The endpoint reports ok with one entry per check."""
    with TestClient(create_app({"models": ok, "storage": ok}, configure_logging=False)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"]["models"] == {"ok": True, "detail": "ok"}


def test_health_is_503_and_names_the_failing_part():
    """One broken part makes the whole answer 503, so a monitor notices it."""
    with TestClient(create_app({"models": ok, "storage": failing}, configure_logging=False)) as client:
        response = client.get("/health")
    body = response.json()
    assert response.status_code == 503 and body["status"] == "degraded"
    assert body["checks"]["storage"] == {"ok": False, "detail": "RuntimeError"}
    assert "sb_secret_123" not in response.text


def test_app_starts_even_if_a_check_fails():
    """A missing model must not stop the app, /health shows it instead."""
    with TestClient(create_app({"models": failing}, configure_logging=False)) as client:
        assert client.get("/health").status_code == 503
