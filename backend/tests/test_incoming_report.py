from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models.incoming_report import IncomingReport, Location, Photo, Source, User


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


def test_valid_location_is_accepted():
    """Normal case: ordinary coordinates (Munich) are accepted unchanged."""
    location = Location(lat=48.1371, lon=11.5754)
    assert location.lat == 48.1371
    assert location.lon == 11.5754


def test_upper_boundary_values_are_accepted():
    """The limits themselves (90 and 180) are valid, the range is inclusive."""
    location = Location(lat=90, lon=180)
    assert location.lat == 90
    assert location.lon == 180


def test_lower_boundary_values_are_accepted():
    """The lower limits themselves (-90 and -180) are valid as well."""
    location = Location(lat=-90, lon=-180)
    assert location.lat == -90
    assert location.lon == -180


def test_latitude_above_90_is_rejected():
    """A latitude above 90 is not a valid coordinate and must raise a ValidationError."""
    with pytest.raises(ValidationError):
        Location(lat=200, lon=11.5754)


def test_longitude_below_minus_180_is_rejected():
    """A longitude below -180 is not a valid coordinate and must raise a ValidationError."""
    with pytest.raises(ValidationError):
        Location(lat=48.1371, lon=-181)


def test_latitude_as_text_is_rejected():
    """In strict mode a latitude given as text ("48.1") is not converted but rejected."""
    with pytest.raises(ValidationError):
        Location(lat="48.1", lon=11.5754)


def test_missing_latitude_is_rejected():
    """Both coordinates are required, a missing latitude must raise a ValidationError."""
    with pytest.raises(ValidationError):
        Location(lon=11.5754)


# ---------------------------------------------------------------------------
# Photo
# ---------------------------------------------------------------------------


def test_valid_photo_is_accepted():
    """Normal case: an image attachment with id, image mime type and reference is accepted."""
    photo = Photo(id="p1", mime_type="image/jpeg", ref="raw/7c9e/p1.jpg")
    assert photo.mime_type == "image/jpeg"


def test_non_image_mime_type_is_rejected():
    """A PDF is not an image, the gateway contract only allows image/* types."""
    with pytest.raises(ValidationError):
        Photo(id="p1", mime_type="application/pdf", ref="raw/7c9e/p1.pdf")


def test_image_prefix_without_subtype_is_rejected():
    """"image/" alone is not a real mime type, a subtype like jpeg must follow."""
    with pytest.raises(ValidationError):
        Photo(id="p1", mime_type="image/", ref="raw/7c9e/p1")


def test_photo_with_empty_ref_is_rejected():
    """Without a reference nobody can find the file again, an empty ref is invalid."""
    with pytest.raises(ValidationError):
        Photo(id="p1", mime_type="image/png", ref="")


def test_uppercase_mime_type_is_rejected():
    """Photo only accepts lowercase types on purpose, the gateway has to lowercase them first."""
    with pytest.raises(ValidationError):
        Photo(id="p1", mime_type="IMAGE/JPEG", ref="raw/7c9e/p1.jpg")


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------


def test_valid_source_is_accepted():
    """Normal case: a known source type with connector name and raw data reference."""
    source = Source(type="email", connector="imap-inbox", raw_ref="raw/3b24/message.eml")
    assert source.type == "email"


def test_unknown_source_type_is_rejected():
    """Only known source types pass, a new type needs an explicit contract change."""
    with pytest.raises(ValidationError):
        Source(type="fax", connector="x", raw_ref="raw/1")


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


def test_valid_user_is_accepted():
    """Normal case: identifier with a known identifier type."""
    user = User(identifier="device-8f14e45f", identifier_type="device_id")
    assert user.identifier_type == "device_id"


def test_empty_user_identifier_is_rejected():
    """An empty identifier cannot be mapped to a pseudonym, so it is invalid."""
    with pytest.raises(ValidationError):
        User(identifier="", identifier_type="email")


# ---------------------------------------------------------------------------
# IncomingReport
# ---------------------------------------------------------------------------


def make_report_data(**overrides):
    """Build the raw data of a valid app report, tests change only what they check."""
    data = {
        "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
        "received_at": datetime(2026, 10, 27, 12, 30, tzinfo=timezone.utc),
        "source": {"type": "app", "connector": "ortsbild-ios", "raw_ref": "raw/7c9e/"},
        "location": {"lat": 48.1371, "lon": 11.5754, "accuracy_m": 12, "origin": "device_gps"},
        "text": "The bin at the bus stop is overflowing.",
        "photos": [{"id": "p1", "mime_type": "image/jpeg", "ref": "raw/7c9e/p1.jpg"}],
        "user": {"identifier": "device-8f14e45f", "identifier_type": "device_id"},
    }
    data.update(overrides)
    return data


def test_valid_app_report_is_accepted():
    """Normal case: a report with photo, text and location as the app delivers it."""
    report = IncomingReport(**make_report_data())
    assert report.source.type == "app"
    assert report.photos[0].mime_type == "image/jpeg"


def test_valid_email_report_without_photo_is_accepted():
    """Same structure for email: no photo is fine, as long as the location is there."""
    report = IncomingReport(
        **make_report_data(
            source={"type": "email", "connector": "imap-inbox", "raw_ref": "raw/3b24/message.eml"},
            photos=[],
            user={"identifier": "max@example.com", "identifier_type": "email"},
        )
    )
    assert report.photos == []


def test_report_without_text_is_accepted():
    """Text is optional, a photo with a location can be a complete report."""
    report = IncomingReport(**make_report_data(text=None))
    assert report.text is None


def test_report_without_location_is_rejected():
    """A report without a location is meaningless and must not pass the contract."""
    data = make_report_data()
    del data["location"]
    with pytest.raises(ValidationError):
        IncomingReport(**data)


def test_report_with_invalid_nested_location_is_rejected():
    """The rules of nested models apply too, a latitude of 200 inside the report fails."""
    with pytest.raises(ValidationError):
        IncomingReport(**make_report_data(location={"lat": 200, "lon": 11.5754}))


def test_report_with_naive_timestamp_is_rejected():
    """received_at needs a timezone, a date without one is ambiguous."""
    with pytest.raises(ValidationError):
        IncomingReport(**make_report_data(received_at=datetime(2026, 10, 27, 12, 30)))


def test_report_with_unknown_field_is_rejected():
    """Unknown fields are rejected, a connector cannot smuggle in extra data."""
    with pytest.raises(ValidationError):
        IncomingReport(**make_report_data(secret_note="x"))


def test_report_cannot_be_changed_after_creation():
    """Reports are frozen, nothing downstream can alter the raw report."""
    report = IncomingReport(**make_report_data())
    with pytest.raises(ValidationError):
        report.text = "changed"
