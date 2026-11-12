import io
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.geocode import MIN_SECONDS_BETWEEN_CALLS, GeocoderUnavailable, NominatimGeocoder, label_of
from api.public import SEARCHES_PER_MINUTE, create_public_router

ITEM = {"lat": "48.7784", "lon": "9.18", "display_name": "Schlossplatz, Mitte, Stuttgart, Baden-Württemberg, 70173, Deutschland",
        "address": {"road": "Schlossplatz", "city": "Stuttgart", "postcode": "70173"}}


class Fake:
    def __init__(self, results=None, fail=False):
        self.results, self.fail, self.texts = results or [], fail, []

    def search(self, text):
        self.texts.append(text)
        if self.fail:
            raise GeocoderUnavailable
        return self.results


def client_with(geocoder, clock=None):
    app = FastAPI()
    app.include_router(create_public_router(lambda: None, lambda: [], geocoder=geocoder, **({"clock": clock} if clock else {})))
    return TestClient(app)


def test_the_search_returns_the_places_of_the_geocoder():
    geocoder = Fake([{"label": "Schlossplatz, 70173 Stuttgart", "lat": 48.7784, "lon": 9.18}])
    answer = client_with(geocoder).get("/v1/public/search", params={"q": " Schlossplatz Stuttgart "})
    assert answer.status_code == 200 and answer.json()["results"][0]["label"] == "Schlossplatz, 70173 Stuttgart"
    assert geocoder.texts == ["Schlossplatz Stuttgart"] and answer.headers["cache-control"] == "no-store"


def test_a_too_short_or_too_long_text_is_refused_before_anything_is_sent_on():
    geocoder = Fake()
    client = client_with(geocoder)
    assert client.get("/v1/public/search", params={"q": "ab"}).status_code == 422
    assert client.get("/v1/public/search", params={"q": "x" * 101}).status_code == 422
    assert client.get("/v1/public/search").status_code == 422
    assert geocoder.texts == []


def test_a_geocoder_that_is_down_gives_503():
    assert client_with(Fake(fail=True)).get("/v1/public/search", params={"q": "Stuttgart"}).status_code == 503


def test_all_visitors_together_get_a_limited_number_of_searches_per_minute():
    now = [0.0]
    client = client_with(Fake(), clock=lambda: now[0])
    codes = [client.get("/v1/public/search", params={"q": "Stuttgart"}).status_code for _ in range(SEARCHES_PER_MINUTE + 1)]
    assert codes[:-1] == [200] * SEARCHES_PER_MINUTE and codes[-1] == 429
    now[0] = 61.0
    assert client.get("/v1/public/search", params={"q": "Stuttgart"}).status_code == 200


def test_the_label_is_short_and_german():
    assert label_of(ITEM) == "Schlossplatz, 70173 Stuttgart"
    assert label_of({"display_name": "A, B, C, D, E"}) == "A, B, C"


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_nominatim_is_asked_for_germany_only_with_a_user_agent_and_the_answer_is_kept_for_an_hour():
    seen, now = [], [0.0]

    def opener(request, timeout):
        seen.append(request)
        return Response(json.dumps([ITEM]).encode())

    geocoder = NominatimGeocoder(opener=opener, clock=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
    first = geocoder.search("Schlossplatz Stuttgart")
    again = geocoder.search("  SCHLOSSPLATZ   stuttgart ")
    assert first == again == [{"label": "Schlossplatz, 70173 Stuttgart", "lat": 48.7784, "lon": 9.18}]
    assert len(seen) == 1
    url = seen[0].full_url
    assert "countrycodes=de" in url and "accept-language=de" in url and "limit=5" in url
    assert seen[0].get_header("User-agent").startswith("Ortsbild-Dashboard")
    assert "Cookie" not in seen[0].headers and "X-forwarded-for" not in seen[0].headers
    now[0] += 4000  # an hour later it asks again
    geocoder.search("Schlossplatz Stuttgart")
    assert len(seen) == 2


def test_nominatim_is_called_at_most_once_a_second_and_a_failure_is_unavailable():
    now, pauses = [0.0], []
    calls = []

    def opener(request, timeout):
        calls.append(now[0])
        return Response(b"[]")

    def sleep(seconds):
        pauses.append(seconds)
        now[0] += seconds

    geocoder = NominatimGeocoder(opener=opener, clock=lambda: now[0], sleep=sleep)
    geocoder.search("eins")
    geocoder.search("zwei")
    assert calls[1] - calls[0] >= MIN_SECONDS_BETWEEN_CALLS - 1e-9 and pauses

    def broken(request, timeout):
        raise OSError("no network")

    try:
        NominatimGeocoder(opener=broken).search("drei")
        raise AssertionError("no error")
    except GeocoderUnavailable:
        pass
