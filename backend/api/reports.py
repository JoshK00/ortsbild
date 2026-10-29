import hmac
import io
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Path, UploadFile
from fastapi.responses import JSONResponse, Response
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

import privacy.photos  # noqa: F401  (registers the HEIC reader of Pillow)
from models.incoming_report import IncomingReport
from privacy.photo_store import PhotoStore
from privacy.report_status import ReportStatusStore
from privacy.service import process_report

logger = logging.getLogger("ortsbild.api")

MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = 5000

# what the file really is (detected from its content) -> (mime type, file extension)
IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "HEIF": ("image/heic", "heic"),
}


@dataclass
class Services:
    """The parts the endpoints need. Tests pass fakes, production passes the real ones."""

    graph: object
    photo_store: PhotoStore
    status_store: ReportStatusStore


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


def create_reports_router(get_services: Callable[[], Services], get_api_key: Callable[[], str | None]) -> APIRouter:
    """The endpoints for reports. Every one of them needs the API key (header X-API-Key)."""

    def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
        expected = get_api_key()
        if not expected:
            raise HTTPException(503, "the API key is not configured")  # fail closed
        if not x_api_key or not hmac.compare_digest(x_api_key, expected):
            raise HTTPException(401, "invalid API key")

    router = APIRouter(dependencies=[Depends(require_api_key)])

    @router.post("/reports")
    def create_report(
        lat: float = Form(..., ge=-90, le=90),
        lon: float = Form(..., ge=-180, le=180),
        device_id: str = Form(..., min_length=1, max_length=200),
        text: str | None = Form(None, max_length=MAX_TEXT_CHARS),
        accuracy_m: float | None = Form(None, ge=0),
        photo: UploadFile | None = File(None),
    ) -> JSONResponse:
        """Take a photo and/or a text with the location, run it through the privacy layer.

        Returns the sanitized report, or status "blocked" if the privacy layer stopped it.
        TODO: Real authentication of the app instead of one shared API key.
        TODO: Limit the number of requests per device.
        """
        services = get_services()
        text = text.strip() if text else None
        data = photo.file.read(MAX_PHOTO_BYTES + 1) if photo is not None else b""
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "the photo is too big")
        if not data and not text:
            raise HTTPException(422, "send a photo or a text")

        report_id = uuid.uuid4().hex
        photos = []
        if data:
            mime_type, extension = detect_image(data)
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
                user={"identifier": device_id, "identifier_type": "device_id"},
            )
        except ValidationError:
            raise HTTPException(422, "the report is not valid")

        result = process_report(report, services.graph, services.status_store)
        if result.get("status") == "blocked_privacy":
            # No reason for the client, it is in the log and in the status table
            return JSONResponse({"id": report_id, "status": "blocked", "report": None, "photo_urls": []})
        sanitized = result["sanitized_report"]
        return JSONResponse(
            {
                "id": report_id,
                "status": "sanitized",
                "report": sanitized.model_dump(mode="json"),
                "photo_urls": [f"/reports/{report_id}/photos/{p.id}" for p in sanitized.photos],
            }
        )

    @router.get("/reports/{report_id}/photos/{photo_id}")
    def get_photo(
        report_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
        photo_id: str = Path(pattern=r"^p[0-9]{1,2}$"),
    ) -> Response:
        """The sanitized photo of a report (faces covered, no metadata). Never the raw photo."""
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

    return router
