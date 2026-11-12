import logging

from classification.models import Classification
from models.sanitized_report import SanitizedReport
from privacy.retry import retry
from research.models import ResearchQuery, ResearchResult
from research.provider import ResearchProvider
from research.registry import RegistryKey, RegistryStore

logger = logging.getLogger("ortsbild.research")


class Researcher:
    """Finds the responsible authority: the memory first, then the web research.

    It never raises for a failing provider: a report without an authority is still a valid report, the user
    adds the recipient by hand. It only ever sees the place and the category of a sanitized report.
    """

    def __init__(self, registry: RegistryStore, provider: ResearchProvider | None) -> None:
        self.registry = registry
        self.provider = provider

    def query_for(self, report: SanitizedReport, classification: Classification, exclude: list[str] | None = None) -> ResearchQuery | None:
        """What the research needs, or None if there is nothing to research (no town, or a report that is no defect)."""
        place = report.location.place
        if place is None or not place.municipality or classification.category == "other":
            return None
        return ResearchQuery(
            category=classification.category, country_code=place.country_code,
            municipality=place.municipality, district=place.district, exclude=exclude or [],
        )

    def research(self, report: SanitizedReport, classification: Classification, exclude: list[str] | None = None) -> ResearchResult | None:
        query = self.query_for(report, classification, exclude)
        if query is None:
            return None
        key = RegistryKey.of(query.country_code, query.municipality, query.category)
        try:
            entry = self.registry.find(key)
            if entry and entry.is_fresh() and entry.result.authority not in query.exclude:
                return entry.result.model_copy(update={"origin": "registry"})
            if self.provider is None:
                return None
            result = retry(lambda: self.provider.research(query), "research", attempts=2)
            if result is None or result.authority in query.exclude:
                return None
            self.registry.save(key, result)
            return result
        except Exception as error:
            # The type only: a message could repeat what the search returned
            logger.error("research failed: report_id=%s error=%s", report.id, type(error).__name__)
            return None
