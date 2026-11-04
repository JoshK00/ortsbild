"""iOS app channel: the app sends structured fields, so the adapter only maps them."""

from datetime import UTC, datetime
from uuid import UUID

from ..schema import Channel, IncomingReport, Location, LocationSource, RawAttachment, ReplyChannel


def to_incoming(
    *,
    client_report_id: UUID,
    device_id: str,
    created_at: datetime,
    lat: float,
    lon: float,
    accuracy_m: float | None,
    text: str | None,
    photo: bytes | None,
    photo_content_type: str | None,
    anonymized_on_device: bool,
) -> IncomingReport:
    return IncomingReport(
        channel=Channel.IOS,
        source_id=str(client_report_id),
        reply_channel=ReplyChannel.APP_STATUS,
        reply_address=device_id,
        created_at=created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC),
        text=text,
        location=Location(lat=lat, lon=lon, accuracy_m=accuracy_m, source=LocationSource.GPS),
        attachments=[RawAttachment(photo, photo_content_type)] if photo else [],
        anonymized_on_device=anonymized_on_device,
    )
