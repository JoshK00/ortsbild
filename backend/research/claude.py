import logging

import anthropic

from research.answer import result_from_text
from research.models import ResearchQuery, ResearchResult
from research.prompt import INSTRUCTIONS, user_message

logger = logging.getLogger("ortsbild.research")

# The model is a choice of cost against quality, it is set by ANTHROPIC_RESEARCH_MODEL
DEFAULT_MODEL = "claude-opus-5-5"
TIMEOUT_SECONDS = 120.0
MAX_ANSWER_TOKENS = 4096
MAX_SEARCHES = 4  # per research: every search costs money
MAX_CONTINUATIONS = 3  # a long search is paused by the server and has to be resumed


class ClaudeSearchProvider:
    """Researches with a Claude model and its web search tool, which runs on Anthropic's servers.

    The model answers in JSON and names its sources. Whether the pages really say so is checked afterwards by
    `research.verify.VerifiedProvider`, not here. Network, rate limit and server errors are raised as they are.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, client: anthropic.Anthropic | None = None) -> None:
        if not api_key and client is None:
            raise ValueError("the Anthropic key is empty")
        self.model = model
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=TIMEOUT_SECONDS)

    def research(self, query: ResearchQuery) -> ResearchResult | None:
        question = [{"role": "user", "content": user_message(query)}]
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCHES}]
        answer_blocks: list = []
        for _ in range(MAX_CONTINUATIONS + 1):
            messages = question + ([{"role": "assistant", "content": answer_blocks}] if answer_blocks else [])
            response = self._client.messages.create(
                model=self.model, max_tokens=MAX_ANSWER_TOKENS, system=INSTRUCTIONS, tools=tools, messages=messages,
                output_config={"effort": "medium"},
            )
            usage = getattr(response, "usage", None)  # only the numbers, never the content: they show what a research costs
            searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", "?")
            logger.info(
                "claude research: model=%s input_tokens=%s output_tokens=%s searches=%s",
                self.model, getattr(usage, "input_tokens", "?"), getattr(usage, "output_tokens", "?"), searches,
            )
            if response.stop_reason == "pause_turn":
                # The server stopped a long search: send what it said so far and it goes on from there
                answer_blocks += response.content
                continue
            if response.stop_reason == "refusal":
                return None
            return result_from_text("".join(block.text for block in response.content if block.type == "text"))
        return None  # still paused after the continuations, give up
