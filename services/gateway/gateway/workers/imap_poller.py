"""Email channel worker: polls an IMAP inbox and ingests every unseen message.

Each message ends up in exactly one folder afterwards:
  processed  -> stored as a report (or was already stored before)
  ignored    -> auto-reply, bounce, or no text and no usable photo
  failed     -> unexpected error; inspect manually, then move back to the inbox to retry

Run:  python -m gateway.workers.imap_poller
"""

from __future__ import annotations

import imaplib
import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

from ..adapters.email import IgnoredEmail, parse_email
from ..config import Settings, get_settings
from ..db import ReportRepository
from ..ingest import EmptyReportError, IngestService
from ..storage import build_storage

log = logging.getLogger(__name__)


class Mailbox(Protocol):
    def fetch_unseen(self) -> list[tuple[bytes, bytes]]: ...  # (uid, raw message)
    def move(self, uid: bytes, folder: str) -> None: ...


@dataclass
class PollStats:
    processed: int = 0
    ignored: int = 0
    failed: int = 0
    report_ids: list[str] = field(default_factory=list)


def process_mailbox(mailbox: Mailbox, ingest: IngestService, settings: Settings) -> PollStats:
    stats = PollStats()
    for uid, raw in mailbox.fetch_unseen():
        try:
            result = ingest.ingest(parse_email(raw))
        except (IgnoredEmail, EmptyReportError) as exc:
            log.info("ignoring message uid=%s: %s", uid.decode(), exc)
            mailbox.move(uid, settings.imap_folder_ignored)
            stats.ignored += 1
            continue
        except Exception:
            log.exception("failed to ingest message uid=%s", uid.decode())
            mailbox.move(uid, settings.imap_folder_failed)
            stats.failed += 1
            continue
        mailbox.move(uid, settings.imap_folder_processed)
        stats.processed += 1
        stats.report_ids.append(str(result.report.id))
        log.info("message uid=%s -> report %s (new=%s)", uid.decode(), result.report.id, result.created)
    return stats


class ImapMailbox:
    """Thin wrapper around imaplib, using UIDs so message numbers can't shift under us."""

    def __init__(self, settings: Settings):
        if not (settings.imap_host and settings.imap_username and settings.imap_password):
            raise RuntimeError("GATEWAY_IMAP_HOST, GATEWAY_IMAP_USERNAME and GATEWAY_IMAP_PASSWORD are required")
        self.settings = settings
        self.conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
        self.conn.login(settings.imap_username, settings.imap_password.get_secret_value())
        for folder in (settings.imap_folder_processed, settings.imap_folder_ignored, settings.imap_folder_failed):
            self.conn.create(folder)  # returns NO if it already exists; that's fine
        self.conn.select(settings.imap_inbox)
        self._has_move = "MOVE" in (self.conn.capabilities or ())

    def fetch_unseen(self) -> list[tuple[bytes, bytes]]:
        typ, data = self.conn.uid("SEARCH", None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return []
        messages = []
        for uid in data[0].split():
            typ, parts = self.conn.uid("FETCH", uid, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None) if typ == "OK" else None
            if raw:
                messages.append((uid, raw))
        return messages

    def move(self, uid: bytes, folder: str) -> None:
        if self._has_move:
            self.conn.uid("MOVE", uid, folder)
            return
        self.conn.uid("COPY", uid, folder)
        self.conn.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
        self.conn.expunge()

    def close(self) -> None:
        try:
            self.conn.close()
        finally:
            self.conn.logout()


def run_forever(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    repo = ReportRepository.from_url(settings.database_url)
    ingest = IngestService(settings, repo, build_storage(settings))
    log.info("polling %s every %ss", settings.imap_host, settings.imap_poll_interval_s)
    while True:
        try:
            mailbox = ImapMailbox(settings)  # reconnect each round: simple and robust
            try:
                stats = process_mailbox(mailbox, ingest, settings)
            finally:
                mailbox.close()
            if stats.processed or stats.ignored or stats.failed:
                log.info("round done: %s", stats)
        except Exception:
            log.exception("polling round failed; retrying next interval")
        time.sleep(settings.imap_poll_interval_s)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_forever()
