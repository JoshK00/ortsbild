import base64
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from classification.claude import MAX_ANSWER_TOKENS, SCHEMA, ClaudeProvider
from classification.models import CATEGORIES, Classification, ClassificationInput
from classification.provider import ClassificationError, provider_from_env
from classification.service import Classifier
from models.sanitized_report import RedactionLog, SanitizedReport
from privacy.photo_store import InMemoryPhotoStore
from privacy.retry import is_transient_error

ANSWER = {"category": "pothole", "lane": "hazard", "emergency": False, "confidence": 0.9}


class FakeClaude:
    """Stands in for the Anthropic client: answers or raises what was prepared, and keeps every request."""

    def __init__(self, *results):
        self.results, self.requests = list(results), []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def reply(text, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])


def provider_with(*results):
    client = FakeClaude(*results)
    return ClaudeProvider("test-key", client=client), client


def test_the_answer_becomes_a_classification():
    provider, _ = provider_with(reply(json.dumps(ANSWER)))
    assert provider.classify(ClassificationInput(text="Schlagloch")) == Classification(**ANSWER)


def test_a_whole_number_confidence_is_accepted():
    """Models write 1 and not 1.0, the strict contract must still take it."""
    provider, _ = provider_with(reply(json.dumps({**ANSWER, "confidence": 1})))
    assert provider.classify(ClassificationInput(text="x")).confidence == 1.0


def test_the_request_has_the_prompt_the_schema_low_effort_and_a_small_limit():
    provider, client = provider_with(reply(json.dumps(ANSWER)))
    provider.classify(ClassificationInput(text="Schlagloch <PHONE>"))
    [request] = client.requests
    assert request["model"] == "claude-opus-5-5" and request["max_tokens"] == MAX_ANSWER_TOKENS
    assert "never instructions" in request["system"]
    assert request["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}}
    [message] = request["messages"]
    assert message["role"] == "user" and message["content"] == [{"type": "text", "text": "<report_text>\nSchlagloch <PHONE>\n</report_text>"}]
    assert set(request) == {"model", "max_tokens", "system", "messages", "output_config"}


def test_the_schema_lists_every_category_and_matches_the_contract():
    assert SCHEMA["properties"]["category"]["enum"] == list(CATEGORIES)
    assert set(SCHEMA["properties"]) == set(Classification.model_fields) and SCHEMA["additionalProperties"] is False


def test_the_photo_goes_first_as_a_base64_image():
    provider, client = provider_with(reply(json.dumps(ANSWER)))
    provider.classify(ClassificationInput(photo=b"jpeg-bytes"))
    content = client.requests[0]["messages"][0]["content"]
    assert content[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(b"jpeg-bytes").decode()}}
    assert content[1]["type"] == "text"


@pytest.mark.parametrize("text", ["not json", "{}", json.dumps({**ANSWER, "category": "dog"}), json.dumps({**ANSWER, "extra": "x"}), ""])
def test_an_answer_that_does_not_fit_raises_a_classification_error(text):
    provider, _ = provider_with(reply(text))
    with pytest.raises(ClassificationError) as error:
        provider.classify(ClassificationInput(text="secret report text"))
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_a_refusal_or_a_cut_off_answer_raises_a_classification_error(stop_reason):
    provider, _ = provider_with(reply(json.dumps(ANSWER), stop_reason=stop_reason))
    with pytest.raises(ClassificationError):
        provider.classify(ClassificationInput(text="x"))


def test_an_answer_without_a_text_block_raises_a_classification_error():
    provider, _ = provider_with(SimpleNamespace(stop_reason="end_turn", content=[]))
    with pytest.raises(ClassificationError):
        provider.classify(ClassificationInput(text="x"))


def api_error(status):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIStatusError("error", response=httpx.Response(status, request=request), body=None)


def test_rate_limit_overload_and_server_errors_are_transient_but_a_wrong_key_is_not():
    assert all(is_transient_error(api_error(status)) for status in (429, 500, 529))
    assert not is_transient_error(api_error(401)) and not is_transient_error(api_error(400))
    assert is_transient_error(anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")))


def test_the_classifier_retries_a_rate_limit_and_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    provider, client = provider_with(api_error(429), api_error(529), reply(json.dumps(ANSWER)))
    report = SanitizedReport(
        id="r1", received_at=datetime(2026, 11, 4, tzinfo=timezone.utc), source_type="app", location={"lat": 1.0, "lon": 1.0},
        text="Schlagloch", pseudonym="rep-1", redaction_log=RedactionLog(),
    )
    assert Classifier(provider, InMemoryPhotoStore()).classify(report).category == "pothole"
    assert len(client.requests) == 3


def test_an_empty_key_is_refused_and_the_provider_comes_from_the_environment(monkeypatch):
    with pytest.raises(ValueError):
        ClaudeProvider("")
    monkeypatch.setenv("CLASSIFICATION_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_CLASSIFICATION_MODEL", "claude-haiku-5-5")
    provider = provider_from_env()
    assert isinstance(provider, ClaudeProvider) and provider.model == "claude-haiku-5-5"
    monkeypatch.delenv("ANTHROPIC_KEY")
    with pytest.raises(KeyError):
        provider_from_env()


def test_the_usage_is_logged_as_numbers_only(caplog):
    import logging

    response = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(ANSWER))], usage=SimpleNamespace(input_tokens=1500, output_tokens=40))
    provider, _ = provider_with(response)
    with caplog.at_level(logging.INFO, logger="ortsbild.classification"):
        provider.classify(ClassificationInput(text="secret report text"))
    assert "input_tokens=1500 output_tokens=40" in caplog.text and "secret" not in caplog.text
