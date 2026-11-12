import re

from pydantic import AwareDatetime, Field, model_validator

from models.incoming_report import ContractModel, Location, Photo, Source

REPORT_ID_PATTERN = r"^[0-9a-f]{32}$"
CLIENT_REPORT_ID_PATTERN = r"^[A-Za-z0-9-]+$"
PHOTO_ID_PATTERN = re.compile(r"^p[0-9]{1,2}$")
PHOTO_EXTENSIONS = ("jpg", "png", "heic")


class GatewaySubmission(ContractModel):
    """A report as the connector gateway (services/gateway) hands it to the backend: an `IncomingReport` without its user.

    The user is not taken from the gateway. The gateway passes the token of the signed-in user on, and the backend checks it and
    adds the user itself, exactly as for a report that comes straight from the app. `client_report_id` is the id the app made up,
    it makes a retry safe (see `ReportStatusStore.claim`).

    The gateway stores the raw photos before it sends this, at refs of the form "raw/<id>/p<n>.<ext>". Only refs inside the raw
    folder of this very report are accepted: the privacy layer reads and later deletes every ref it gets, so a ref to another
    report's file must never come in here.
    """

    client_report_id: str = Field(min_length=8, max_length=64, pattern=CLIENT_REPORT_ID_PATTERN)
    id: str = Field(pattern=REPORT_ID_PATTERN)
    received_at: AwareDatetime
    source: Source
    location: Location
    text: str | None = Field(default=None, max_length=5000)
    # TODO: Decide the limit of photos per report together with the contract (models/incoming_report.py, Photo).
    photos: list[Photo] = Field(default_factory=list)

    @model_validator(mode="after")
    def refs_stay_in_the_raw_folder_of_this_report(self) -> "GatewaySubmission":
        folder = f"raw/{self.id}/"
        if self.source.raw_ref != folder:
            raise ValueError("source.raw_ref must be the raw folder of this report")
        seen = set()
        for photo in self.photos:
            if not PHOTO_ID_PATTERN.match(photo.id) or photo.id in seen:
                raise ValueError("photo ids must be unique and look like p1, p2, ...")
            seen.add(photo.id)
            if photo.ref not in {f"{folder}{photo.id}.{extension}" for extension in PHOTO_EXTENSIONS}:
                raise ValueError("a photo ref must point into the raw folder of this report")
        if not self.photos and not (self.text and self.text.strip()):
            raise ValueError("a report needs a photo or a text")
        return self
