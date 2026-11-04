import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError

from classification.models import Classification
from models.incoming_report import Place
from models.sanitized_report import RedactionLog, SanitizedReport
from research.fetcher import SafeFetcher, is_public_address
from research.mistral import MAX_WEB_CONFIDENCE, MistralSearchProvider, read_answer, user_message
from research.models import Channel, ResearchQuery, ResearchResult
from research.postgres_registry import PostgresRegistryStore
from research.provider import ScriptedResearchProvider, provider_from_env
from research.registry import ENTRY_LIFETIME_DAYS, InMemoryRegistryStore, RegistryEntry, RegistryKey, normalize
from research.service import Researcher
from research.verify import VerifiedProvider, verify_result, words_of
from tests.test_storage_and_database import fake_connect

SOURCE = "https://www.muenchen.de/rathaus/kontakt"


def make_result(**changes):
    values = {"authority": "Baureferat Tiefbau", "channel": Channel(type="email", target="tiefbau@muenchen.de"), "language": "de", "sources": [SOURCE], "confidence": 0.7}
    return ResearchResult(**{**values, **changes})


def make_report(place="default"):
    place = Place(country_code="DE", municipality="München", district="Altstadt", street="Hauptstraße", house_number="12") if place == "default" else place
    return SanitizedReport(
        id="r1", received_at=datetime(2026, 11, 4, tzinfo=timezone.utc), source_type="app",
        location={"lat": 48.1, "lon": 11.5, "place": place}, text="Schlagloch", pseudonym="rep-1", redaction_log=RedactionLog(),
    )


def make_classification(**changes):
    return Classification(**{"category": "pothole", "lane": "hazard", "emergency": False, "confidence": 0.9, **changes})


# ---------------------------------------------------------------------------
# The contracts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("channel", [
    {"type": "email", "target": "not-an-address"},
    {"type": "email", "target": "https://example.org"},
    {"type": "web_form", "target": "http://insecure.example.org/form"},
    {"type": "web_form", "target": "not a url"},
    {"type": "phone", "target": "+49 89 1234"},
])
def test_an_invalid_channel_is_rejected(channel):
    with pytest.raises(ValidationError):
        Channel(**channel)


def test_valid_channels_are_accepted():
    assert Channel(type="email", target="tiefbau@muenchen.de")
    assert Channel(type="web_form", target="https://www.muenchen.de/form")


@pytest.mark.parametrize("change", [{"sources": []}, {"sources": ["http://insecure.example.org"]}, {"sources": ["not a url"]}, {"confidence": 1.5}, {"authority": ""}, {"extra": "x"}])
def test_a_result_needs_secure_sources_and_valid_values(change):
    with pytest.raises(ValidationError):
        make_result(**change)


def test_the_query_has_room_only_for_the_place_and_the_category():
    """Text, photo, pseudonym, coordinates and street cannot be handed to the research by mistake."""
    for extra in ({"text": "x"}, {"lat": 1.0}, {"pseudonym": "rep-1"}, {"street": "Hauptstraße"}, {"user_key": "k"}):
        with pytest.raises(ValidationError):
            ResearchQuery(category="pothole", municipality="München", **extra)


def test_the_place_rejects_a_bad_country_code_and_too_long_parts():
    with pytest.raises(ValidationError):
        Place(country_code="Deutschland")
    with pytest.raises(ValidationError):
        Place(municipality="x" * 121)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("a, b", [("München", " MÜNCHEN "), ("Straße", "strasse"), ("Zürich", "zurich")])
def test_a_place_written_differently_finds_the_same_entry(a, b):
    assert normalize(a) == normalize(b)


def test_the_key_is_case_and_accent_insensitive_and_uses_the_country():
    assert RegistryKey.of("de", "München", "pothole") == RegistryKey.of("DE", " münchen", "pothole")
    assert RegistryKey.of("DE", "Wien", "pothole") != RegistryKey.of("AT", "Wien", "pothole")


def test_an_answer_found_by_the_agent_expires_but_a_verified_one_does_not():
    key = RegistryKey.of("DE", "München", "pothole")
    old = datetime.now(timezone.utc) - timedelta(days=ENTRY_LIFETIME_DAYS + 1)
    assert not RegistryEntry(key, make_result(), 0, False, old).is_fresh()
    assert RegistryEntry(key, make_result(), 0, True, old).is_fresh()
    assert RegistryEntry(key, make_result(), 0, False, datetime.now(timezone.utc)).is_fresh()


