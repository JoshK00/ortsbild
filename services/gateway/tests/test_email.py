from pathlib import Path

import pytest

from gateway.adapters.email import IgnoredEmail, parse_email
from gateway.ingest import EmptyReportError
from gateway.workers.imap_poller import process_mailbox
from tests.conftest import make_email, make_jpeg

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_plain_email_with_photo():
    incoming = parse_email(make_email(images=[make_jpeg()]))
    assert incoming.channel == "email"
    assert incoming.source_id == "abc123@example.org"
    assert incoming.reply_address == "buerger@example.org"
    assert incoming.text.startswith("Schlagloch Gartengasse")
    assert "Hausnummer 12" in incoming.text
    assert incoming.created_at.isoformat() == "2026-11-01T20:15:00+01:00"
    assert len(incoming.attachments) == 1
    assert incoming.anonymized_on_device is False


def test_parse_html_only_email():
    raw = make_email(body=None, html="<html><body><p>Ampel defekt</p><p>Ecke Hauptplatz</p></body></html>")
    text = parse_email(raw).text
    assert "Ampel defekt" in text and "Ecke Hauptplatz" in text and "<p>" not in text


def test_quoted_reply_lines_are_dropped():
    raw = make_email(body="Noch ein Foto dazu.\n> Ihre Meldung ist eingegangen\n> Danke")
    assert "eingegangen" not in parse_email(raw).text


def test_missing_message_id_falls_back_to_content_hash():
    raw = make_email(message_id=None)
    assert parse_email(raw).source_id.startswith("sha256:")


@pytest.mark.parametrize(
    "headers,sender",
    [
        ({"Auto-Submitted": "auto-replied"}, "buerger@example.org"),
        ({"Precedence": "bulk"}, "buerger@example.org"),
        ({"X-Autoreply": "yes"}, "buerger@example.org"),
        ({}, "mailer-daemon@example.org"),
    ],
)
def test_automatic_messages_are_ignored(headers, sender):
    with pytest.raises(IgnoredEmail):
        parse_email(make_email(headers=headers, sender=sender))


def test_eml_fixture_from_a_real_mail_client_parses():
    incoming = parse_email((FIXTURES / "report_with_photo.eml").read_bytes())
    assert incoming.source_id == "20261101201500.12345@mail.example.org"
    assert incoming.reply_address == "anna@example.org"
    assert "Laterne" in incoming.text
    assert len(incoming.attachments) == 1


def test_ingest_email_reads_location_from_exif_and_uses_raw_bucket(ingest, settings, storage):
    raw = make_email(images=[make_jpeg(gps=(47.0707, 15.4395))])
    result = ingest.ingest(parse_email(raw))
    report = result.report
    assert result.created
    assert report.location.source == "exif"
    assert report.location.lat == pytest.approx(47.0707, abs=1e-4)
    assert report.location.lon == pytest.approx(15.4395, abs=1e-4)
    (media,) = report.media
    assert media.bucket == settings.storage_bucket_raw and media.anonymized is False
    assert storage.get(media.bucket, media.key)  # stored


def test_ingest_email_without_gps_has_no_location(ingest):
    report = ingest.ingest(parse_email(make_email(images=[make_jpeg()]))).report
    assert report.location is None  # the intake agent will try the address in the text


def test_ingest_email_is_idempotent(ingest):
    raw = make_email()
    first = ingest.ingest(parse_email(raw))
    second = ingest.ingest(parse_email(raw))
    assert first.created and not second.created
    assert first.report.id == second.report.id


def test_broken_attachment_is_skipped_but_text_is_kept(ingest):
    report = ingest.ingest(parse_email(make_email(images=[b"garbage"]))).report
    assert report.media == [] and report.text


def test_email_with_nothing_usable_is_empty():
    incoming = parse_email(make_email(subject="", body=""))
    assert incoming.text is None and not incoming.attachments


class FakeMailbox:
    def __init__(self, messages):
        self.messages = messages
        self.moves: dict[bytes, str] = {}

    def fetch_unseen(self):
        return self.messages

    def move(self, uid, folder):
        self.moves[uid] = folder


def test_poller_sorts_messages_into_folders(ingest, settings, monkeypatch):
    mailbox = FakeMailbox(
        [
            (b"1", make_email(message_id="<one@x>")),
            (b"2", make_email(message_id="<two@x>", headers={"Auto-Submitted": "auto-replied"})),
            (b"3", make_email(message_id="<three@x>", subject="", body="")),
            (b"4", make_email(message_id="<four@x>")),
        ]
    )
    original = ingest.ingest

    def flaky(incoming):
        if incoming.source_id == "four@x":
            raise RuntimeError("database down")
        return original(incoming)

    monkeypatch.setattr(ingest, "ingest", flaky)
    stats = process_mailbox(mailbox, ingest, settings)

    assert mailbox.moves == {b"1": "processed", b"2": "ignored", b"3": "ignored", b"4": "failed"}
    assert (stats.processed, stats.ignored, stats.failed) == (1, 2, 1)


def test_empty_report_error_for_nothing_usable(ingest):
    with pytest.raises(EmptyReportError):
        ingest.ingest(parse_email(make_email(subject="", body="", images=[b"garbage"])))
