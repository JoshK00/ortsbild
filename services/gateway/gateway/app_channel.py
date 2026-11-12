"""The app channel: POST /v1/reports, exactly as the app sends it today (ios/Ortsbild/Services/BackendClient.swift).

The request and the answer are the ones of the backend (backend/api/reports.py, `create_report`),
so the app does not change.
Caddy sends this one request here, every other request of the app goes straight to the backend (deploy/Caddyfile).

What the gateway does:
1. Check the input of the channel: the form fields, the size and the real type of the photo.
2. Store the raw photo in the raw bucket of the backend.
3. Build the report in the format of the backend: `IncomingReport` without the user
   (backend/models/gateway_submission.py).
4. Hand it over with the token of the user, and give the app the answer of the backend as it is.

The user is checked by the backend, the gateway only passes the token on.
"""

import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response

from .backend import BackendTimeout, BackendUnreachable
from .config import MAX_PHOTO_BYTES, MAX_TEXT_CHARS
from .photos import NotAnImage, UnsupportedImage, detect_image

log = logging.getLogger("gateway.app")

CONNECTOR = "gateway-app"

router = APIRouter()


@router.post(
    "/v1/reports",
    summary="Send a report from the app",
    description=(
        "The request of the app as the backend defines it (backend/api/reports.py). "
        "The answer is the one of the backend: "
        "the sanitized report with classification, authority and draft, or status blocked or rejected."
    ),
)
def create_report(
    request: Request,
    client_report_id: str = Form(..., min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$"),
    lat: float = Form(..., ge=-90, le=90),
    lon: float = Form(..., ge=-180, le=180),
    text: str | None = Form(None, max_length=MAX_TEXT_CHARS),
    accuracy_m: float | None = Form(None, ge=0),
    country_code: str | None = Form(None, pattern=r"^[A-Za-z]{2}$"),
    state: str | None = Form(None, max_length=120),
    municipality: str | None = Form(None, max_length=120),
    district: str | None = Form(None, max_length=120),
    postal_code: str | None = Form(None, max_length=20),
    street: str | None = Form(None, max_length=160),
    house_number: str | None = Form(None, max_length=20),
    photo: UploadFile | None = File(None),
    authorization: str | None = Header(None),
) -> Response:
    if not authorization or not authorization.startswith("Bearer "):
        # Without a token the backend would refuse anyway, so nothing is stored. The app signs in again on 401.
        raise HTTPException(401, "not signed in", headers={"WWW-Authenticate": "Bearer"})

    text = text.strip() if text else None
    data = photo.file.read(MAX_PHOTO_BYTES + 1) if photo is not None else b""
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "the photo is too big")
    if not data and not text:
        raise HTTPException(422, "send a photo or a text")
    try:
        image = detect_image(data) if data else None
    except NotAnImage as error:
        raise HTTPException(422, str(error)) from None
    except UnsupportedImage as error:
        raise HTTPException(415, str(error)) from None

    store = request.app.state.raw_store
    report_id = uuid.uuid4().hex
    photos = []
    if image:
        mime_type, extension = image
        ref = f"raw/{report_id}/p1.{extension}"
        store.save(ref, data, mime_type)
        photos.append({"id": "p1", "mime_type": mime_type, "ref": ref})

    # The address as the phone found it, the user may have corrected it. Empty parts are dropped, as in the backend.
    parts = {
        "country_code": country_code, "state": state, "municipality": municipality, "district": district,
        "postal_code": postal_code, "street": street, "house_number": house_number,
    }  # fmt: skip
    parts = {name: value.strip() for name, value in parts.items() if value and value.strip()}
    submission = {
        "client_report_id": client_report_id,
        "id": report_id,
        "received_at": datetime.now(UTC).isoformat(),
        "source": {"type": "app", "connector": CONNECTOR, "raw_ref": f"raw/{report_id}/"},
        "location": {"lat": lat, "lon": lon, "accuracy_m": accuracy_m, "origin": "device_gps", "place": parts or None},
        "text": text,
        "photos": photos,
    }

    try:
        answer = request.app.state.backend.submit(submission, authorization)
    except BackendUnreachable:
        drop_photos(store, photos, report_id, "backend unreachable")
        raise HTTPException(503, "the service is not available, try again") from None
    except BackendTimeout:
        # The backend may still be working on it: its privacy layer deletes the raw photo, the gateway must not.
        log.error("backend timeout: report_id=%s", report_id)
        raise HTTPException(504, "the report takes too long, try again") from None

    if 400 <= answer.status_code < 500:
        # Not taken (token, rate limit, invalid): the raw photo still belongs to the gateway.
        drop_photos(store, photos, report_id, f"backend answered {answer.status_code}")
    elif answer.status_code == 200 and not is_answer_for(answer.content, report_id):
        # A retry of a report that exists already: the backend answered with the first one, this photo is not needed.
        drop_photos(store, photos, report_id, "retry of an existing report")
    elif answer.status_code >= 500:
        # The privacy layer keeps the raw data of a failed run for the operator, so the gateway leaves it too.
        log.error("backend error: report_id=%s status=%s", report_id, answer.status_code)

    headers = {"WWW-Authenticate": answer.www_authenticate} if answer.www_authenticate else None
    return Response(answer.content, status_code=answer.status_code, media_type=answer.content_type, headers=headers)


def is_answer_for(content: bytes, report_id: str) -> bool:
    """True if the answer of the backend is about this report (and not about the first one of a retry)."""
    try:
        return json.loads(content).get("id") == report_id
    except (ValueError, AttributeError):
        return True  # unknown answer: keep the photo, the backend may use it


def drop_photos(store, photos: list[dict], report_id: str, reason: str) -> None:
    """Delete the raw photos the backend did not take. Best effort: a failure is logged, the answer stands."""
    for photo in photos:
        try:
            store.delete(photo["ref"])
        except Exception as error:
            log.error("raw photo not deleted: report_id=%s reason=%s error=%s", report_id, reason, type(error).__name__)
