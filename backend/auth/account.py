import logging

from auth.sessions import AuthManager
from privacy.photo_store import PhotoStore
from privacy.pseudonyms import PseudonymStore
from privacy.report_status import ReportRecord, ReportStatusStore

logger = logging.getLogger("ortsbild.api")

# Where the files of a report can be. A blocked report has a clean photo but no sanitized result that points to it,
# so the paths are listed here and not only read from the report.
# TODO: One photo per report today (p1). Walk the photo ids when a report can have several.
FILE_REFS = ("raw/{id}/p1.jpg", "raw/{id}/p1.png", "raw/{id}/p1.heic", "clean/{id}/p1.jpg", "clean/{id}/p1.png")


def photo_refs(record: ReportRecord) -> list[str]:
    """Every file that can belong to a report, clean or raw."""
    refs = {pattern.format(id=record.report_id) for pattern in FILE_REFS}
    refs.update(photo["ref"] for photo in (record.sanitized or {}).get("photos", []))
    return sorted(refs)


def delete_account(
    user_key: str,
    status_store: ReportStatusStore,
    photo_store: PhotoStore,
    pseudonym_store: PseudonymStore,
    auth: AuthManager,
) -> None:
    """Delete everything we hold about a user: reports, their photos, the pseudonym and all sessions.

    A photo that cannot be deleted is logged with the report id and the rest goes on, so the user
    is not stuck half deleted.
    TODO: A cleanup job that finds files without a report row (the log lists the ids until then).
    """
    for record in status_store.delete_user(user_key):
        for ref in photo_refs(record):
            try:
                photo_store.delete(ref)
            except Exception as error:
                logger.error("account deletion: file not deleted: report_id=%s error=%s", record.report_id, type(error).__name__)
    pseudonym_store.delete(user_key, "user_key")
    auth.end_all_sessions(user_key)
