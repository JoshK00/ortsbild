from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models.sanitized_report import RedactionEntry, RedactionLog, SanitizedReport


# ---------------------------------------------------------------------------
# RedactionEntry / RedactionLog
# ---------------------------------------------------------------------------


def test_valid_redaction_entry_is_accepted():
    """Normal case: a detector removed two faces with a confidence."""
    entry = RedactionEntry(step="sanitize_photos", kind="face", count=2, confidence=0.93)
    assert entry.count == 2


def test_redaction_entry_without_confidence_is_accepted():
    """Deterministic steps like removing EXIF data have no confidence."""
    entry = RedactionEntry(step="strip_metadata", kind="exif", count=1)
    assert entry.confidence is None


def test_redaction_entry_with_count_zero_is_rejected():
    """An entry means something was removed, so the count must be at least 1."""
    with pytest.raises(ValidationError):
        RedactionEntry(step="sanitize_text", kind="email", count=0)


def test_redaction_entry_with_confidence_above_1_is_rejected():
    """Confidence is a value between 0 and 1."""
    with pytest.raises(ValidationError):
        RedactionEntry(step="sanitize_photos", kind="face", count=1, confidence=1.5)


def test_redaction_entry_with_unknown_kind_is_rejected():
    """Only known kinds pass, so the log stays comparable between steps."""
    with pytest.raises(ValidationError):
        RedactionEntry(step="sanitize_text", kind="shoe_size", count=1)


def test_redaction_entry_cannot_carry_the_removed_content():
    """The log records what was removed, never the content itself."""
    with pytest.raises(ValidationError):
        RedactionEntry(step="sanitize_text", kind="email", count=1, content="max@example.com")


def test_empty_redaction_log_is_accepted():
    """A report without anything to remove has an empty log."""
    assert RedactionLog().entries == []


# ---------------------------------------------------------------------------
# SanitizedReport
# ---------------------------------------------------------------------------


def make_sanitized_data(**overrides):
    """Build the data of a valid sanitized report, tests change only what they check."""
    data = {
        "id": "7c9e",
        "received_at": datetime(2026, 10, 27, 12, 30, tzinfo=timezone.utc),
        "source_type": "app",
        "location": {"lat": 48.137, "lon": 11.575},
        "text": "The bin at the bus stop is overflowing.",
        "photos": [{"id": "p1", "mime_type": "image/jpeg", "ref": "clean/7c9e/p1.jpg"}],
        "pseudonym": "rep-4f2a9c",
        "redaction_log": {"entries": [{"step": "strip_metadata", "kind": "exif", "count": 1}]},
    }
    data.update(overrides)
    return data


def test_valid_sanitized_report_is_accepted():
    """Normal case: a sanitized report with pseudonym and log."""
    report = SanitizedReport(**make_sanitized_data())
    assert report.pseudonym == "rep-4f2a9c"
    assert report.redaction_log.entries[0].kind == "exif"


def test_sanitized_report_without_pseudonym_is_rejected():
    """Later agents need the pseudonym to group reports of the same reporter."""
    data = make_sanitized_data()
    del data["pseudonym"]
    with pytest.raises(ValidationError):
        SanitizedReport(**data)


def test_sanitized_report_with_plain_user_is_rejected():
    """Privacy guarantee: the plain identifier must never survive into a sanitized report."""
    with pytest.raises(ValidationError):
        SanitizedReport(
            **make_sanitized_data(user={"identifier": "max@example.com", "identifier_type": "email"})
        )
