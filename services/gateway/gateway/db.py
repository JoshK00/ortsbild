"""Persistence for canonical reports (SQLite for dev/tests, Postgres/Supabase in production)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, Float, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import Uuid

from .schema import (
    CanonicalReport,
    Channel,
    Enrichment,
    HistoryEntry,
    Location,
    LocationSource,
    MediaRef,
    ReplyChannel,
    ReportStatus,
)

JsonType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class ReportRow(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("channel", "source_id", name="uq_reports_channel_source"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[str] = mapped_column(String(512))
    reply_channel: Mapped[str] = mapped_column(String(16))
    reply_address: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    text: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    location_source: Mapped[str | None] = mapped_column(String(16))
    media: Mapped[list] = mapped_column(JsonType, default=list)
    enrichment: Mapped[dict] = mapped_column(JsonType, default=dict)
    history: Mapped[list] = mapped_column(JsonType, default=list)


def _aware(value: datetime) -> datetime:
    # SQLite drops tzinfo; everything we store is UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def to_row(report: CanonicalReport) -> ReportRow:
    loc = report.location
    return ReportRow(
        id=report.id,
        tenant=report.tenant,
        channel=report.channel.value,
        source_id=report.source_id,
        reply_channel=report.reply_channel.value,
        reply_address=report.reply_address,
        status=report.status.value,
        created_at=report.created_at,
        received_at=report.received_at,
        updated_at=report.updated_at,
        text=report.text,
        lat=loc.lat if loc else None,
        lon=loc.lon if loc else None,
        accuracy_m=loc.accuracy_m if loc else None,
        location_source=loc.source.value if loc else None,
        media=[m.model_dump(mode="json") for m in report.media],
        enrichment=report.enrichment.model_dump(mode="json", exclude_none=True),
        history=[h.model_dump(mode="json") for h in report.history],
    )


def from_row(row: ReportRow) -> CanonicalReport:
    location = None
    if row.lat is not None and row.lon is not None:
        location = Location(
            lat=row.lat, lon=row.lon, accuracy_m=row.accuracy_m, source=LocationSource(row.location_source)
        )
    return CanonicalReport(
        id=row.id,
        tenant=row.tenant,
        channel=Channel(row.channel),
        source_id=row.source_id,
        reply_channel=ReplyChannel(row.reply_channel),
        reply_address=row.reply_address,
        status=ReportStatus(row.status),
        created_at=_aware(row.created_at),
        received_at=_aware(row.received_at),
        updated_at=_aware(row.updated_at),
        text=row.text,
        location=location,
        media=[MediaRef(**m) for m in row.media or []],
        enrichment=Enrichment(**(row.enrichment or {})),
        history=[HistoryEntry(**h) for h in row.history or []],
    )


class ReportRepository:
    def __init__(self, engine: Engine):
        self.engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def from_url(cls, url: str) -> ReportRepository:
        engine = create_engine(url, pool_pre_ping=True)
        Base.metadata.create_all(engine)  # MVP: replace with Alembic migrations later
        return cls(engine)

    def add(self, report: CanonicalReport) -> None:
        """Insert a report. Raises ``sqlalchemy.exc.IntegrityError`` on a duplicate (channel, source_id)."""
        with self._sessions.begin() as session:
            session.add(to_row(report))

    def get(self, report_id: UUID) -> CanonicalReport | None:
        with Session(self.engine) as session:
            row = session.get(ReportRow, report_id)
            return from_row(row) if row else None

    def find_by_source(self, channel: Channel, source_id: str) -> CanonicalReport | None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(ReportRow).where(ReportRow.channel == channel.value, ReportRow.source_id == source_id)
            )
            return from_row(row) if row else None
