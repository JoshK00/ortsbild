from models.incoming_report import IncomingReport, Photo
from models.sanitized_report import RedactionEntry, RedactionLog, SanitizedReport


def assemble_report(
    report: IncomingReport,
    text: str | None,
    photos: list[Photo],
    pseudonym: str,
    redactions: list[RedactionEntry],
) -> SanitizedReport:
    """Build the sanitized report from the results of the steps.

    Raises if a step that had to run left no result, so a half-sanitized report never
    gets through (the caller fails closed).
    """
    if report.text and text is None:
        raise ValueError("the text step did not run")
    if len(photos) != len(report.photos):
        raise ValueError("the photo step did not run")
    return SanitizedReport(
        id=report.id,
        received_at=report.received_at,
        source_type=report.source.type,
        location=report.location,  # unchanged, it is the location of the defect
        text=text,
        photos=photos,
        pseudonym=pseudonym,
        redaction_log=RedactionLog(entries=redactions),
    )
