from datetime import datetime, timezone

import httpx
import pytest

from models.incoming_report import IncomingReport
from privacy.detectors import PatternDetector
from privacy.graph import build_privacy_graph
from privacy.photo_store import InMemoryPhotoStore
from privacy.pseudonyms import InMemoryPseudonymStore
from privacy.report_status import InMemoryReportStatusStore, SupabaseReportStatusStore
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


# ---------------------------------------------------------------------------
# Supabase variant with a fake client
# ---------------------------------------------------------------------------


class FakeTable:
    def __init__(self, data=None, fail_first=False):
        self.data, self.fail_first, self.upserts, self.calls = data or [], fail_first, [], 0

    def upsert(self, row, on_conflict):
        self.upserts.append((row, on_conflict))
        return self

    def select(self, columns):
        return self

    def eq(self, column, value):
        return self

    def order(self, column, desc):
        return self

    def execute(self):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise httpx.ConnectError("x")
        return self


class FakeClient:
    def __init__(self, table):
        self.fake_table = table

    def table(self, name):
        assert name == "reports"
        return self.fake_table


def test_supabase_store_writes_one_row_per_report(monkeypatch):
    """The status is written as an upsert on the report id, including the block reason."""
    monkeypatch.setattr("privacy.retry.time.sleep", lambda _: None)
    table = FakeTable(fail_first=True)  # the first call fails with a network error, retry saves it
    SupabaseReportStatusStore(FakeClient(table)).set_status("7c9e", "blocked_privacy", "app", "sanitize_text: X")
    row, conflict = table.upserts[0]
    assert conflict == "id"
    assert (row["id"], row["status"], row["block_reason"]) == ("7c9e", "blocked_privacy", "sanitize_text: X")
    assert table.calls == 2


def test_supabase_store_lists_blocked_reports():
    """The operator list is built from the rows of the table."""
    table = FakeTable(data=[{"id": "a", "status": "blocked_privacy", "source_type": "app", "block_reason": "assemble: ValueError"}])
    [row] = SupabaseReportStatusStore(FakeClient(table)).list_blocked()
    assert (row.report_id, row.block_reason) == ("a", "assemble: ValueError")
