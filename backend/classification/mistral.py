import base64
import json

import httpx
from pydantic import ValidationError

from classification.models import Classification, ClassificationInput
from classification.prompt import SYSTEM_PROMPT, user_message
from classification.provider import ClassificationError

# The EU endpoint of Mistral. It is fixed in the server configuration (MISTRAL_BASE_URL), never taken from a request.
DEFAULT_BASE_URL = "https://api.eu.mistral.ai"
DEFAULT_MODEL = "mistral-small-latest"
TIMEOUT_SECONDS = 30.0
MAX_ANSWER_TOKENS = 200  # the answer is a small object, a longer one is a sign that something is wrong


class MistralProvider:
    """Classifies with a vision model of Mistral: one chat call, the answer is forced into the schema of `Classification`.

    Network and server errors (including 429 and 5xx) are raised as they are, the caller retries them.
    An answer that does not fit the schema raises `ClassificationError`. Neither ever contains the report text or the key.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL, client: httpx.Client | None = None) -> None:
        if not api_key:
            raise ValueError("the Mistral key is empty")
        self.model = model
        self.url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def classify(self, data: ClassificationInput) -> Classification:
        response = self._client.post(self.url, headers=self._headers, json=self._request(data))
        response.raise_for_status()
        try:
            content = response.json()["choices"][0]["message"]["content"]
            return Classification.model_validate_json(content)
        except (KeyError, IndexError, TypeError, ValueError, ValidationError):
            # The type only: the answer could repeat parts of the report
            raise ClassificationError("the answer does not fit the schema") from None

    def _request(self, data: ClassificationInput) -> dict:
        content: list[dict] = [{"type": "text", "text": user_message(data)}]
        if data.photo:
            encoded = base64.b64encode(data.photo).decode()
            content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{encoded}"})
        return {
            "model": self.model,
            "temperature": 0,
            "max_tokens": MAX_ANSWER_TOKENS,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "classification", "schema": Classification.model_json_schema(), "strict": True},
            },
        }
