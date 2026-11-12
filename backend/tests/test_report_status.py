from datetime import datetime, timezone

import pytest

from models.incoming_report import IncomingReport
from privacy.detectors import PatternDetector
from privacy.graph import build_privacy_graph
from privacy.photo_store import InMemoryPhotoStore
from privacy.pseudonyms import InMemoryPseudonymStore
from privacy.report_status import InMemoryReportStatusStore
from privacy.service import process_report


class BrokenDetector:
    def detect(self, text):
        raise RuntimeError("detector down: max@example.com")


def make_report(report_id="7c9e", text="Call 0151 2345678"):
    return IncomingReport(
        id=report_id,
        received_at=datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc),
        source={"type": "email", "connector": "imap", "raw_ref": "raw/x/m.eml"},
        location={"lat": 48.1371, "lon": 11.5754},
        text=text,
        photos=[],
        user={"identifier": "max@example.com", "identifier_type": "email"},
    )


def graph_with(detector):
    return build_privacy_graph([detector], InMemoryPhotoStore(), InMemoryPseudonymStore("s"))


def test_successful_report_ends_as_sanitized():
    """A report that passes all steps is recorded as sanitized, and is not in the blocked list."""
    store = InMemoryReportStatusStore()
    process_report(make_report(), graph_with(PatternDetector()), store)
    assert store.rows["7c9e"].status == "sanitized"
    assert store.list_blocked() == []


def test_blocked_report_is_recorded_with_step_and_error_type_only():
    """A blocked report shows up in the operator list with its reason, without raw data."""
    store = InMemoryReportStatusStore()
    result = process_report(make_report(), graph_with(BrokenDetector()), store)
    assert result["status"] == "blocked_privacy"
    [row] = store.list_blocked()
    assert (row.report_id, row.source_type) == ("7c9e", "email")
    assert row.block_reason == "sanitize_text: RuntimeError"
    assert "max@example.com" not in repr(row)


def test_unexpected_crash_is_recorded_as_blocked_and_raised_again():
    """If something no step caught breaks the graph, the report is still not lost."""
    class CrashingGraph:
        def invoke(self, state):
            raise MemoryError("boom")

    store = InMemoryReportStatusStore()
    with pytest.raises(MemoryError):
        process_report(make_report(), CrashingGraph(), store)
    assert store.rows["7c9e"].block_reason == "graph: MemoryError"


def test_start_answer_moves_a_waiting_report_once():
    store = InMemoryReportStatusStore()
    store.set_status("r1", "needs_input", "app")
    assert store.start_answer("r1") is True and store.rows["r1"].status == "classified"
    assert store.start_answer("r1") is False  # the second answer finds nothing waiting


def test_start_answer_ignores_other_statuses_and_unknown_reports():
    store = InMemoryReportStatusStore()
    store.set_status("r1", "sanitized", "app")
    assert store.start_answer("r1") is False and store.start_answer("nobody") is False
    assert store.rows["r1"].status == "sanitized"


def test_a_report_takes_only_a_few_answers():
    from privacy.report_status import MAX_ANSWERS

    store = InMemoryReportStatusStore()
    results = []
    for _ in range(MAX_ANSWERS + 1):
        store.set_status("r1", "needs_input", "app")
        results.append(store.start_answer("r1"))
    assert results == [True] * MAX_ANSWERS + [False]
