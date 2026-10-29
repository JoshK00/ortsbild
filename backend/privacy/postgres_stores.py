import os

import psycopg

from privacy.pseudonyms import hash_identifier, new_pseudonym
from privacy.report_status import ReportStatusRow, Status
from privacy.retry import retry


class PostgresPseudonymStore:
    """Keeps the pseudonyms in the PostgreSQL table `pseudonyms` (see sql/postgres/001_pseudonyms.sql).

    `connect` can be replaced in tests. One short connection per call, enough for the MVP.

    TODO: Use a connection pool once there is real load.
    TODO: Open question: may the authority contact the reporter? If yes, the identifier has to
          be stored (encrypted) as well, today only its hash is kept.
    """

    def __init__(self, dsn: str, secret: str, connect=psycopg.connect) -> None:
        self.dsn = dsn
        self.secret = secret
        self.connect = connect

    def get_or_create(self, identifier: str, identifier_type: str) -> str:
        identifier_hash = hash_identifier(identifier, identifier_type, self.secret)

        def run() -> str:
            with self.connect(self.dsn) as connection:
                # Insert first: if a parallel request created the row, the existing one is kept
                connection.execute(
                    "insert into pseudonyms (identifier_hash, pseudonym) values (%s, %s) "
                    "on conflict (identifier_hash) do nothing",
                    (identifier_hash, new_pseudonym()),
                )
                row = connection.execute(
                    "select pseudonym from pseudonyms where identifier_hash = %s", (identifier_hash,)
                ).fetchone()
            return row[0]

        return retry(run, "pseudonym lookup")


class PostgresReportStatusStore:
    """Keeps the statuses in the PostgreSQL table `reports` (see sql/postgres/002_reports.sql)."""

    def __init__(self, dsn: str, connect=psycopg.connect) -> None:
        self.dsn = dsn
        self.connect = connect

    def set_status(
        self, report_id: str, status: Status, source_type: str, block_reason: str | None = None
    ) -> None:
        def run() -> None:
            with self.connect(self.dsn) as connection:
                connection.execute(
                    "insert into reports (id, status, source_type, block_reason) values (%s, %s, %s, %s) "
                    "on conflict (id) do update set status = excluded.status, "
                    "source_type = excluded.source_type, block_reason = excluded.block_reason, "
                    "updated_at = now()",
                    (report_id, status, source_type, block_reason),
                )

        retry(run, "report status save")

    def list_blocked(self) -> list[ReportStatusRow]:
        def run():
            with self.connect(self.dsn) as connection:
                return connection.execute(
                    "select id, status, source_type, block_reason from reports "
                    "where status = 'blocked_privacy' order by updated_at desc"
                ).fetchall()

        return [ReportStatusRow(r[0], r[1], r[2], r[3]) for r in retry(run, "report status list")]


def postgres_pseudonym_store_from_env() -> PostgresPseudonymStore:
    """Build the pseudonym store from DATABASE_URL and PSEUDONYM_SECRET (backend/.env)."""
    from dotenv import load_dotenv

    load_dotenv()
    return PostgresPseudonymStore(os.environ["DATABASE_URL"], os.environ["PSEUDONYM_SECRET"])


def postgres_status_store_from_env() -> PostgresReportStatusStore:
    """Build the status store from DATABASE_URL (backend/.env)."""
    from dotenv import load_dotenv

    load_dotenv()
    return PostgresReportStatusStore(os.environ["DATABASE_URL"])