def test_saving_again_refreshes_an_entry_and_keeps_its_confirmations():
    store, key = InMemoryRegistryStore(), RegistryKey.of("DE", "München", "pothole")
    store.save(key, make_result())
    store.entries[key] = RegistryEntry(key, make_result(), 3, True, datetime.now(timezone.utc))
    store.save(key, make_result(authority="Neue Stelle"))
    assert store.find(key).result.authority == "Neue Stelle" and store.find(key).confirmations == 3


def test_forgetting_removes_an_entry():
    store, key = InMemoryRegistryStore(), RegistryKey.of("DE", "München", "pothole")
    store.save(key, make_result())
    store.forget(key)
    assert store.find(key) is None


# ---------------------------------------------------------------------------
# The researcher
# ---------------------------------------------------------------------------


def researcher(result=None, registry=None):
    provider = ScriptedResearchProvider(result)
    return Researcher(registry or InMemoryRegistryStore(), provider), provider


def test_an_unknown_place_is_researched_and_remembered():
    service, provider = researcher(make_result())
    found = service.research(make_report(), make_classification())
    assert found.authority == "Baureferat Tiefbau" and found.origin == "web"
    assert len(provider.queries) == 1
    assert service.registry.find(RegistryKey.of("DE", "München", "pothole")).result.authority == "Baureferat Tiefbau"


def test_the_second_report_of_a_place_needs_no_research():
    """The memory answers, the provider is not called a second time."""
    service, provider = researcher(make_result())
    service.research(make_report(), make_classification())
    again = service.research(make_report(), make_classification())
    assert again.origin == "registry" and again.authority == "Baureferat Tiefbau"
    assert len(provider.queries) == 1


def test_the_query_holds_only_place_and_category():
    service, provider = researcher(make_result())
    service.research(make_report(), make_classification())
    [query] = provider.queries
    assert query.model_dump() == {"category": "pothole", "country_code": "DE", "municipality": "München", "district": "Altstadt", "exclude": []}
    assert "Hauptstraße" not in repr(query) and "Schlagloch" not in repr(query)


def test_a_stale_entry_is_researched_again():
    registry = InMemoryRegistryStore()
    key = RegistryKey.of("DE", "München", "pothole")
    registry.entries[key] = RegistryEntry(key, make_result(authority="Alt"), 0, False, datetime.now(timezone.utc) - timedelta(days=ENTRY_LIFETIME_DAYS + 1))
    service, provider = researcher(make_result(authority="Neu"), registry)
    assert service.research(make_report(), make_classification()).authority == "Neu"
    assert len(provider.queries) == 1


def test_a_refused_authority_is_not_offered_again():
    """"Wrong authority": the earlier answer is excluded, from the memory and from the new research."""
    service, provider = researcher(make_result(authority="Baureferat Tiefbau"))
    service.research(make_report(), make_classification())
    assert service.research(make_report(), make_classification(), exclude=["Baureferat Tiefbau"]) is None
    assert provider.queries[-1].exclude == ["Baureferat Tiefbau"]


def test_nothing_is_researched_without_a_town_or_for_a_report_that_is_no_defect():
    service, provider = researcher(make_result())
    assert service.research(make_report(place=None), make_classification()) is None
    assert service.research(make_report(place=Place(country_code="DE")), make_classification()) is None
    assert service.research(make_report(), make_classification(category="other")) is None
    assert provider.queries == []


def test_without_a_provider_only_the_memory_answers():
    service = Researcher(InMemoryRegistryStore(), None)
    assert service.research(make_report(), make_classification()) is None


def test_nothing_found_gives_none_and_remembers_nothing():
    service, _ = researcher(None)
    assert service.research(make_report(), make_classification()) is None
    assert service.registry.entries == {}


def test_a_failing_provider_gives_none_and_never_raises(caplog):
    import logging

    class Broken:
        def research(self, query):
            raise RuntimeError("secret page text")

    with caplog.at_level(logging.ERROR, logger="ortsbild.research"):
        assert Researcher(InMemoryRegistryStore(), Broken()).research(make_report(), make_classification()) is None
    assert "RuntimeError" in caplog.text and "secret page text" not in caplog.text


