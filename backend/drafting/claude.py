import logging

import anthropic
from pydantic import ValidationError

from drafting.models import DraftContent, DraftInput
from drafting.prompt import SYSTEM_PROMPT, user_message
from drafting.provider import DraftError

logger = logging.getLogger("ortsbild.drafting")

# The model is a choice of cost against quality, it is set by ANTHROPIC_DRAFT_MODEL
DEFAULT_MODEL = "claude-haiku-5-5"
TIMEOUT_SECONDS = 60.0
MAX_ANSWER_TOKENS = 2048

SCHEMA = {
    "type": "object",
    "properties": {"subject": {"type": "string"}, "body": {"type": "string"}, "summary_de": {"type": "string"}},
    "required": ["subject", "body", "summary_de"],
    "additionalProperties": False,
}


class ClaudeDraftProvider:
    """Writes the draft with a Claude model: one call without a photo, the answer is forced into the schema, effort low.

    The model never gets the address or the coordinates and never sees the photo. A network, rate limit or server error
    is raised as it is, the caller retries it. A refusal or an answer that does not fit raises `DraftError`.
    TODO: The model could look at the cleaned photo too and describe what it shows. Today the description rests on the text
    of the citizen and the category.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, client: anthropic.Anthropic | None = None) -> None:
        if not api_key and client is None:
            raise ValueError("the Anthropic key is empty")
        self.model = model
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=TIMEOUT_SECONDS)

    def draft(self, data: DraftInput) -> DraftContent:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_ANSWER_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message(data)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        usage = getattr(response, "usage", None)  # only the numbers, never the content
        logger.info("claude draft: model=%s input_tokens=%s output_tokens=%s", self.model, getattr(usage, "input_tokens", "?"), getattr(usage, "output_tokens", "?"))
        if response.stop_reason in ("refusal", "max_tokens"):
            raise DraftError(f"no usable answer: {response.stop_reason}")
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            return DraftContent.model_validate_json(text)
        except (ValidationError, ValueError):
            # The type only: the answer could repeat parts of the report
            raise DraftError("the answer does not fit the schema") from None
