from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


# TODO: Add more source types when new connectors are built.
SourceType = Literal["app", "email"]


class ContractModel(BaseModel):
    """Base class of all data contract models, so the rules are defined once.

    strict: no silent conversion ("48.1" stays text and is rejected).
    extra="forbid": unknown fields are rejected, a connector cannot smuggle in extra data.
    frozen: a model cannot be changed after creation.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class Location(ContractModel):
    """Geographic position of a report as WGS84 coordinates in decimal degrees."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0)
    # TODO: Decide whether origin is required or can be dropped. The privacy layer no
    #       longer uses it, the location is passed on unchanged.
    origin: Literal["device_gps", "exif", "geocoded_from_text"] | None = None
    # TODO: Decide whether the place is also kept as text (address_text) next to lat/lon.


class Photo(ContractModel):
    """Reference to one image attachment of a report, not the image data itself.

    Only image types pass: the gateway rejects every other attachment.
    """

    id: str = Field(min_length=1)
    mime_type: str = Field(pattern=r"^image/[\w.+-]+$")
    ref: str = Field(min_length=1)  # pointer to the stored file
    # TODO: Add limits (file size, number of photos) once the gateway rules are decided.


class Source(ContractModel):
    """Where a report came from. Provenance only, the report structure is the same for all sources."""

    type: SourceType
    connector: str = Field(min_length=1)
    raw_ref: str = Field(min_length=1)  # pointer to the raw data, needed to delete it later


class User(ContractModel):
    """Plain identifier of the reporter. Only the privacy agent may read it.

    The privacy agent replaces it with a pseudonym, nothing downstream sees this.
    """

    identifier: str = Field(min_length=1)
    identifier_type: Literal["email", "user_key"]


class IncomingReport(ContractModel):
    """A raw, unsanitized report as delivered by the connector gateway.

    Same structure for every source, sources differ only in which optional
    fields (text, photos) are filled.
    """

    id: str = Field(min_length=1)
    received_at: AwareDatetime  # must carry a timezone, UTC expected
    source: Source
    location: Location
    text: str | None = None
    photos: list[Photo] = Field(default_factory=list)
    user: User