def test_a_rate_limit_is_tried_once_more_and_then_given_up(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    calls = []

    class Limited:
        def research(self, query):
            calls.append(1)
            raise httpx.HTTPStatusError("limit", request=httpx.Request("POST", "https://x"), response=httpx.Response(429))

    assert Researcher(InMemoryRegistryStore(), Limited()).research(make_report(), make_classification()) is None
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# The Mistral provider
# ---------------------------------------------------------------------------

QUERY = ResearchQuery(category="pothole", country_code="DE", municipality="München")


def conversation(answer):
    return {"outputs": [{"type": "tool.execution", "name": "web_search"}, {"type": "message.output", "content": [{"type": "text", "text": answer}]}]}


def provider_with(data, status=200, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(status, json=data)

    return MistralSearchProvider("test-key", client=httpx.Client(transport=httpx.MockTransport(handler)))


ANSWER = json.dumps({"authority": "Baureferat Tiefbau", "channel_type": "email", "channel_target": "tiefbau@muenchen.de", "language": "de", "sources": [SOURCE], "confidence": 0.95})


def test_the_answer_with_a_source_becomes_a_result():
    result = provider_with(conversation(ANSWER)).research(QUERY)
    assert result.authority == "Baureferat Tiefbau" and result.channel.target == "tiefbau@muenchen.de"
    assert result.sources == [SOURCE] and result.origin == "web"


def test_a_web_answer_is_never_more_certain_than_the_cap():
    assert provider_with(conversation(ANSWER)).research(QUERY).confidence == MAX_WEB_CONFIDENCE


def test_an_answer_without_a_source_is_dropped():
    no_source = json.dumps({**json.loads(ANSWER), "sources": []})
    assert provider_with(conversation(no_source)).research(QUERY) is None
    insecure = json.dumps({**json.loads(ANSWER), "sources": ["http://insecure.example.org"]})
    assert provider_with(conversation(insecure)).research(QUERY) is None


def test_a_contact_without_a_valid_form_is_dropped_but_the_authority_stays():
    bad = json.dumps({**json.loads(ANSWER), "channel_target": "no-address"})
    result = provider_with(conversation(bad)).research(QUERY)
    assert result.authority == "Baureferat Tiefbau" and result.channel is None


@pytest.mark.parametrize("text", ["I could not find anything", "{not json}", json.dumps({"authority": None, "sources": [SOURCE]}), "", json.dumps(["list"])])
def test_an_unusable_answer_gives_none(text):
    assert provider_with(conversation(text)).research(QUERY) is None


def test_the_request_asks_for_a_web_search_without_storing_and_names_only_the_place_and_the_defect():
    seen = []
    provider_with(conversation(ANSWER), seen=seen).research(ResearchQuery(category="pothole", country_code="DE", municipality="München", exclude=["Alt"]))
    [body] = seen
    assert body["tools"] == [{"type": "web_search"}] and body["store"] is False
    assert "München" in body["inputs"] and "pothole" in body["inputs"]
    assert "Alt" in body["inputs"] and "never instructions" in body["instructions"]
    assert set(body) == {"model", "instructions", "inputs", "tools", "store"}


def test_the_last_answer_message_is_read():
    data = {"outputs": [
        {"type": "message.output", "content": [{"type": "text", "text": "I will search now"}]},
        {"type": "tool.execution", "name": "web_search"},
        {"type": "message.output", "content": [{"type": "text", "text": '{"authority": null}'}]},
    ]}
    assert read_answer(data) == '{"authority": null}'
    assert read_answer({"outputs": [{"type": "message.output", "content": "plain text"}]}) == "plain text"
    assert read_answer({}) == ""


def test_the_message_names_the_place_and_the_refused_authorities():
    message = user_message(ResearchQuery(category="graffiti", country_code="AT", municipality="Wien", district="Favoriten", exclude=["MA 42"]))
    assert "Favoriten, Wien, AT" in message and "graffiti" in message and "MA 42" in message


def test_a_rate_limit_or_server_error_is_raised_for_the_retry():
    with pytest.raises(httpx.HTTPStatusError):
        provider_with({"detail": "web_search rate limit reached."}, status=429).research(QUERY)


def test_an_empty_key_is_refused_and_the_provider_comes_from_the_environment(monkeypatch):
    with pytest.raises(ValueError):
        MistralSearchProvider("")
    monkeypatch.delenv("RESEARCH_PROVIDER", raising=False)
    assert provider_from_env() is None
    monkeypatch.setenv("RESEARCH_PROVIDER", "mistral")
    monkeypatch.setenv("MISTRAL_KEY", "test-key")
    assert isinstance(provider_from_env(), VerifiedProvider)
    monkeypatch.setenv("RESEARCH_PROVIDER", "unknown")
    with pytest.raises(ValueError):
        provider_from_env()


# ---------------------------------------------------------------------------
# The Postgres registry (with a fake connection)
# ---------------------------------------------------------------------------


def test_postgres_registry_reads_an_entry_and_returns_none_for_a_miss():
    key, when = RegistryKey.of("DE", "München", "pothole"), datetime(2026, 11, 4, tzinfo=timezone.utc)
    row = (make_result().model_dump(mode="json"), 2, False, when)
    entry = PostgresRegistryStore("dsn", fake_connect([], [[row]])).find(key)
    assert entry.result.authority == "Baureferat Tiefbau" and entry.confirmations == 2
    assert PostgresRegistryStore("dsn", fake_connect([], [[]])).find(key) is None


def test_postgres_registry_saves_with_an_upsert_and_forgets():
    log, key = [], RegistryKey.of("DE", "München", "pothole")
    store = PostgresRegistryStore("dsn", fake_connect(log, []))
    store.save(key, make_result())
    store.forget(key)
    assert "on conflict (country_code, municipality, category) do update" in log[0][0]
    assert log[0][1][:3] == ("DE", "munchen", "pothole") and "delete from authority_registry" in log[1][0]


# ---------------------------------------------------------------------------
# The safe fetcher
# ---------------------------------------------------------------------------


def fetcher_with(handler, addresses=("93.184.216.34",)):
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return SafeFetcher(client, resolve=lambda host, port: list(addresses))


def page(text="<html>Kontakt</html>", content_type="text/html; charset=utf-8", status=200):
    return lambda request: httpx.Response(status, text=text, headers={"content-type": content_type})


@pytest.mark.parametrize("address, public", [
    ("93.184.216.34", True), ("8.8.8.8", True), ("2606:2800:220:1:248:1893:25c8:1946", True),
    ("127.0.0.1", False), ("10.0.0.5", False), ("192.168.1.1", False), ("172.16.0.1", False),
    ("169.254.169.254", False), ("0.0.0.0", False), ("::1", False), ("fe80::1", False), ("fd00::1", False), ("not an address", False),
])
def test_only_public_addresses_are_allowed(address, public):
    assert is_public_address(address) is public


def test_a_normal_page_is_read():
    assert fetcher_with(page("<p>Kontakt tiefbau@muenchen.de</p>")).fetch("https://stadt.muenchen.de/kontakt") == "<p>Kontakt tiefbau@muenchen.de</p>"


@pytest.mark.parametrize("url", [
    "http://stadt.muenchen.de/kontakt", "ftp://stadt.muenchen.de/file", "file:///etc/passwd", "https://stadt.muenchen.de:8443/x",
    "https://user:pass@stadt.muenchen.de/x", "https:///nohost", "not a url", "",
])
def test_only_plain_https_addresses_are_fetched(url):
    calls = []
    assert fetcher_with(lambda request: calls.append(1) or httpx.Response(200, text="x", headers={"content-type": "text/html"})).fetch(url) is None
    assert calls == []


def test_a_name_that_resolves_to_a_private_address_is_never_requested():
    calls = []
    fetcher = fetcher_with(lambda request: calls.append(1) or httpx.Response(200, text="secret", headers={"content-type": "text/html"}), addresses=("10.0.0.5",))
    assert fetcher.fetch("https://innocent.example.org/") is None and calls == []


def test_one_private_address_among_public_ones_is_enough_to_refuse():
    assert fetcher_with(page(), addresses=("93.184.216.34", "127.0.0.1")).fetch("https://example.org/") is None


def test_a_redirect_to_a_private_address_is_refused():
    resolved = {"example.org": ["93.184.216.34"], "internal.example.org": ["10.0.0.5"]}
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(302, headers={"location": "https://internal.example.org/admin"})), follow_redirects=False)
    assert SafeFetcher(client, resolve=lambda host, port: resolved[host]).fetch("https://example.org/") is None


