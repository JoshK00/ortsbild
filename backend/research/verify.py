import html
import logging
import re
import unicodedata
from typing import Protocol

from research.models import ResearchQuery, ResearchResult
from research.provider import ResearchProvider
from research.registry import normalize

logger = logging.getLogger("ortsbild.research")

MAX_SOURCES = 3  # pages read per answer
MIN_WORD_SHARE = 0.5  # how many of the words of the authority's name must stand on a page
UNVERIFIED_CONTACT_CONFIDENCE = 0.5


class PageFetcher(Protocol):
    def fetch(self, url: str) -> str | None: ...


def words_of(text: str) -> list[str]:
    """The words of a name that carry meaning: letters only, at least four of them, accents and case ignored."""
    return [w for w in re.split(r"[^a-z]+", normalize(unicodedata.normalize("NFKC", text))) if len(w) >= 4]


def verify_result(result: ResearchResult, fetcher: PageFetcher) -> ResearchResult | None:
    """Check an answer against the pages it names, and keep only what is really written there.

    - A page that cannot be read does not count as a source. No readable source: the answer is dropped.
    - The name of the authority must be on those pages (at least half of its words), else the answer is dropped.
    - The contact must be on them too (the email address, or the web address), else only the contact is dropped
      and the confidence falls. A contact that nobody can find on a page is how a made-up address looks.
    """
    pages = {}
    for url in result.sources[:MAX_SOURCES]:
        text = fetcher.fetch(url)
        if text is not None:
            pages[url] = html.unescape(text).lower()  # &uuml; and &#64; are read as the letters they stand for
    if not pages:
        return None
    everything = normalize(" ".join(pages.values()))

    words = words_of(result.authority)
    if not words or sum(1 for word in words if word in everything) / len(words) < MIN_WORD_SHARE:
        return None

    channel, confidence = result.channel, result.confidence
    if channel is not None:
        target = channel.target.lower()
        found = target in " ".join(pages.values()) or (channel.type != "email" and target in {url.lower() for url in pages})
        if not found:
            channel, confidence = None, min(confidence, UNVERIFIED_CONTACT_CONFIDENCE)
    return result.model_copy(update={"channel": channel, "sources": list(pages), "confidence": confidence})


class VerifiedProvider:
    """Wraps a research provider: whatever it answers is checked against the pages it names before anybody sees it."""

    def __init__(self, provider: ResearchProvider, fetcher: PageFetcher) -> None:
        self.provider, self.fetcher = provider, fetcher

    def research(self, query: ResearchQuery) -> ResearchResult | None:
        result = self.provider.research(query)
        if result is None:
            return None
        verified = verify_result(result, self.fetcher)
        if verified is None:
            logger.warning("research answer dropped, the pages do not support it")
        return verified
