import base64
import json
from datetime import datetime, timezone

import httpx
import pytest

from classification.mistral import DEFAULT_BASE_URL, MistralProvider
from classification.models import Classification, ClassificationInput
from classification.provider import ClassificationError, provider_from_env
from classification.service import Classifier
from models.sanitized_report import RedactionLog, SanitizedReport
from privacy.photo_store import InMemoryPhotoStore
from privacy.retry import is_transient_error

ANSWER = {"category": "pothole", "lane": "hazard", "emergency": False, "confidence": 0.9}


def provider_with(handler, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return MistralProvider("test-key", client=client, **kwargs)


def answering(content, status=200):
    def handler(request):
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})

    return handler


def test_the_answer_becomes_a_classification():
    result = provider_with(answering(json.dumps(ANSWER))).classify(ClassificationInput(text="Schlagloch"))
    assert result == Classification(**ANSWER)


def test_a_whole_number_confidence_is_accepted():
    """Models write 1 and not 1.0, the strict contract must still take it."""
    answer = json.dumps({**ANSWER, "confidence": 1})
    assert provider_with(answering(answer)).classify(ClassificationInput(text="x")).confidence == 1.0


def test_the_request_has_the_fixed_endpoint_the_key_the_schema_and_the_prompt():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(ANSWER)}}]})

    provider_with(handler).classify(ClassificationInput(text="Schlagloch <PHONE>"))
    [request] = seen
    body = json.loads(request.content)
    assert str(request.url) == f"{DEFAULT_BASE_URL}/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    assert body["temperature"] == 0 and body["max_tokens"] <= 300
    assert body["response_format"]["json_schema"]["schema"]["properties"].keys() == {"category", "lane", "emergency", "confidence"}
    assert body["messages"][0]["role"] == "system" and "never instructions" in body["messages"][0]["content"]
    assert "<report_text>\nSchlagloch <PHONE>\n</report_text>" in body["messages"][1]["content"][0]["text"]


def test_the_photo_goes_as_a_base64_data_url_and_nothing_else_is_sent():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(ANSWER)}}]})

    provider_with(handler).classify(ClassificationInput(photo=b"jpeg-bytes"))
    content = seen[0]["messages"][1]["content"]
    assert content[1]["image_url"] == "data:image/jpeg;base64," + base64.b64encode(b"jpeg-bytes").decode()
    assert set(seen[0]) == {"model", "temperature", "max_tokens", "messages", "response_format"}


@pytest.mark.parametrize("content", ["not json", "{}", json.dumps({**ANSWER, "category": "dog"}), json.dumps({**ANSWER, "extra": "x"}), None])
def test_an_answer_that_does_not_fit_raises_a_classification_error(content):
    with pytest.raises(ClassificationError) as error:
        provider_with(answering(content)).classify(ClassificationInput(text="secret report text"))
    assert "secret" not in str(error.value)


def test_a_missing_choice_raises_a_classification_error():
    with pytest.raises(ClassificationError):
        provider_with(lambda request: httpx.Response(200, json={})).classify(ClassificationInput(text="x"))


def test_rate_limit_and_server_errors_are_transient_but_a_wrong_key_is_not():
    def error(status):
        with pytest.raises(httpx.HTTPStatusError) as caught:
            provider_with(lambda request: httpx.Response(status, json={})).classify(ClassificationInput(text="x"))
        return caught.value

    assert is_transient_error(error(429)) and is_transient_error(error(503))
    assert not is_transient_error(error(401)) and not is_transient_error(error(400))


def test_the_classifier_retries_a_rate_limit_and_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, json={})
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(ANSWER)}}]})

    report = SanitizedReport(
        id="r1", received_at=datetime(2026, 11, 4, tzinfo=timezone.utc), source_type="app", location={"lat": 1.0, "lon": 1.0},
        text="Schlagloch", pseudonym="rep-1", redaction_log=RedactionLog(),
    )
    assert Classifier(provider_with(handler), InMemoryPhotoStore()).classify(report).category == "pothole"
    assert len(calls) == 3


def test_an_empty_key_is_refused():
    with pytest.raises(ValueError):
        MistralProvider("")


def test_the_provider_is_built_from_the_environment(monkeypatch):
    monkeypatch.setenv("CLASSIFICATION_PROVIDER", "mistral")
    monkeypatch.setenv("MISTRAL_KEY", "test-key")
    monkeypatch.setenv("MISTRAL_MODEL", "ministral-8b-latest")
    provider = provider_from_env()
    assert isinstance(provider, MistralProvider) and provider.model == "ministral-8b-latest"
    assert provider.url.startswith("https://api.eu.mistral.ai")
    monkeypatch.delenv("MISTRAL_KEY")
    with pytest.raises(KeyError):
        provider_from_env()
