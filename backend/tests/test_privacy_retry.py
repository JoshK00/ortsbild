import io
import logging
from datetime import datetime, timezone

import botocore.exceptions
import httpx
import pytest

from models.incoming_report import IncomingReport
from privacy.detectors import PatternDetector
from privacy.graph import build_privacy_graph
from privacy.photo_store import InMemoryPhotoStore, S3PhotoStore
from privacy.pseudonyms import InMemoryPseudonymStore
from privacy.retry import is_transient_error, retry
from tests.image_helpers import make_jpeg


class FlakyCall:
    """Fails with the given errors one after another, then returns "ok"."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


class ErrorWithStatus(Exception):
    def __init__(self, status):
        self.status = status


# ---------------------------------------------------------------------------
# is_transient_error / retry
# ---------------------------------------------------------------------------


def test_network_errors_and_server_errors_are_transient():
    """Network trouble, overload and 5xx may go away on their own."""
    assert is_transient_error(httpx.ConnectError("x"))
    assert is_transient_error(httpx.ReadTimeout("x"))
    assert is_transient_error(ConnectionError())
    assert is_transient_error(ErrorWithStatus(503))
    assert is_transient_error(ErrorWithStatus("500"))
    assert is_transient_error(ErrorWithStatus(429))


def test_other_errors_are_not_transient():
    """A missing file (404), a bad request or a bug fail the same way every time."""
    assert not is_transient_error(ErrorWithStatus(404))
    assert not is_transient_error(ErrorWithStatus(400))
    assert not is_transient_error(ValueError("x"))
    assert not is_transient_error(KeyError("x"))


def test_retry_succeeds_after_transient_errors_and_waits_longer_each_time():
    """Two network errors, then success. The pause doubles: 0.5 s, then 1 s."""
    call, pauses = FlakyCall(httpx.ConnectError("x"), httpx.ConnectError("x")), []
    assert retry(call, "test", sleep=pauses.append) == "ok"
    assert call.calls == 3
    assert pauses == [0.5, 1.0]


def test_retry_gives_up_after_the_last_attempt():
    """If every try fails, the last error is raised so the step can fail closed."""
    call = FlakyCall(*[httpx.ConnectError("x")] * 5)
    with pytest.raises(httpx.ConnectError):
        retry(call, "test", attempts=3, sleep=lambda _: None)
    assert call.calls == 3


def test_retry_does_not_repeat_a_permanent_error():
    """A permanent error is raised at once, no pause, no second try."""
    call, pauses = FlakyCall(ValueError("broken image")), []
    with pytest.raises(ValueError):
        retry(call, "test", sleep=pauses.append)
    assert call.calls == 1 and pauses == []


def test_retry_logs_the_error_type_but_not_the_message(caplog):
    """The log helps to find the problem and never contains the content of the error."""
    call = FlakyCall(httpx.ConnectError("secret max@example.com"))
    with caplog.at_level(logging.WARNING, logger="ortsbild.privacy"):
        retry(call, "storage load", sleep=lambda _: None)
    assert "storage load" in caplog.text and "ConnectError" in caplog.text
    assert "max@example.com" not in caplog.text


# ---------------------------------------------------------------------------
# S3 store uses retry
# ---------------------------------------------------------------------------


class FakeS3:
    """Pretends to be the S3 client: the first read fails with a network error."""

    def __init__(self, error):
        self.error, self.calls = error, 0

    def get_object(self, Bucket, Key):
        self.calls += 1
        if self.calls == 1:
            raise self.error
        return {"Body": io.BytesIO(b"image")}


def test_s3_store_retries_a_network_error(monkeypatch):
    """A short network error while loading a photo does not block the report."""
    monkeypatch.setattr("privacy.retry.time.sleep", lambda _: None)
    client = FakeS3(botocore.exceptions.EndpointConnectionError(endpoint_url="http://x"))
    store = S3PhotoStore(client, {"raw": "r", "clean": "c"})
    assert store.load("raw/a/p1.jpg") == b"image"
    assert client.calls == 2


# ---------------------------------------------------------------------------
# Logging when a report is blocked
# ---------------------------------------------------------------------------


class BrokenDetector:
    def detect(self, text):
        raise RuntimeError("detector down: max@example.com")


def test_blocked_report_is_logged_with_id_step_and_error_type_only(caplog):
    """The log names report, step and error type. The error message (raw data) is not in it."""
    report = IncomingReport(
        id="7c9e",
        received_at=datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc),
        source={"type": "email", "connector": "imap", "raw_ref": "raw/7c9e/m.eml"},
        location={"lat": 48.1371, "lon": 11.5754},
        text="Call 0151 2345678",
        photos=[],
        user={"identifier": "max@example.com", "identifier_type": "email"},
    )
    graph = build_privacy_graph([BrokenDetector()], InMemoryPhotoStore(), InMemoryPseudonymStore("s"))
    with caplog.at_level(logging.ERROR, logger="ortsbild.privacy"):
        result = graph.invoke({"report": report})
    assert result["status"] == "blocked_privacy"
    assert "report_id=7c9e" in caplog.text
    assert "step=sanitize_text" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "max@example.com" not in caplog.text
