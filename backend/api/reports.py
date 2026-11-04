import io
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, UploadFile
from fastapi.responses import JSONResponse, Response
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

import privacy.photos  # noqa: F401  (registers the HEIC reader of Pillow)
from auth.account import delete_account
from auth.sessions import AuthManager
from auth.tokens import AccessClaims
from models.incoming_report import IncomingReport
from privacy.photo_store import PhotoStore
from privacy.pseudonyms import PseudonymStore
from privacy.report_status import ReportRecord, ReportStatusStore

logger = logging.getLogger("ortsbild.api")

MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = 5000
RATE_WINDOW_SECONDS = 3600

# what the file really is (detected from its content) -> (mime type, file extension)
IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "HEIF": ("image/heic", "heic"),
}


@dataclass
class Services:
    """The parts the endpoints need. Tests pass fakes, production passes the real ones.

    `graph` is the orchestrator of the whole chain (privacy, classification, ...), see orchestrator/graph.py.
    """

    graph: object
    photo_store: PhotoStore
    status_store: ReportStatusStore
    pseudonym_store: PseudonymStore
    auth: AuthManager


def detect_image(data: bytes) -> tuple[str, str]:
    """Return (mime type, extension) of an image by looking INTO the file, not at its name or header.

    The type the client claims is only a claim. Anything that is not a supported image is rejected.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            image_format = image.format
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise HTTPException(422, "the file is not a readable image")
    if image_format not in IMAGE_FORMATS:
        raise HTTPException(415, "only JPEG, PNG and HEIC images are accepted")
    return IMAGE_FORMATS[image_format]


def is_not_found(error: Exception) -> bool:
    """True if a store reports that a file does not exist (in-memory store or S3)."""
    if isinstance(error, KeyError):
        return True
    response = getattr(error, "response", None)
    return isinstance(response, dict) and response.get("Error", {}).get("Code") in ("NoSuchKey", "404")


def report_payload(record: ReportRecord) -> dict:
    """What the app gets for a report: sanitized (with the result), blocked, rejected or still processing.

    `status` is the outcome of the privacy layer. `classification` is the object of the classification, or null
    if it does not exist (yet). A blocked report gets no reason (it is in the log and the status table).
    A rejected one gets a short code.
    """
    empty = {"id": record.report_id, "report": None, "photo_urls": [], "classification": None}
    if record.status in ("sanitized", "classified") and record.sanitized is not None:
        photos = record.sanitized.get("photos", [])
        urls = [f"/v1/reports/{record.report_id}/photos/{photo['id']}" for photo in photos]
        return {
            "id": record.report_id, "status": "sanitized", "report": record.sanitized,
            "photo_urls": urls, "classification": record.classification,
        }
    if record.status == "blocked_privacy":
        return {**empty, "status": "blocked"}
    if record.status == "rejected":
        return {**empty, "status": "rejected", "reason": record.block_reason}
    return {**empty, "status": "processing"}


def create_reports_router(
    get_services: Callable[[], Services],
    current_user: Callable[..., AccessClaims],
    reports_per_hour: int = 20,
    tenant: str = "pilot",
) -> APIRouter:
    """The endpoints for reports and the account. Every one of them needs a signed-in user (Bearer token).

    A user sees only their own reports. `tenant` is the municipality, it is set here and never taken from the client.
    """
    router = APIRouter(prefix="/v1")

    def own_report(report_id: str, user: AccessClaims) -> ReportRecord:
        record = get_services().status_store.get(report_id)
        if record is None or record.user_key != user.user_key:
            raise HTTPException(404, "no such report")  # the same answer for a foreign report, so ids cannot be probed
        return record

    @router.post("/reports")
    def create_report(
        client_report_id: str = Form(..., min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$"),
        lat: float = Form(..., ge=-90, le=90),
        lon: float = Form(..., ge=-180, le=180),
        text: str | None = Form(None, max_length=MAX_TEXT_CHARS),
        accuracy_m: float | None = Form(None, ge=0),
        photo: UploadFile | None = File(None),
        user: AccessClaims = Depends(current_user),
    ) -> JSONResponse:
        """Take a photo and/or a text with the location, run it through the privacy layer.

        `client_report_id` is made up by the app (a UUID) and makes a retry safe: the same id from the
        same user returns the first result and creates nothing new.
        Returns the sanitized report, or status "blocked" / "rejected" if the privacy layer stopped it.
        """
        services = get_services()
        if services.status_store.count_recent(user.user_key, RATE_WINDOW_SECONDS) >= reports_per_hour:
            raise HTTPException(429, "too many reports, try again later")
        text = text.strip() if text else None
        data = photo.file.read(MAX_PHOTO_BYTES + 1) if photo is not None else b""
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "the photo is too big")
        if not data and not text:
            raise HTTPException(422, "send a photo or a text")
        image = detect_image(data) if data else None

        report_id = uuid.uuid4().hex
        owner_of_id = services.status_store.claim(report_id, user.user_key, client_report_id, "app", tenant)
        if owner_of_id != report_id:  # a retry: answer with the first result, do the work only once
            return JSONResponse(report_payload(own_report(owner_of_id, user)))

        photos = []
        if image:
            mime_type, extension = image
            raw_ref = f"raw/{report_id}/p1.{extension}"
            services.photo_store.save(raw_ref, data, mime_type)
            photos.append({"id": "p1", "mime_type": mime_type, "ref": raw_ref})

        try:
            report = IncomingReport(
                id=report_id,
                received_at=datetime.now(timezone.utc),
                source={"type": "app", "connector": "app-api", "raw_ref": f"raw/{report_id}/"},
                location={"lat": lat, "lon": lon, "accuracy_m": accuracy_m, "origin": "device_gps"},
                text=text,
                photos=photos,
                user={"identifier": user.user_key, "identifier_type": "user_key"},
            )
        except ValidationError:
            raise HTTPException(422, "the report is not valid")

        services.graph.invoke({"report": report})
        return JSONResponse(report_payload(own_report(report_id, user)))

    @router.get("/reports/{report_id}")
    def get_report(report_id: str = Path(pattern=r"^[0-9a-f]{32}$"), user: AccessClaims = Depends(current_user)) -> JSONResponse:
        """The status and, when it is ready, the sanitized result of one of your reports."""
        return JSONResponse(report_payload(own_report(report_id, user)))

    @router.get("/reports/{report_id}/photos/{photo_id}")
    def get_photo(
        report_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        photo_id: str = Path(pattern=r"^p[0-9]{1,2}$"),
        user: AccessClaims = Depends(current_user),
    ) -> Response:
        """The sanitized photo of one of your reports (faces covered, no metadata). Never the raw photo."""
        own_report(report_id, user)
        store = get_services().photo_store
        for extension, mime_type in (("jpg", "image/jpeg"), ("png", "image/png")):
            try:
                data = store.load(f"clean/{report_id}/{photo_id}.{extension}")
            except Exception as error:
                if is_not_found(error):
                    continue
                raise
            return Response(data, media_type=mime_type, headers={"Cache-Control": "no-store"})
        raise HTTPException(404, "no such photo")

    @router.delete("/account", status_code=204)
    def delete_my_account(user: AccessClaims = Depends(current_user)) -> Response:
        """Delete everything we hold about you: reports, photos, pseudonym and all sessions."""
        services = get_services()
        delete_account(user.user_key, services.status_store, services.photo_store, services.pseudonym_store, services.auth)
        return Response(status_code=204)

    return router
