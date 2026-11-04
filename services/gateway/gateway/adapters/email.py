"""Email channel: turns a raw RFC 5322 message into an ``IncomingReport``.

Kept free of any IMAP code so it can be tested with plain ``.eml`` files.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

from ..schema import Channel, IncomingReport, RawAttachment, ReplyChannel, utcnow

_AUTO_SENDERS = re.compile(r"^(mailer-daemon|postmaster|no-?reply|do-?not-?reply)@", re.IGNORECASE)


class IgnoredEmail(Exception):
    """The message is not a citizen report (auto-reply, bounce, ...)."""


def parse_email(raw: bytes) -> IncomingReport:
    msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw)

    reply_address = parseaddr(str(msg.get("Reply-To") or msg.get("From") or ""))[1].lower() or None
    reason = _auto_message_reason(msg, reply_address)
    if reason:
        raise IgnoredEmail(reason)

    subject = str(msg.get("Subject") or "").strip()
    body = _body_text(msg)
    text = "\n\n".join(part for part in (subject, body) if part) or None

    return IncomingReport(
        channel=Channel.EMAIL,
        source_id=_source_id(msg, raw),
        reply_channel=ReplyChannel.EMAIL,
        reply_address=reply_address,
        created_at=_sent_at(msg),
        text=text,
        location=None,  # the ingest service reads it from photo EXIF if present
        attachments=_images(msg),
        anonymized_on_device=False,
    )


def _auto_message_reason(msg: EmailMessage, sender: str | None) -> str | None:
    auto_submitted = str(msg.get("Auto-Submitted") or "no").strip().lower()
    if auto_submitted != "no":
        return f"Auto-Submitted: {auto_submitted}"
    precedence = str(msg.get("Precedence") or "").strip().lower()
    if precedence in {"bulk", "junk", "list", "auto_reply"}:
        return f"Precedence: {precedence}"
    if msg.get("X-Autoreply") or msg.get("X-Autorespond"):
        return "auto-reply header"
    if sender and _AUTO_SENDERS.match(sender):
        return f"automated sender: {sender}"
    return None


def _source_id(msg: EmailMessage, raw: bytes) -> str:
    message_id = str(msg.get("Message-ID") or "").strip().strip("<>")
    return message_id or "sha256:" + hashlib.sha256(raw).hexdigest()


def _sent_at(msg: EmailMessage):
    try:
        sent = parsedate_to_datetime(str(msg["Date"]))
    except (TypeError, ValueError, IndexError):
        return utcnow()
    return sent if sent.tzinfo else sent.replace(tzinfo=UTC)


def _body_text(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    if part.get_content_subtype() == "html":
        content = _html_to_text(content)
    return _drop_quoted_reply(content).strip()


def _drop_quoted_reply(text: str) -> str:
    """Remove '> quoted' lines that mail clients add when replying."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))


def _images(msg: EmailMessage) -> list[RawAttachment]:
    images = []
    for part in msg.walk():
        if part.get_content_maintype() != "image":
            continue
        data = part.get_payload(decode=True)
        if data:
            images.append(RawAttachment(data, part.get_content_type(), part.get_filename()))
    return images


class _TextExtractor(HTMLParser):
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"}
    _SKIP = {"script", "style", "head"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    return re.sub(r"\n\s*\n+", "\n\n", text)
