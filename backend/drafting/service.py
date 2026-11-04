import logging

from classification.models import Classification
from drafting.models import Draft, DraftInput
from drafting.provider import DraftProvider
from models.incoming_report import Place
from models.sanitized_report import SanitizedReport
from privacy.retry import retry
from research.models import ResearchResult

logger = logging.getLogger("ortsbild.drafting")

DEFAULT_LANGUAGE = "de"  # the language of the app, used when no authority and no language was found


def address_line(place: Place | None) -> str:
    """The address as one line, from the parts the phone found. Empty if the phone found nothing."""
    if place is None:
        return ""
    street = " ".join(part for part in (place.street, place.house_number) if part)
    town = " ".join(part for part in (place.postal_code, place.municipality) if part)
    return ", ".join(part for part in (street, town, (place.country_code or "").upper()) if part)


def facts_block(report: SanitizedReport) -> str:
    """The location and the attachment, written by our code and not by the model, so they are exactly what the phone found.

    The labels have both languages, so the block fits a letter in any language.
    """
    lat, lon = report.location.lat, report.location.lon
    address = address_line(report.location.place)
    lines = [f"Standort / Location: {address + ' | ' if address else ''}{lat:.5f}, {lon:.5f}"]
    lines.append(f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}#map=19/{lat:.5f}/{lon:.5f}")
    if report.photos:
        lines.append("Anhang / Attachment: Foto / photo")
    return "\n".join(lines)


class Drafter:
    """Writes the message for the user to approve: the text of the model plus the facts of our code.

    It never raises for a failing provider: a report without a draft is still a valid report. It sees the sanitized report,
    the classification and the authority, never a raw report.
    """

    def __init__(self, provider: DraftProvider) -> None:
        self.provider = provider

    def draft(self, report: SanitizedReport, classification: Classification, research: ResearchResult | None) -> Draft | None:
        if classification.category == "other":
            return None  # no defect, nothing to report
        language = (research.language if research and research.language else DEFAULT_LANGUAGE).lower()
        try:
            data = DraftInput(
                category=classification.category, lane=classification.lane, text=report.text,
                authority=research.authority if research else None, language=language,
            )
            content = retry(lambda: self.provider.draft(data), "draft", attempts=2)
            return Draft(
                subject=content.subject.strip(), body=f"{content.body.strip()}\n\n{facts_block(report)}",
                summary_de=content.summary_de.strip(), language=language,
                authority=research.authority if research else None, contact=research.channel if research else None,
            )
        except Exception as error:
            # The type only: a message could repeat what the model wrote
            logger.error("draft failed: report_id=%s error=%s", report.id, type(error).__name__)
            return None
