from datetime import datetime, timezone

import pytest

from models.incoming_report import IncomingReport
from privacy.detectors import Entity, PatternDetector, is_valid_iban
from privacy.graph import build_privacy_graph
from privacy.photo_store import InMemoryPhotoStore
from privacy.text import merge_entities, redact_text, sanitize_text


class FakeDetector:
    """Returns fixed hits, so the tests do not need the real model."""

    def __init__(self, entities):
        self.entities = entities

    def detect(self, text):
        return self.entities


class BrokenDetector:
    """Always fails, to test that the privacy layer fails closed."""

    def detect(self, text):
        raise RuntimeError("detector down: max@example.com")


# ---------------------------------------------------------------------------
# PatternDetector
# ---------------------------------------------------------------------------


def kinds_found(text):
    return {(text[e.start : e.end], e.kind) for e in PatternDetector().detect(text)}


def test_pattern_detector_finds_email():
    """An email address is found."""
    assert ("max.mueller@example.com", "email") in kinds_found("Write to max.mueller@example.com now")


def test_pattern_detector_finds_german_phone_numbers():
    """Phone numbers with and without country code are found."""
    found = kinds_found("Call 0151 2345678 or +49 151 2345678")
    assert ("0151 2345678", "phone") in found
    assert ("+49 151 2345678", "phone") in found


def test_pattern_detector_finds_license_plate():
    """A German license plate is found."""
    assert ("M-AB 1234", "plate") in kinds_found("The car M-AB 1234 blocks the road")


def test_pattern_detector_accepts_valid_iban():
    """An IBAN with a correct checksum is found."""
    assert ("DE89 3704 0044 0532 0130 00", "iban") in kinds_found("IBAN DE89 3704 0044 0532 0130 00 bitte")


def test_iban_with_wrong_checksum_is_not_flagged():
    """A string that only looks like an IBAN but fails the checksum is ignored."""
    assert not is_valid_iban("DE00 3704 0044 0532 0130 00")
    assert not any(kind == "iban" for _, kind in kinds_found("Ref DE00 3704 0044 0532 0130 00"))


def test_pattern_detector_ignores_normal_text():
    """Text without personal data produces no hits."""
    assert PatternDetector().detect("The bin at the bus stop is overflowing.") == []


# ---------------------------------------------------------------------------
# merge_entities / redact_text / sanitize_text
# ---------------------------------------------------------------------------


def test_merge_keeps_the_longer_of_two_overlapping_hits():
    """Two detectors find the same piece, only one hit remains."""
    short = Entity(0, 5, "name", 0.9)
    long = Entity(0, 10, "email", None)
    assert merge_entities([short, long]) == [long]


def test_redact_text_replaces_hits_and_logs_without_content():
    """Hits become placeholders, the log says what and how often, never the content."""
    text = "Hi Max Müller, mail max@example.com"
    entities = [Entity(3, 13, "name", 0.99), Entity(20, 35, "email")]
    clean, log = redact_text(text, entities)
    assert clean == "Hi <PERSON>, mail <EMAIL>"
    assert {(e.kind, e.count) for e in log} == {("name", 1), ("email", 1)}
    assert "Max" not in repr(log) and "example.com" not in repr(log)


def test_redact_text_keeps_the_lowest_confidence_per_kind():
    """The log shows the least certain hit of each kind."""
    text = "Anna and Ben"
    clean, log = redact_text(text, [Entity(0, 4, "name", 0.9), Entity(9, 12, "name", 0.6)])
    assert clean == "<PERSON> and <PERSON>"
    assert log[0].count == 2 and log[0].confidence == 0.6


def test_addresses_are_not_redacted_by_default():
    """The street in a report is usually the defect location, so it stays for now."""
    text = "Pothole at Hauptstr. 5"
    clean, log = redact_text(text, [Entity(11, 22, "address", 0.99)])
    assert clean == text and log == []


def test_sanitize_text_combines_all_detectors():
    """Patterns and the model detector work on the same text."""
    text = "Max Müller, max@example.com"
    clean, _ = sanitize_text(text, [PatternDetector(), FakeDetector([Entity(0, 10, "name", 0.95)])])
    assert clean == "<PERSON>, <EMAIL>"


# ---------------------------------------------------------------------------
# sanitize_text step inside the graph
# ---------------------------------------------------------------------------


def make_report(text):
    return IncomingReport(
        id="7c9e",
        received_at=datetime(2026, 10, 27, 12, 30, tzinfo=timezone.utc),
        source={"type": "email", "connector": "imap-inbox", "raw_ref": "raw/7c9e/m.eml"},
        location={"lat": 48.1371, "lon": 11.5754},
        text=text,
        photos=[],
        user={"identifier": "max@example.com", "identifier_type": "email"},
    )


def test_graph_sanitizes_the_text_and_fills_the_log():
    """The step replaces personal data in the text and appends to the redaction log."""
    graph = build_privacy_graph([PatternDetector()], InMemoryPhotoStore())
    result = graph.invoke({"report": make_report("Call 0151 2345678 about the pothole")})
    assert result["text"] == "Call <PHONE> about the pothole"
    assert result["redactions"][0].kind == "phone"
    assert result["status"] == "running"


def test_graph_without_text_passes_without_entries():
    """A report without text is fine, there is just nothing to redact."""
    graph = build_privacy_graph([PatternDetector()], InMemoryPhotoStore())
    result = graph.invoke({"report": make_report(None)})
    assert result["text"] is None
    assert result.get("redactions", []) == []


def test_graph_fails_closed_when_a_detector_breaks():
    """If a detector fails, the report is blocked and no unsanitized text is passed on."""
    graph = build_privacy_graph([BrokenDetector()], InMemoryPhotoStore())
    result = graph.invoke({"report": make_report("Call 0151 2345678")})
    assert result["status"] == "blocked_privacy"
    assert "text" not in result
    assert "max@example.com" not in result["block_reason"]
