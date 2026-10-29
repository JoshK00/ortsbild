from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol

from privacy.retry import retry

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


class SupabaseReportStatusStore:
    """Keeps the statuses in the Supabase table `reports` (see sql/002_reports.sql)."""

    TABLE = "reports"

    def __init__(self, client) -> None:
        self.client = client

    def set_status(
        self, report_id: str, status: Status, source_type: str, block_reason: str | None = None
    ) -> None:
        row = {
            "id": report_id,
            "status": status,
            "source_type": source_type,
            "block_reason": block_reason,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        retry(
            lambda: self.client.table(self.TABLE).upsert(row, on_conflict="id").execute(),
            "report status save",
        )

    def list_blocked(self) -> list[ReportStatusRow]:
        result = retry(
            lambda: self.client.table(self.TABLE)
            .select("id,status,source_type,block_reason")
            .eq("status", "blocked_privacy")
            .order("updated_at", desc=True)
            .execute(),
            "report status list",
        )
        return [
            ReportStatusRow(r["id"], r["status"], r["source_type"], r["block_reason"])
            for r in result.data
        ]
