import time
from dataclasses import dataclass
from typing import Literal, Protocol

Status = Literal["processing", "sanitized", "classified", "researched", "blocked_privacy", "rejected"]


@dataclass(frozen=True)
class ReportStatusRow:
    """Where a report is. Contains no personal data."""

    report_id: str
    status: Status
    source_type: str
    block_reason: str | None = None  # step and error type, never an error message


@dataclass(frozen=True)
class ReportRecord:
    """A report as the owner sees it: the status, who owns it and the sanitized result.

    `user_key` is the pseudonymous key of the owner (a keyed hash), never the Apple id.
    `sanitized` is the sanitized report as a dict, there is no raw data in a record.
    `classification` is the result of the classification as a dict, None until it exists.
    """

    report_id: str
    user_key: str | None
    status: Status
    block_reason: str | None = None
    sanitized: dict | None = None
    classification: dict | None = None
    research: dict | None = None  # the responsible authority and its sources, None if none was found


class ReportStatusStore(Protocol):
    """Keeps the status of every report, so an operator finds the blocked ones and an owner finds their reports."""

    def set_status(
        self, report_id: str, status: Status, source_type: str, block_reason: str | None = None
    ) -> None: ...

    def list_blocked(self) -> list[ReportStatusRow]: ...

    def claim(self, report_id: str, user_key: str, client_report_id: str, source_type: str, tenant: str) -> str:
        """Register a new report of a user and return the id that owns this `client_report_id`.

        Returns `report_id` if it is new, or the id of the earlier report if the app sent the same
        `client_report_id` before (a retry). Compare the result with `report_id` to see which.
        """
        ...

    def save_sanitized(self, report_id: str, sanitized: dict) -> None: ...

    def save_classification(self, report_id: str, classification: dict) -> None:
        """Keep the classification and move the report to the status `classified`."""
        ...

    def save_research(self, report_id: str, research: dict) -> None:
        """Keep the result of the research and move the report to the status `researched`."""
        ...

    def get(self, report_id: str) -> ReportRecord | None: ...

    def count_recent(self, user_key: str, seconds: int) -> int:
        """How many reports the user started in the last `seconds` seconds."""
        ...

    def delete_user(self, user_key: str) -> list[ReportRecord]:
        """Delete all reports of the user and return them, so their files can be deleted too."""
        ...


class InMemoryReportStatusStore:
    """Keeps the statuses in a dict. For tests and local experiments, nothing is persisted."""

    def __init__(self) -> None:
        self.rows: dict[str, ReportStatusRow] = {}
        self.owners: dict[str, str] = {}  # report id -> user key
        self.client_ids: dict[tuple[str, str], str] = {}  # (user key, client report id) -> report id
        self.sanitized: dict[str, dict] = {}
        self.classifications: dict[str, dict] = {}
        self.research: dict[str, dict] = {}
        self.started_at: dict[str, float] = {}  # report id -> time.monotonic()

    def set_status(
        self, report_id: str, status: Status, source_type: str, block_reason: str | None = None
    ) -> None:
        self.rows[report_id] = ReportStatusRow(report_id, status, source_type, block_reason)

    def list_blocked(self) -> list[ReportStatusRow]:
        return [row for row in self.rows.values() if row.status == "blocked_privacy"]

    def claim(self, report_id: str, user_key: str, client_report_id: str, source_type: str, tenant: str) -> str:
        existing = self.client_ids.get((user_key, client_report_id))
        if existing is not None:
            return existing
        self.client_ids[(user_key, client_report_id)] = report_id
        self.owners[report_id] = user_key
        self.started_at[report_id] = time.monotonic()
        self.rows[report_id] = ReportStatusRow(report_id, "processing", source_type)
        return report_id

    def save_sanitized(self, report_id: str, sanitized: dict) -> None:
        self.sanitized[report_id] = sanitized

    def save_classification(self, report_id: str, classification: dict) -> None:
        self.classifications[report_id] = classification
        row = self.rows[report_id]
        self.rows[report_id] = ReportStatusRow(report_id, "classified", row.source_type, row.block_reason)

    def save_research(self, report_id: str, research: dict) -> None:
        self.research[report_id] = research
        row = self.rows[report_id]
        self.rows[report_id] = ReportStatusRow(report_id, "researched", row.source_type, row.block_reason)

    def get(self, report_id: str) -> ReportRecord | None:
        row = self.rows.get(report_id)
        if row is None:
            return None
        return ReportRecord(
            report_id, self.owners.get(report_id), row.status, row.block_reason,
            self.sanitized.get(report_id), self.classifications.get(report_id), self.research.get(report_id),
        )

    def count_recent(self, user_key: str, seconds: int) -> int:
        now = time.monotonic()
        return sum(1 for rid, owner in self.owners.items() if owner == user_key and now - self.started_at[rid] <= seconds)

    def delete_user(self, user_key: str) -> list[ReportRecord]:
        deleted = [self.get(rid) for rid, owner in list(self.owners.items()) if owner == user_key]
        for record in deleted:
            rid = record.report_id
            self.rows.pop(rid, None)
            self.sanitized.pop(rid, None)
            self.classifications.pop(rid, None)
            self.research.pop(rid, None)
            self.started_at.pop(rid, None)
            self.owners.pop(rid, None)
        self.client_ids = {k: v for k, v in self.client_ids.items() if k[0] != user_key}
        return deleted