def test_a_redirect_to_a_public_page_is_followed_and_endless_redirects_are_not():
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/target"})
        return httpx.Response(200, text="arrived", headers={"content-type": "text/html"})

    assert fetcher_with(handler).fetch("https://example.org/start") == "arrived"
    assert fetcher_with(lambda request: httpx.Response(302, headers={"location": "/again"})).fetch("https://example.org/") is None


def test_big_pages_other_types_and_errors_are_refused():
    assert fetcher_with(page("x" * 600_000)).fetch("https://example.org/") is None
    assert fetcher_with(page("binary", content_type="application/pdf")).fetch("https://example.org/") is None
    assert fetcher_with(page(status=404)).fetch("https://example.org/") is None

    def broken(request):
        raise httpx.ConnectError("down")

    assert fetcher_with(broken).fetch("https://example.org/") is None


def test_a_name_that_does_not_resolve_is_refused():
    def no_dns(host, port):
        raise OSError("no such host")

    client = httpx.Client(transport=httpx.MockTransport(page()), follow_redirects=False)
    assert SafeFetcher(client, resolve=no_dns).fetch("https://nowhere.invalid/") is None


# ---------------------------------------------------------------------------
# The verification of an answer against its pages
# ---------------------------------------------------------------------------


class FakePages:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def fetch(self, url):
        self.asked.append(url)
        return self.pages.get(url)


