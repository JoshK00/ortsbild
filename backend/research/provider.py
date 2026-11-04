import os
from typing import Protocol

from research.models import ResearchQuery, ResearchResult


class ResearchProvider(Protocol):
    """Whatever finds the responsible authority for a place and a category: an agent with a web search, or a stand-in.

    It returns a `ResearchResult` that carries its sources, or None if it found nothing it can support.
    Network errors are raised as they are, the caller retries them. A provider only sees a `ResearchQuery`.
    """

    def research(self, query: ResearchQuery) -> ResearchResult | None: ...


class ScriptedResearchProvider:
    """A stand-in with a fixed answer, for tests and for running the chain without a search provider.

    TODO: It is not an answer for a real place. It exists so that the whole chain can be tried before a search is paid for.
    """

    def __init__(self, result: ResearchResult | None) -> None:
        self.result = result
        self.queries: list[ResearchQuery] = []

    def research(self, query: ResearchQuery) -> ResearchResult | None:
        self.queries.append(query)
        return self.result


def provider_from_env() -> ResearchProvider | None:
    """The provider named in RESEARCH_PROVIDER. Default `none`: no web research, the user adds the recipient by hand.

    An unknown name stops the start of the server.
    """
    name = os.getenv("RESEARCH_PROVIDER", "none")
    if name == "none":
        return None
    if name == "anthropic":
        from research.claude import DEFAULT_MODEL, ClaudeSearchProvider
        from research.fetcher import SafeFetcher
        from research.verify import VerifiedProvider

        # Every answer is checked against the pages it names before it is used
        return VerifiedProvider(
            ClaudeSearchProvider(os.environ["ANTHROPIC_KEY"], os.getenv("ANTHROPIC_RESEARCH_MODEL", DEFAULT_MODEL)), SafeFetcher()
        )
    raise ValueError(f"unknown RESEARCH_PROVIDER: {name}")
