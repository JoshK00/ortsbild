from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models.incoming_report import IncomingReport
from models.sanitized_report import SanitizedReport
from privacy.detectors import PatternDetector
from privacy.graph import build_privacy_graph
from privacy.photo_store import InMemoryPhotoStore
from privacy.pseudonyms import InMemoryPseudonymStore, hash_identifier
from tests.image_helpers import make_jpeg


# ---------------------------------------------------------------------------
# Pseudonyms
# ---------------------------------------------------------------------------


def test_same_identifier_gets_the_same_pseudonym():
    """A reporter keeps one pseudonym, so duplicates and votes can be grouped."""
    store = InMemoryPseudonymStore("secret")
    first = store.get_or_create("max@example.com", "email")
    assert store.get_or_create("max@example.com", "email") == first


def test_different_identifiers_get_different_pseudonyms():
    """Two reporters never share a pseudonym."""
    store = InMemoryPseudonymStore("secret")
    assert store.get_or_create("a@example.com", "email") != store.get_or_create("b@example.com", "email")


def test_pseudonym_does_not_contain_the_identifier():
    """The pseudonym is random and says nothing about the identifier."""
    pseudonym = InMemoryPseudonymStore("secret").get_or_create("max@example.com", "email")
    assert pseudonym.startswith("rep-")
    assert "max" not in pseudonym and "example" not in pseudonym


def test_store_keeps_only_a_hash_of_the_identifier():
    """The plain identifier is not stored, only its keyed hash."""
    store = InMemoryPseudonymStore("secret")
    store.get_or_create("max@example.com", "email")
    assert "max@example.com" not in repr(store.pseudonyms)
    assert hash_identifier("max@example.com", "email", "secret") in store.pseudonyms


def test_hash_depends_on_the_secret_and_the_type():
    """Without the secret nobody can recompute the hash, and the type is part of it."""
    base = hash_identifier("x", "email", "secret")
    assert base != hash_identifier("x", "email", "other-secret")
    assert base != hash_identifier("x", "user_key", "secret")


# ---------------------------------------------------------------------------
# Whole graph: the result is a SanitizedReport
# ---------------------------------------------------------------------------


def make_report(**overrides):
    data = {
        "id": "7c9e",
        "received_at": datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc),
        "source": {"type": "app", "connector": "ortsbild-ios", "raw_ref": "raw/7c9e/"},
        "location": {"lat": 48.1371, "lon": 11.5754},
        "text": "Hi, I am Max, call 0151 2345678",
        "photos": [{"id": "p1", "mime_type": "image/jpeg", "ref": "raw/7c9e/p1.jpg"}],
        "user": {"identifier": "max@example.com", "identifier_type": "email"},
    }
    data.update(overrides)
    return IncomingReport(**data)


def run(report, store=None):
    store = store or InMemoryPhotoStore()
    graph = build_privacy_graph([PatternDetector()], store, InMemoryPseudonymStore("secret"))
    return graph.invoke({"report": report}), store


def test_graph_returns_a_complete_sanitized_report():
    """Photo, text and user are sanitized and put together into one SanitizedReport."""
    store = InMemoryPhotoStore()
    store.save("raw/7c9e/p1.jpg", make_jpeg(with_exif=True), "image/jpeg")
    result, _ = run(make_report(), store)
    report = result["sanitized_report"]
    assert isinstance(report, SanitizedReport)
    assert report.id == "7c9e"
    assert report.text == "Hi, I am Max, call <PHONE>"
    assert report.photos[0].ref == "clean/7c9e/p1.jpg"
    assert report.pseudonym.startswith("rep-")
    assert {e.kind for e in report.redaction_log.entries} == {"exif", "phone", "user_identifier"}


def test_sanitized_report_keeps_the_location_unchanged():
    """The location is the defect location, the authority needs it exactly."""
    store = InMemoryPhotoStore()
    store.save("raw/7c9e/p1.jpg", make_jpeg(), "image/jpeg")
    result, _ = run(make_report(), store)
    assert (result["sanitized_report"].location.lat, result["sanitized_report"].location.lon) == (48.1371, 11.5754)


def test_no_plain_identifier_anywhere_in_the_sanitized_report():
    """The email of the reporter appears nowhere in the result."""
    store = InMemoryPhotoStore()
    store.save("raw/7c9e/p1.jpg", make_jpeg(), "image/jpeg")
    result, _ = run(make_report(), store)
    assert "max@example.com" not in result["sanitized_report"].model_dump_json()


def test_raw_photos_are_deleted_after_assembling():
    """When the sanitized report exists, the raw photo is gone and only the clean one remains."""
    store = InMemoryPhotoStore()
    store.save("raw/7c9e/p1.jpg", make_jpeg(), "image/jpeg")
    _, store = run(make_report(), store)
    assert "raw/7c9e/p1.jpg" not in store.files
    assert "clean/7c9e/p1.jpg" in store.files


def test_text_only_report_from_email_is_assembled():
    """A report without photos works too."""
    result, _ = run(make_report(photos=[], source={"type": "email", "connector": "imap", "raw_ref": "raw/7c9e/m.eml"}))
    assert result["sanitized_report"].photos == []
    assert result["sanitized_report"].source_type == "email"


def test_blocked_report_has_no_sanitized_report_and_keeps_the_raw_photo():
    """If a step blocks, no result is produced and the raw data stays for the operator."""
    store = InMemoryPhotoStore()
    store.save("raw/7c9e/p1.jpg", b"this is not an image", "image/jpeg")
    result, store = run(make_report(), store)
    assert result["status"] == "blocked_privacy"
    assert "sanitized_report" not in result
    assert "raw/7c9e/p1.jpg" in store.files


def test_sanitized_report_model_rejects_a_leftover_user_field():
    """Safety net in the contract: a user field can never be part of a SanitizedReport."""
    result, _ = run(make_report(photos=[]))
    data = result["sanitized_report"].model_dump()
    with pytest.raises(ValidationError):
        SanitizedReport(**data, user={"identifier": "max@example.com", "identifier_type": "email"})
