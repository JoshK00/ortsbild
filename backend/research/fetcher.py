import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import httpx

USER_AGENT = "OrtsbildResearch/0.1 (checks a contact that a search named, one request per page)"
MAX_BYTES = 500_000
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 5.0
TEXT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")


def is_public_address(address: str) -> bool:
    """False for every address that is not on the public internet: private, loopback, link-local, reserved."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def resolve_all(host: str, port: int) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


class SafeFetcher:
    """Reads one web page that a search named, with strict limits. Plain code, no model, so no page can give it orders.

    The address comes from a model, so it is never trusted: only `https` on the usual port, every address the name resolves
    to must be public (nothing inside our network or on the server itself), a redirect is checked again from the start,
    the size and the time are capped, and only text is accepted.
    TODO: The name is resolved here and again by the connection, an attacker who controls a DNS server could answer
    differently the second time. Close the gap by connecting to the checked address, or by a proxy that blocks private addresses.
    """

    def __init__(self, client: httpx.Client | None = None, resolve: Callable[[str, int], list[str]] = resolve_all) -> None:
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)
        self._resolve = resolve

    def fetch(self, url: str) -> str | None:
        """The page as text, or None for anything that is not allowed or does not work."""
        for _ in range(MAX_REDIRECTS + 1):
            if not self._allowed(url):
                return None
            try:
                with self._client.stream("GET", url, headers={"User-Agent": USER_AGENT}, follow_redirects=False) as response:
                    if 300 <= response.status_code < 400 and response.headers.get("location"):
                        url = urljoin(url, response.headers["location"])
                        continue
                    if response.status_code != 200 or not response.headers.get("content-type", "").lower().startswith(TEXT_TYPES):
                        return None
                    body = b""
                    for chunk in response.iter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            return None  # too big, not a contact page
                    return body.decode(response.encoding or "utf-8", errors="replace")
            except (httpx.HTTPError, OSError):
                return None
        return None  # too many redirects

    def _allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.port not in (None, 443):
            return False
        if parsed.username or parsed.password:
            return False
        try:
            addresses = self._resolve(parsed.hostname, 443)
        except OSError:
            return False
        return bool(addresses) and all(is_public_address(address) for address in addresses)
