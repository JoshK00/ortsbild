import io
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from PIL.ExifTags import IFD

from gateway.config import Settings
from gateway.db import ReportRepository
from gateway.ingest import IngestService
from gateway.main import create_app
from gateway.storage import LocalStorage

API_KEY = "test-key"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        tenant="test-town",
        api_keys=[API_KEY],
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_backend="local",
        storage_local_root=str(tmp_path / "storage"),
    )


@pytest.fixture
def storage(settings) -> LocalStorage:
    return LocalStorage(settings.storage_local_root)


@pytest.fixture
def client(settings, storage) -> TestClient:
    return TestClient(create_app(settings, storage))


@pytest.fixture
def ingest(settings, storage) -> IngestService:
    return IngestService(settings, ReportRepository.from_url(settings.database_url), storage)


def make_jpeg(width=3000, height=2000, gps: tuple[float, float] | None = None, camera="TestPhone 12") -> bytes:
    """JPEG with camera metadata and optionally a GPS position in EXIF."""
    img = Image.new("RGB", (width, height), (120, 140, 160))
    exif = Image.Exif()
    exif[0x0110] = camera  # Model
    if gps:
        lat, lon = gps
        exif[IFD.GPSInfo] = {
            1: "N" if lat >= 0 else "S",
            2: _to_dms(abs(lat)),
            3: "E" if lon >= 0 else "W",
            4: _to_dms(abs(lon)),
        }
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def _to_dms(value: float) -> tuple[float, float, float]:
    degrees = int(value)
    minutes = int((value - degrees) * 60)
    seconds = round((value - degrees - minutes / 60) * 3600, 4)
    return (float(degrees), float(minutes), seconds)


def make_email(
    subject="Schlagloch Gartengasse",
    body="Großes Schlagloch vor Hausnummer 12.",
    sender="buerger@example.org",
    message_id="<abc123@example.org>",
    images: list[bytes] | None = None,
    headers: dict[str, str] | None = None,
    html: str | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = f"Bürger <{sender}>"
    msg["To"] = "melden@example.gov"
    msg["Subject"] = subject
    msg["Date"] = "Sun, 01 Nov 2026 20:15:00 +0100"
    if message_id:
        msg["Message-ID"] = message_id
    for name, value in (headers or {}).items():
        msg[name] = value
    if body is not None:
        msg.set_content(body)
    if html is not None:
        if body is None:
            msg.set_content(html, subtype="html")
        else:
            msg.add_alternative(html, subtype="html")
    for i, data in enumerate(images or []):
        msg.add_attachment(data, maintype="image", subtype="jpeg", filename=f"foto{i}.jpg")
    return msg.as_bytes()
