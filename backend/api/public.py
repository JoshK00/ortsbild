import logging
import re
import time
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import JSONResponse, Response

from api.geocode import Geocoder, GeocoderUnavailable, NominatimGeocoder
from api.reports import Services, clean_draft, is_not_found
from cases import case_id_of, group_into_cases, votes_of
from privacy.report_status import ReportRecord

logger = logging.getLogger("ortsbild.api")

MAX_REPORTS = 500  # read from the database, then grouped into cases
MAX_CASES = 200
SEARCHES_PER_MINUTE = 30  # all visitors together, the public geocoder is for light use
CACHE_SECONDS = 30
REPORTER_ID = re.compile(r"^usr-[0-9a-f]{12}$")


def key_prefixes_of(reporter_ids: list[str]) -> list[str]:
    """The user key prefixes that belong to the reporter ids of the allow list. Anything that is not a reporter id is dropped.

    The check is strict on purpose: an empty or short prefix would match every user.
    """
    return [entry.strip().removeprefix("usr-") for entry in reporter_ids if REPORTER_ID.match(entry.strip())]


def address_of(place: dict | None) -> str | None:
    """The address as one line, from the parts the phone found: "Hauptstraße 5, 48143 Münster"."""
    if not place:
        return None
    street = " ".join(part for part in (place.get("street"), place.get("house_number")) if part)
    town = " ".join(part for part in (place.get("postal_code"), place.get("municipality")) if part)
    return ", ".join(part for part in (street, town) if part) or None


def case_of(record: ReportRecord, created_at) -> dict | None:
    """One report as the dashboard gets it. A fixed list of fields: nothing else about a report leaves through this door.

    Never in it: the original photo, the user key, the real report id, the pseudonym.
    TODO: `status` is always "received". It becomes "in_progress" and "done" when authorities report back.
    """
    sanitized, classification = record.sanitized, record.classification
    if sanitized is None or classification is None:
        return None
    location = sanitized.get("location") or {}
    photos = sanitized.get("photos") or []
    research, draft = record.research or {}, clean_draft(record.draft) or {}
    case_id = case_id_of(record.report_id)
    return {
        "id": case_id,
        "category": classification.get("category"),
        "lane": classification.get("lane"),
        "status": "received",
        "created_at": created_at.isoformat(),
        "lat": location.get("lat"),
        "lon": location.get("lon"),
        "accuracy_m": location.get("accuracy_m"),
        "address": address_of(location.get("place")),
        "text": sanitized.get("text"),
        "photo_url": f"/v1/public/cases/{case_id}/photo" if photos else None,
        "authority": research.get("authority") or draft.get("authority"),
        "draft": {
            "subject": draft.get("subject"),
            "body": draft.get("body"),
            "summary_de": draft.get("summary_de"),
            "language": draft.get("language"),
            "contact": draft.get("contact"),
        } if draft else None,
    }


def case_of_group(group: list) -> tuple[dict, ReportRecord] | None:
    """One case (reports that belong together, the oldest first) as the dashboard gets it, and the report that holds its photo.

    The oldest report gives the text, the draft and the position, the age is the age of the oldest. `reports_count` is the number
    of votes. The photo is the first one that exists in the case.
    """
    first_record, first_time = group[0]
    case = case_of(first_record, first_time)
    if case is None:
        return None
    photo_record = next((record for record, _ in group if (record.sanitized or {}).get("photos")), None)
    case["photo_url"] = f"/v1/public/cases/{case['id']}/photo" if photo_record else None
    case["reports_count"] = votes_of(group)
    case["last_reported_at"] = group[-1][1].isoformat()
    return case, photo_record or first_record


def create_public_router(
    get_services: Callable[[], Services],
    reporter_ids: Callable[[], list[str]],
    clock: Callable[[], float] = time.monotonic,
    geocoder: Geocoder | None = None,
) -> APIRouter:
    """The dashboard endpoints. They need no login, so they show only the reports of the users on the allow list (the team's
    own test accounts, given by their reporter ids). Without an allow list there is nothing to see. The entry `*` lifts the
    list: every released report is shown. That is right only while nobody but the team can sign in to the app.

    The list is read from the database at most every `CACHE_SECONDS`, so a flood of requests does not reach the database.
    """
    router = APIRouter(prefix="/v1/public")
    geocoder = geocoder or NominatimGeocoder()
    searches: list[float] = []  # the times of the last minute
    cache: dict[str, tuple[float, list[tuple[dict, ReportRecord]]]] = {}

    def visible() -> list[tuple[dict, ReportRecord]]:
        cached = cache.get("cases")
        if cached is not None and clock() - cached[0] < CACHE_SECONDS:
            return cached[1]
        entries = [entry.strip() for entry in reporter_ids()]
        # "*" shows the released reports of every user: only for a server whose app is not public (the team's own accounts).
        prefixes = None if "*" in entries else key_prefixes_of(entries)
        found = get_services().status_store.list_visible(prefixes, MAX_REPORTS)
        cases = [pair for group in group_into_cases(found) if (pair := case_of_group(group)) is not None][:MAX_CASES]
        cache["cases"] = (clock(), cases)
        return cases

    @router.get("/cases")
    def list_cases() -> JSONResponse:
        """The reports of the allow list, newest first, as a fixed list of fields (see `case_of`)."""
        return JSONResponse({"cases": [case for case, _ in visible()]}, headers={"Cache-Control": "no-store"})

    @router.get("/search")
    def search_place(q: str = Query(min_length=3, max_length=100)) -> JSONResponse:
        """Places and addresses in Germany for the search field of the dashboard (see `api/geocode.py`). Nothing of the visitor is passed on."""
        now = clock()
        searches[:] = [moment for moment in searches if now - moment < 60]
        if len(searches) >= SEARCHES_PER_MINUTE:
            raise HTTPException(429, "too many searches, try again in a minute")
        searches.append(now)
        try:
            results = geocoder.search(q.strip())
        except GeocoderUnavailable:
            raise HTTPException(503, "the search is not available right now") from None
        return JSONResponse({"results": results}, headers={"Cache-Control": "no-store"})

    @router.get("/cases/{case_id}/photo")
    def get_case_photo(case_id: str = Path(pattern=r"^[0-9a-f]{16}$")) -> Response:
        """The cleaned photo of a visible report. Never the raw photo. Any other id is 404, so reports cannot be probed."""
        record = next((record for case, record in visible() if case["id"] == case_id), None)
        photos = (record.sanitized or {}).get("photos") if record else None
        if not photos:
            raise HTTPException(404, "no such photo")
        store = get_services().photo_store
        for extension, mime_type in (("jpg", "image/jpeg"), ("png", "image/png")):
            try:
                data = store.load(f"clean/{record.report_id}/{photos[0]['id']}.{extension}")
            except Exception as error:
                if is_not_found(error):
                    continue
                raise
            return Response(data, media_type=mime_type, headers={"Cache-Control": "public, max-age=300"})
        raise HTTPException(404, "no such photo")

    return router
