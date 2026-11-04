import base64
import logging

import anthropic
from pydantic import ValidationError

from classification.models import CATEGORIES, Classification, ClassificationInput
from classification.prompt import SYSTEM_PROMPT, user_message
from classification.provider import ClassificationError

logger = logging.getLogger("ortsbild.classification")

# The model is a choice of cost against quality, it is set by ANTHROPIC_CLASSIFICATION_MODEL.
# Haiku: about a hundredth of a cent per report and as good as the larger tiers on our evaluation set (docs/documentation.md, 2026-11-04).
DEFAULT_MODEL = "claude-haiku-5-5"
TIMEOUT_SECONDS = 30.0
MAX_ANSWER_TOKENS = 1024  # the answer is a small object, the rest is room for the model to think

# The schema of `Classification` as the API wants it: plain types only. The limits (confidence between 0 and 1) are
# checked by our own model afterwards, so a wrong answer is caught either way.
SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "lane": {"type": "string", "enum": ["hazard", "nuisance"]},
        "emergency": {"type": "boolean"},
        "confidence": {"type": "number"},
    },
    "required": ["category", "lane", "emergency", "confidence"],
    "additionalProperties": False,
}


class ClaudeProvider:
    """Classifies with a Claude model: one call, the answer is forced into the schema, thinking kept short (effort low).

    A network, rate limit or server error is raised as it is, the caller retries it. A refusal or an answer that does
    not fit raises `ClassificationError`. Neither ever contains the report text or the key.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, client: anthropic.Anthropic | None = None) -> None:
        if not api_key and client is None:
            raise ValueError("the Anthropic key is empty")
        self.model = model
        # No retries inside the SDK: our own retry logs the type of the error and counts the tries once
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=TIMEOUT_SECONDS)

    def classify(self, data: ClassificationInput) -> Classification:
        content: list[dict] = []
        if data.photo:
            encoded = base64.standard_b64encode(data.photo).decode()
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": encoded}})
        content.append({"type": "text", "text": user_message(data)})
        response = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_ANSWER_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        usage = getattr(response, "usage", None)  # only the numbers, never the content: they show what a report costs
        logger.info("claude classification: model=%s input_tokens=%s output_tokens=%s", self.model, getattr(usage, "input_tokens", "?"), getattr(usage, "output_tokens", "?"))
        if response.stop_reason in ("refusal", "max_tokens"):
            raise ClassificationError(f"no usable answer: {response.stop_reason}")
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            return Classification.model_validate_json(text)
        except (ValidationError, ValueError):
            # The type only: the answer could repeat parts of the report
            raise ClassificationError("the answer does not fit the schema") from None
