"""Canonical report schema.

Every channel adapter produces an :class:`IncomingReport`. The ingest service turns it into a
:class:`CanonicalReport`, which is what the agents and the dashboard work with. From this point
on the system no longer cares which channel a report came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- enums


class Channel(StrEnum):
    IOS = "ios"
    EMAIL = "email"


class ReplyChannel(StrEnum):
    """How status updates get back to the citizen."""

    APP_STATUS = "app_status"  # the app polls GET /v1/reports/{id}
    EMAIL = "email"


class ReportStatus(StrEnum):
    """Lifecycle of a report. The gateway only ever sets ``received``."""

    RECEIVED = "received"
    ENRICHED = "enriched"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    FORWARDED = "forwarded"
    RESOLVED = "resolved"
    CLOSED = "closed"  # citizen chose "close" in the app, nothing was sent
    DUPLICATE = "duplicate"  # merged into an existing report, only its counter was raised
    REJECTED = "rejected"


class LocationSource(StrEnum):
    GPS = "gps"  # device GPS sent by the app
    EXIF = "exif"  # read from the photo's EXIF data before it was stripped
    TEXT = "text"  # geocoded from an address in the text (set later by the intake agent)


class Actor(StrEnum):
    GATEWAY = "gateway"
    AGENT = "agent"
    HUMAN = "human"


# --------------------------------------------------------------------------- value objects


class Location(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(None, ge=0)
    source: LocationSource


class MediaRef(BaseModel):
    """Pointer to a photo in object storage. Photos never go into the database."""

    bucket: str
    key: str
    content_type: str = "image/jpeg"
    width: int
    height: int
    size_bytes: int
    anonymized: bool = Field(description="False until the privacy check has run on this photo.")


class AgentResult(BaseModel):
    """One field filled in by an agent, always with its confidence and reasoning."""

    value: str | int | float | bool | None
    confidence: float = Field(ge=0, le=1, description="Agent's self-assessed certainty, 0..1.")
    rationale: str | None = None


class Enrichment(BaseModel):
    """Filled by the agents after the gateway. Empty when the gateway stores a report."""

    category: AgentResult | None = None
    severity: AgentResult | None = None
    emergency: AgentResult | None = None
    responsibility: AgentResult | None = None
    priority: AgentResult | None = None


class HistoryEntry(BaseModel):
    at: datetime = Field(default_factory=utcnow)
    actor: Actor
    step: str
    status: ReportStatus | None = None
    note: str | None = None


# --------------------------------------------------------------------------- canonical report


class CanonicalReport(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant: str
    channel: Channel
    source_id: str = Field(description="ID in the source system: client_report_id or email Message-ID.")
    reply_channel: ReplyChannel
    reply_address: str | None = Field(
        None, description="Where status updates go: device ID for the app, email address for email."
    )
    created_at: datetime = Field(description="When the citizen created the report.")
    received_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    status: ReportStatus = ReportStatus.RECEIVED
    text: str | None = None
    location: Location | None = None
    media: list[MediaRef] = Field(default_factory=list)
    enrichment: Enrichment = Field(default_factory=Enrichment)
    history: list[HistoryEntry] = Field(default_factory=list)


# --------------------------------------------------------------------------- adapter output


@dataclass
class RawAttachment:
    data: bytes
    content_type: str | None = None
    filename: str | None = None


@dataclass
class IncomingReport:
    """What a channel adapter hands to the ingest service."""

    channel: Channel
    source_id: str
    reply_channel: ReplyChannel
    reply_address: str | None
    created_at: datetime
    text: str | None = None
    location: Location | None = None
    attachments: list[RawAttachment] = field(default_factory=list)
    anonymized_on_device: bool = False
