"""The place and address search of the dashboard.

The browser never calls a third party (the page allows only its own server). It asks `GET /v1/public/search`, our server asks
the public geocoder of OpenStreetMap (Nominatim) and sends only the text that was typed, nothing of the visitor (no address,
no headers). Answers are kept for an hour, and the server calls Nominatim at most once a second, as its usage policy asks.

TODO: Run an own geocoder (Photon or Nominatim on the Cube) if the dashboard gets real traffic. The public one is for light use.
"""

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger("ortsbild.api")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "Ortsbild-Dashboard/1.0 (university project, place search of the dashboard)"
MIN_SECONDS_BETWEEN_CALLS = 1.1
CACHE_SECONDS = 3600
CACHE_MAX_ENTRIES = 500
MAX_RESULTS = 5


class GeocoderUnavailable(Exception):
    """The search service did not answer."""


class Geocoder(Protocol):
    def search(self, text: str) -> list[dict]: ...


def label_of(item: dict) -> str:
    """A short German label: "Königstraße 1, 70173 Stuttgart" from the parts of the answer, else the first parts of the long name."""
    address = item.get("address") or {}
    street = " ".join(part for part in (address.get("road"), address.get("house_number")) if part)
    town = address.get("city") or address.get("town") or address.get("village") or address.get("municipality")
    town_line = " ".join(part for part in (address.get("postcode"), town) if part)
    label = ", ".join(part for part in (street or item.get("name"), town_line) if part)
    if not label:
        label = ", ".join(str(item.get("display_name", "")).split(", ")[:3])
    return label[:120]


class NominatimGeocoder:
    """Germany only, German labels, at most five results, throttled and cached."""

    def __init__(self, opener: Callable = urllib.request.urlopen, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self.opener, self.clock, self.sleep = opener, clock, sleep
        self.cache: dict[str, tuple[float, list[dict]]] = {}
        self.lock = threading.Lock()
        self.last_call = -MIN_SECONDS_BETWEEN_CALLS

    def search(self, text: str) -> list[dict]:
        key = " ".join(text.lower().split())
        with self.lock:  # one call at a time, so the pause between calls holds
            cached = self.cache.get(key)
            if cached and self.clock() - cached[0] < CACHE_SECONDS:
                return cached[1]
            wait = self.last_call + MIN_SECONDS_BETWEEN_CALLS - self.clock()
            if wait > 0:
                self.sleep(wait)
            query = urllib.parse.urlencode({
                "q": text, "format": "jsonv2", "countrycodes": "de", "limit": MAX_RESULTS, "addressdetails": 1, "accept-language": "de",
            })
            request = urllib.request.Request(f"{NOMINATIM_URL}?{query}", headers={"User-Agent": USER_AGENT})
            self.last_call = self.clock()
            try:
                with self.opener(request, timeout=6) as response:
                    items = json.loads(response.read().decode("utf-8"))
            except Exception as error:  # the type only, the text could be what a person typed
                logger.error("place search failed: error=%s", type(error).__name__)
                raise GeocoderUnavailable from None
            results = [
                {"label": label_of(item), "lat": float(item["lat"]), "lon": float(item["lon"])}
                for item in items[:MAX_RESULTS] if "lat" in item and "lon" in item
            ]
            if len(self.cache) >= CACHE_MAX_ENTRIES:
                self.cache.clear()
            self.cache[key] = (self.clock(), results)
            return results
