import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from gateway.backend import BackendAnswer, BackendTimeout, BackendUnreachable
from gateway.main import create_app
from gateway.raw_store import InMemoryRawPhotoStore

TOKEN = {"Authorization": "Bearer token-of-anna"}
FORM = {"client_report_id": "1B9D6BCD-BBFD-4B2D-9B5D-AB8DFBBD4BED", "lat": "48.7758", "lon": "9.1829"}


def make_image(fmt: str = "JPEG", size=(40, 20)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(output, format=fmt)
    return output.getvalue()


def make_heic(size=(40, 20)) -> bytes:
    import pillow_heif

    pillow_heif.register_heif_opener()
    output = io.BytesIO()
    Image.new("RGB", size, (30, 200, 30)).save(output, format="HEIF")
    return output.getvalue()


class FakeBackend:
    """Stands in for the backend. By default it answers like the backend does for a new report: 200 with its payload."""

    def __init__(self):
        self.calls: list[tuple[dict, str]] = []
        self.status_code = 200
        self.body: dict | None = None  # None: a payload for the submitted report
        self.error: Exception | None = None

    def submit(self, submission: dict, authorization: str) -> BackendAnswer:
        self.calls.append((submission, authorization))
        if self.error:
            raise self.error
        body = self.body if self.body is not None else {"id": submission["id"], "status": "sanitized"}
        www = "Bearer" if self.status_code == 401 else None
        return BackendAnswer(self.status_code, json.dumps(body).encode(), "application/json", www)


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def store() -> InMemoryRawPhotoStore:
    return InMemoryRawPhotoStore()


@pytest.fixture
def client(store, backend) -> TestClient:
    return TestClient(create_app(raw_store=store, backend=backend))


@pytest.fixture
def unreachable():
    return BackendUnreachable()


@pytest.fixture
def timeout():
    return BackendTimeout()
