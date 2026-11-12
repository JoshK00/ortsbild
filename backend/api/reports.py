import io
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

import privacy.photos  # noqa: F401  (registers the HEIC reader of Pillow)
from auth.account import delete_account, photo_refs
from auth.sessions import AuthManager
from auth.tokens import AccessClaims
from cases import CASE_OPEN_DAYS, DUPLICATE_RADIUS_M, case_for, case_id_of, votes_of
from classification.models import CLARIFICATION_CATEGORIES, Classification
from models.incoming_report import IncomingReport
from models.sanitized_report import RedactionLog, SanitizedReport
from privacy.photo_store import PhotoStore
from privacy.pseudonyms import PseudonymStore
from privacy.detectors import TextDetector
from privacy.report_status import ReportRecord, ReportStatusStore
from drafting.service import strip_facts_block
from privacy.text import sanitize_text

logger = logging.getLogger("ortsbild.api")

MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = 5000
MAX_ANSWER_CHARS = 500  # the description of the problem that the user types after the question
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
    `followup_graph` runs the rest of it (research, draft) after the user picked a category. `answer_graph` runs the
    classification again, then the rest, after the user described the problem in words. `text_detectors` are the ones of
    the privacy layer, the description passes them before anything else happens to it.
    """

    graph: object
    photo_store: PhotoStore
    status_store: ReportStatusStore
    pseudonym_store: PseudonymStore
    auth: AuthManager
    followup_graph: object | None = None
    answer_graph: object | None = None
    text_detectors: list[TextDetector] | None = None


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


def report_payload(record: ReportRecord, case: dict | None = None) -> dict:
    """What the app gets for a report: sanitized (with the result), blocked, rejected or still processing.

    `status` is the outcome of the privacy layer. `classification` is the object of the classification, or null
    if it does not exist (yet). A blocked report gets no reason (it is in the log and the status table).
    A rejected one gets a short code. `case` says whether the report is a duplicate and how many votes its case has
    (see `case_info`), null while the report has no category. `approved` says whether the user released the report (it is
    visible in the dashboard then).
    """
    empty = {
        "id": record.report_id, "report": None, "photo_urls": [], "classification": None, "research": None, "draft": None,
        "clarification": None, "case": None, "approved": False,
    }
    if record.status in ("sanitized", "classified", "needs_input", "researched", "drafted") and record.sanitized is not None:
        photos = record.sanitized.get("photos", [])
        urls = [f"/v1/reports/{record.report_id}/photos/{photo['id']}" for photo in photos]
        return {
            "id": record.report_id, "status": "sanitized", "report": record.sanitized,
            "photo_urls": urls, "classification": record.classification, "research": record.research, "draft": clean_draft(record.draft),
            "clarification": clarification_of(record), "case": case,
            "approved": record.approved_at is not None,
        }
    if record.status == "blocked_privacy":
        return {**empty, "status": "blocked"}
    if record.status == "rejected":
        return {**empty, "status": "rejected", "reason": record.block_reason}
    return {**empty, "status": "processing"}


def clean_draft(draft: dict | None) -> dict | None:
    """The draft without the facts block that drafts of the first versions carry (see `strip_facts_block`)."""
    if not draft or not isinstance(draft.get("body"), str):
        return draft
    return {**draft, "body": strip_facts_block(draft["body"])}


def clarification_of(record: ReportRecord) -> dict | None:
    """The open question for the user, or None. `reason` says why the picture could not be assigned, `options` is what can be picked."""
    if record.status != "needs_input":
        return None
    unknown = (record.classification or {}).get("category") == "other"
    return {"reason": "no_defect" if unknown else "unclear", "options": list(CLARIFICATION_CATEGORIES)}


def case_info(services: Services, record: ReportRecord) -> dict | None:
    """Is this report a duplicate, and how many votes has its case? None while the report has no category or no position.

    A vote is a RELEASED report (the dashboard shows only those). The report itself is counted even before the user releases it,
    so the number is what the case will have after the release. Only the counts, the time of the first report and the public id
    of the case leave here, nothing of another user's report. The reports of everybody count, so the user sees "this was
    reported before" even when somebody else did it.
    """
    category = (record.classification or {}).get("category")
    location = ((record.sanitized or {}).get("location")) or {}
    if category is None or not isinstance(location.get("lat"), (int, float)) or not isinstance(location.get("lon"), (int, float)):
        return None
    try:
        # twice the open time: the anchor of a case may be older than the report by up to that
        since = datetime.now(timezone.utc) - timedelta(days=2 * CASE_OPEN_DAYS)
        entries = services.status_store.list_nearby(category, location["lat"], location["lon"], 2 * DUPLICATE_RADIUS_M, since)
        entries = [entry for entry in entries if entry[0].approved_at is not None or entry[0].report_id == record.report_id]
        case = case_for(entries, record)
    except Exception as error:  # the answer to the user must not fail because of the duplicate check
        logger.error("duplicate check failed: report_id=%s error=%s", record.report_id, type(error).__name__)
        return None
    if not case:
        return None
    return {
        "votes": votes_of(case),
        "is_duplicate": case[0][0].report_id != record.report_id,
        "first_reported_at": case[0][1].isoformat(),
        "case_id": case_id_of(case[0][0].report_id),  # the id the dashboard knows, to open the case there
    }


def owned_record(services: Services, report_id: str, user: AccessClaims) -> ReportRecord:
    """The report if it belongs to the user, else 404. The same answer for a foreign report, so ids cannot be probed."""
    record = services.status_store.get(report_id)
    if record is None or record.user_key != user.user_key:
        raise HTTPException(404, "no such report")
    return record


def payload_for(services: Services, record: ReportRecord) -> dict:
    """What the app gets for a report, with the duplicate information of its case (see `report_payload`)."""
    return report_payload(record, case_info(services, record))


def check_rate_limit(services: Services, user: AccessClaims, reports_per_hour: int) -> None:
    """429 if the user sent `reports_per_hour` reports or more within the last hour. Used by every way a report comes in."""
    if services.status_store.count_recent(user.user_key, RATE_WINDOW_SECONDS) >= reports_per_hour:
        raise HTTPException(429, "too many reports, try again later")


class AnswerBody(BaseModel):
    """The answer to the question what the picture shows: one of the categories, or the problem in the user's own words.

    Exactly one of them. The words can hold personal data, so they are sanitized first (see `answer_question`).
    """

    model_config = ConfigDict(extra="forbid")

    category: Literal[CLARIFICATION_CATEGORIES] | None = None  # type: ignore[valid-type]
    text: str | None = Field(default=None, min_length=1, max_length=MAX_ANSWER_CHARS)

    @model_validator(mode="after")
    def exactly_one(self) -> "AnswerBody":
        if (self.category is None) == (self.text is None):
            raise ValueError("send a category or a text, not both and not none")
        if self.text is not None and not self.text.strip():
            raise ValueError("the text is empty")
        return self


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
        return owned_record(get_services(), report_id, user)

    def payload_of(record: ReportRecord) -> dict:
        return payload_for(get_services(), record)

    @router.post("/reports")
    def create_report(
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
        user: AccessClaims = Depends(current_user),
    ) -> JSONResponse:
        """Take a photo and/or a text with the location, run it through the privacy layer.

        `client_report_id` is made up by the app (a UUID) and makes a retry safe: the same id from the
        same user returns the first result and creates nothing new.
        Returns the sanitized report, or status "blocked" / "rejected" if the privacy layer stopped it.
        """
        services = get_services()
        check_rate_limit(services, user, reports_per_hour)
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
            return JSONResponse(payload_of(own_report(owner_of_id, user)))

        photos = []
        if image:
            mime_type, extension = image
            raw_ref = f"raw/{report_id}/p1.{extension}"
            services.photo_store.save(raw_ref, data, mime_type)
            photos.append({"id": "p1", "mime_type": mime_type, "ref": raw_ref})

        # The address as the phone found it, the user may have corrected it. Empty parts are dropped.
        parts = {
            "country_code": country_code, "state": state, "municipality": municipality, "district": district,
            "postal_code": postal_code, "street": street, "house_number": house_number,
        }
        parts = {name: value.strip() for name, value in parts.items() if value and value.strip()}
        try:
            report = IncomingReport(
                id=report_id,
                received_at=datetime.now(timezone.utc),
                source={"type": "app", "connector": "app-api", "raw_ref": f"raw/{report_id}/"},
                location={"lat": lat, "lon": lon, "accuracy_m": accuracy_m, "origin": "device_gps", "place": parts or None},
                text=text,
                photos=photos,
                user={"identifier": user.user_key, "identifier_type": "user_key"},
            )
        except ValidationError:
            raise HTTPException(422, "the report is not valid")

        services.graph.invoke({"report": report})
        return JSONResponse(payload_of(own_report(report_id, user)))

    @router.get("/reports/{report_id}")
    def get_report(report_id: str = Path(pattern=r"^[0-9a-f]{32}$"), user: AccessClaims = Depends(current_user)) -> JSONResponse:
        """The status and, when it is ready, the sanitized result of one of your reports."""
        return JSONResponse(payload_of(own_report(report_id, user)))

    @router.post("/reports/{report_id}/approve")
    def approve_report(report_id: str = Path(pattern=r"^[0-9a-f]{32}$"), user: AccessClaims = Depends(current_user)) -> JSONResponse:
        """The user releases the report: it is visible in the dashboard from now on and counts as a vote of its case.

        The dashboard replaces the letters to the authorities (docs/documentation.md, 2026-11-10). Releasing twice is fine. A report
        that has no category yet (still processing, waiting for the answer to a question, blocked or rejected) gets 409.
        """
        own_report(report_id, user)  # 404 for a foreign report
        if not get_services().status_store.approve(report_id):
            raise HTTPException(409, "the report cannot be released yet")
        return JSONResponse(payload_of(own_report(report_id, user)))

    @router.delete("/reports/{report_id}", status_code=204)
    def delete_report(report_id: str = Path(pattern=r"^[0-9a-f]{32}$"), user: AccessClaims = Depends(current_user)) -> Response:
        """The user deletes the report for good: its photo files first, then the report itself (text, place, draft, release).

        It works at any time, also after the release (the dashboard then no longer lists it, its answer may be 30 seconds old).
        A file that cannot be deleted gives 503 and the report stays, so the user is never told it is gone when it is not.
        Another user's or an unknown report gets 404. Deleting twice gets 404 the second time, the app counts that as gone.
        """
        services = get_services()
        record = own_report(report_id, user)
        for ref in photo_refs(record):
            try:
                services.photo_store.delete(ref)
            except Exception as error:
                if is_not_found(error):
                    continue
                logger.error("report not deleted, photo stays: report_id=%s error=%s", report_id, type(error).__name__)
                raise HTTPException(503, "the report could not be deleted, try again") from None
        services.status_store.delete_report(report_id, user.user_key)
        return Response(status_code=204)

    @router.delete("/reports/{report_id}/photo")
    def delete_photo(report_id: str = Path(pattern=r"^[0-9a-f]{32}$"), user: AccessClaims = Depends(current_user)) -> JSONResponse:
        """The user removes the photo of the report, for good: the cleaned file is deleted (and the raw one, if it is still there), the report stays without it.

        This is the last safety net of the privacy layer. The user looks at the cleaned photo before releasing the report, and if a
        face or a plate is still visible, this removes it. It works at any time, also after the release (the dashboard then
        shows the placeholder). Doing it twice is fine.
        A file that cannot be deleted gives 503 and the photo stays in the report, so the user knows it is not gone.
        """
        services = get_services()
        record = own_report(report_id, user)
        for ref in photo_refs(record):
            try:
                services.photo_store.delete(ref)
            except Exception as error:
                if is_not_found(error):
                    continue
                logger.error("photo not deleted: report_id=%s error=%s", report_id, type(error).__name__)
                raise HTTPException(503, "the photo could not be deleted, try again") from None
        if record.sanitized is not None and record.sanitized.get("photos"):
            services.status_store.save_sanitized(report_id, {**record.sanitized, "photos": []})
        return JSONResponse(payload_of(own_report(report_id, user)))

    @router.post("/reports/{report_id}/answer")
    def answer_question(
        body: AnswerBody, report_id: str = Path(pattern=r"^[0-9a-f]{32}$"), user: AccessClaims = Depends(current_user)
    ) -> JSONResponse:
        """The user says what the problem is, after the question "what is this about?".

        - A category: it is the user's word and counts as sure (confidence 1), the lane and the emergency flag stay what
          the model found. The research and the draft follow.
        - Words: they are sanitized with the detectors of the privacy layer **first**, the raw words are never stored, logged
          or sent on. If they cannot be checked they are dropped (503) and the question stays open. Then the classification
          runs again with the description, and the question can come again if the picture is still unclear.

        A report takes `MAX_ANSWERS` answers. An answer to a report without an open question, a second one at the same
        moment, or one beyond the limit gets 409.
        """
        services = get_services()
        record = own_report(report_id, user)
        if record.status != "needs_input" or record.sanitized is None or record.classification is None:
            raise HTTPException(409, "no question can be answered for this report")
        sanitized = SanitizedReport.model_validate_json(json.dumps(record.sanitized))

        if body.text is not None:
            try:
                clean, entries = sanitize_text(body.text.strip(), services.text_detectors or [])
            except Exception as error:  # fail closed: words that cannot be checked are not used
                logger.error("answer text blocked: report_id=%s error=%s", report_id, type(error).__name__)
                raise HTTPException(503, "the answer could not be checked, try again later") from None
            if not services.status_store.start_answer(report_id):
                raise HTTPException(409, "no question can be answered for this report")
            described = sanitized.model_copy(update={
                "text": f"{sanitized.text}\n{clean}" if sanitized.text else clean,
                "redaction_log": RedactionLog(entries=[*sanitized.redaction_log.entries, *entries]),
            })
            services.status_store.save_sanitized(report_id, described.model_dump(mode="json"))
            services.answer_graph.invoke({"sanitized_report": described})
        else:
            if not services.status_store.start_answer(report_id):
                raise HTTPException(409, "no question can be answered for this report")
            asked = Classification.model_validate_json(json.dumps(record.classification))
            chosen = Classification(category=body.category, lane=asked.lane, emergency=asked.emergency, confidence=1.0)
            services.status_store.save_classification(report_id, chosen.model_dump(mode="json"))
            services.followup_graph.invoke({"sanitized_report": sanitized, "classification": chosen})
        return JSONResponse(payload_of(own_report(report_id, user)))

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
