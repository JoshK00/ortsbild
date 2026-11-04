"""The one code path every channel goes through after its adapter."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from .config import Settings
from .db import ReportRepository
from .images import InvalidImageError, process_image
from .schema import (
    Actor,
    CanonicalReport,
    Channel,
    HistoryEntry,
    IncomingReport,
    Location,
    LocationSource,
    MediaRef,
    ReportStatus,
)
from .storage import Storage

log = logging.getLogger(__name__)


class EmptyReportError(ValueError):
    """Neither text nor a usable photo."""


@dataclass
class IngestResult:
    report: CanonicalReport
    created: bool  # False when the same (channel, source_id) was ingested before


class IngestService:
    def __init__(self, settings: Settings, repo: ReportRepository, storage: Storage):
        self.settings = settings
        self.repo = repo
        self.storage = storage

    def ingest(self, incoming: IncomingReport) -> IngestResult:
        existing = self.repo.find_by_source(incoming.channel, incoming.source_id)
        if existing:
            return IngestResult(existing, created=False)

        text = (incoming.text or "").strip()[: self.settings.max_text_chars] or None
        attachments = incoming.attachments[: self.settings.max_photos_per_report]
        if not text and not attachments:
            raise EmptyReportError("a report needs text or a photo")

        report = CanonicalReport(
            tenant=self.settings.tenant,
            channel=incoming.channel,
            source_id=incoming.source_id,
            reply_channel=incoming.reply_channel,
            reply_address=incoming.reply_address,
            created_at=incoming.created_at,
            text=text,
            location=incoming.location,
        )

        # Photos that were not anonymized on the device go to the private raw bucket
        # until the server-side privacy check has handled them.
        anonymized = incoming.anonymized_on_device
        bucket = self.settings.storage_bucket_anonymized if anonymized else self.settings.storage_bucket_raw
        stored: list[MediaRef] = []
        try:
            for index, attachment in enumerate(attachments):
                try:
                    image = process_image(
                        attachment.data,
                        max_bytes=self.settings.max_photo_bytes,
                        max_edge_px=self.settings.max_photo_edge_px,
                    )
                except InvalidImageError as exc:
                    if incoming.channel is Channel.IOS:
                        raise  # the app must send a valid photo; surface it as a client error
                    log.warning("skipping attachment %s of %s: %s", index, incoming.source_id, exc)
                    continue
                if report.location is None and image.gps:
                    report.location = Location(lat=image.gps[0], lon=image.gps[1], source=LocationSource.EXIF)
                key = f"{report.tenant}/{report.id}/{index}.jpg"
                self.storage.put(bucket, key, image.data, "image/jpeg")
                stored.append(
                    MediaRef(
                        bucket=bucket,
                        key=key,
                        width=image.width,
                        height=image.height,
                        size_bytes=len(image.data),
                        anonymized=anonymized,
                    )
                )

            if not text and not stored:
                raise EmptyReportError("no usable photo and no text")

            report.media = stored
            report.history.append(
                HistoryEntry(
                    actor=Actor.GATEWAY,
                    step="ingest",
                    status=ReportStatus.RECEIVED,
                    note=f"channel={report.channel.value}; photos={len(stored)}; "
                    f"location={report.location.source.value if report.location else 'none'}",
                )
            )
            self.repo.add(report)
            return IngestResult(report, created=True)

        except IntegrityError:
            # Another request with the same source_id won the race: keep theirs, drop our uploads.
            self._delete(stored)
            existing = self.repo.find_by_source(incoming.channel, incoming.source_id)
            if existing is None:
                raise
            return IngestResult(existing, created=False)
        except Exception:
            self._delete(stored)
            raise

    def _delete(self, media: list[MediaRef]) -> None:
        for ref in media:
            try:
                self.storage.delete(ref.bucket, ref.key)
            except Exception:  # cleanup is best effort
                log.exception("could not delete %s/%s", ref.bucket, ref.key)