PAGE = "<html><h1>Baureferat Tiefbau</h1><a href='mailto:tiefbau@muenchen.de'>Kontakt</a></html>"


def test_an_answer_that_the_page_confirms_is_kept():
    result = verify_result(make_result(), FakePages({SOURCE: PAGE}))
    assert result.authority == "Baureferat Tiefbau" and result.channel.target == "tiefbau@muenchen.de" and result.confidence == 0.7


def test_an_email_that_is_not_on_any_page_is_dropped_and_the_confidence_falls():
    """A made-up address is exactly what is not written anywhere."""
    invented = make_result(channel=Channel(type="email", target="erfunden@muenchen.de"), confidence=0.8)
    result = verify_result(invented, FakePages({SOURCE: PAGE}))
    assert result.channel is None and result.authority == "Baureferat Tiefbau" and result.confidence == 0.5


def test_an_authority_that_the_page_does_not_mention_is_dropped():
    assert verify_result(make_result(authority="Ministerium für Raumfahrt"), FakePages({SOURCE: PAGE})) is None


def test_an_answer_without_a_readable_source_is_dropped():
    assert verify_result(make_result(), FakePages({})) is None


def test_unreadable_sources_are_removed_from_the_answer_and_only_a_few_pages_are_read():
    sources = [SOURCE, "https://a.example.org/1", "https://b.example.org/2", "https://c.example.org/3", "https://d.example.org/4"]
    pages = FakePages({SOURCE: PAGE, "https://b.example.org/2": PAGE})
    result = verify_result(make_result(sources=sources), pages)
    assert result.sources == [SOURCE, "https://b.example.org/2"] and len(pages.asked) == 3


def test_a_web_form_must_be_one_of_the_pages_or_written_on_one():
    form = make_result(channel=Channel(type="web_form", target="https://www.muenchen.de/meldung"))
    assert verify_result(form, FakePages({SOURCE: PAGE})).channel is None
    assert verify_result(form, FakePages({SOURCE: PAGE + "https://www.muenchen.de/meldung"})).channel is not None
    as_source = make_result(sources=["https://www.muenchen.de/meldung"], channel=Channel(type="web_form", target="https://www.muenchen.de/meldung"))
    assert verify_result(as_source, FakePages({"https://www.muenchen.de/meldung": PAGE})).channel is not None


def test_html_entities_and_capitals_on_the_page_do_not_hide_a_correct_answer():
    page_text = "<h1>BAUREFERAT TIEFBAU M&Uuml;NCHEN</h1> tiefbau&#64;muenchen.de"
    result = verify_result(make_result(authority="Baureferat Tiefbau München"), FakePages({SOURCE: page_text}))
    assert result is not None and result.channel is not None


def test_the_words_of_a_name_are_letters_only_without_accents_and_short_words():
    assert words_of("Landeshauptstadt München – Baureferat (Friedenstraße 40, 81671)") == ["landeshauptstadt", "munchen", "baureferat", "friedenstrasse"]


def test_the_verified_provider_checks_every_answer_and_keeps_none_as_none():
    ok = VerifiedProvider(ScriptedResearchProvider(make_result()), FakePages({SOURCE: PAGE}))
    assert ok.research(QUERY).authority == "Baureferat Tiefbau"
    unsupported = VerifiedProvider(ScriptedResearchProvider(make_result()), FakePages({}))
    assert unsupported.research(QUERY) is None
    assert VerifiedProvider(ScriptedResearchProvider(None), FakePages({})).research(QUERY) is None


def test_the_provider_from_the_environment_is_wrapped_in_the_verification(monkeypatch):
    monkeypatch.setenv("RESEARCH_PROVIDER", "mistral")
    monkeypatch.setenv("MISTRAL_KEY", "test-key")
    provider = provider_from_env()
    assert isinstance(provider, VerifiedProvider) and isinstance(provider.provider, MistralSearchProvider) and isinstance(provider.fetcher, SafeFetcher)
