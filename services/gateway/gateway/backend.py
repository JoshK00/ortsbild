"""The way to the backend: its entrance for the gateway, POST /internal/v1/reports (backend/api/gateway.py)."""

import json
from dataclasses import dataclass

import httpx


class BackendUnreachable(Exception):
    """No connection to the backend: it did not get the report."""


class BackendTimeout(Exception):
    """The backend did not answer in time: it may still be working on the report."""


@dataclass
class BackendAnswer:
    status_code: int
    content: bytes
    content_type: str | None
    www_authenticate: str | None


class BackendClient:
    def __init__(self, base_url: str, gateway_key: str, timeout_s: float, http: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.gateway_key = gateway_key
        self.http = http or httpx.Client(timeout=httpx.Timeout(timeout_s, connect=5.0))

    def submit(self, submission: dict, authorization: str) -> BackendAnswer:
        """Hand a report over. `authorization` is the header of the app, passed on unchanged: the backend checks it."""
        try:
            response = self.http.post(
                f"{self.base_url}/internal/v1/reports",
                content=json.dumps(submission),
                headers={
                    "Authorization": authorization,
                    "X-Gateway-Key": self.gateway_key,
                    "Content-Type": "application/json",
                },
            )
        except httpx.ConnectError as error:
            raise BackendUnreachable() from error
        except httpx.TimeoutException as error:
            if isinstance(error, httpx.ConnectTimeout):
                raise BackendUnreachable() from error
            raise BackendTimeout() from error
        return BackendAnswer(
            response.status_code,
            response.content,
            response.headers.get("content-type"),
            response.headers.get("www-authenticate"),
        )
