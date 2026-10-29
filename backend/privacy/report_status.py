from dataclasses import dataclass
from typing import Literal, Protocol

Status = Literal["processing", "sanitized", "blocked_privacy", "rejected"]


@dataclass(frozen=True)
class ReportStatusRow:
    """Where a report is. Contains no personal data."""

    report_id: str
    status: Status
    source_type: str
    block_reason: str | None = None  # step and error type, never an error message


class ReportStatusStore(Protocol):
    """Keeps the status of every report, so an operator finds the blocked ones."""

    def set_status(
        self, report_id: str, status: Status, source_type: str, block_reason: str | None = None
    ) -> None: ...

    def list_blocked(self) -> list[ReportStatusRow]: ...


class InMemoryReportStatusStore:
    """Keeps the statuses in a dict. For tests and local experiments, nothing is persisted."""

    def __init__(self) -> None:
        self.rows: dict[str, ReportStatusRow] = {}

    def set_status(
        self, report_id: str, status: Status, source_type: str, block_reason: str | None = None
    ) -> None:
        self.rows[report_id] = ReportStatusRow(report_id, status, source_type, block_reason)

    def list_blocked(self) -> list[ReportStatusRow]:
        return [row for row in self.rows.values() if row.status == "blocked_privacy"]
