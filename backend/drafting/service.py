import logging

from classification.models import Classification
from drafting.models import Draft, DraftInput
from drafting.provider import DraftProvider
from models.sanitized_report import SanitizedReport
from privacy.retry import retry
from research.models import ResearchResult

logger = logging.getLogger("ortsbild.drafting")

DEFAULT_LANGUAGE = "de"  # the language of the app, used when no authority and no language was found


# The lines that older drafts carry under the letter (location, map link, attachment). New drafts do not get them any more
# (decision of the team 2026-11-11: the address and the photo are shown by the dashboard), old ones are cleaned when they are read.
_LEGACY_FACT_PREFIXES = ("Standort / Location:", "https://www.openstreetmap.org/?mlat=", "Anhang / Attachment:")


def strip_facts_block(body: str) -> str:
    """The letter without the lines of the old facts block (location, map link, attachment) and without the blank lines it leaves."""
    lines = [line for line in body.split("\n") if not line.startswith(_LEGACY_FACT_PREFIXES)]
    return "\n".join(lines).rstrip()


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
                subject=content.subject.strip(), body=content.body.strip(),
                summary_de=content.summary_de.strip(), language=language,
                authority=research.authority if research else None, contact=research.channel if research else None,
            )
        except Exception as error:
            # The type only: a message could repeat what the model wrote
            logger.error("draft failed: report_id=%s error=%s", report.id, type(error).__name__)
            return None
