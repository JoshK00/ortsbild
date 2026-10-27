from typing import Literal

from pydantic import AwareDatetime, Field

from models.incoming_report import ContractModel, Location, Photo, SourceType

RedactionStep = Literal[
    "strip_metadata",
    "sanitize_text",
    "sanitize_photos",
    "pseudonymize_user",
]

RedactionKind = Literal[
    "face",
    "plate",
    "name",
    "address",
    "organization",
    "email",
    "phone",
    "iban",
    "exif",
    "user_identifier",
]


class RedactionEntry(ContractModel):
    """One line of the redaction log: which step removed what, and how often.

    Never contains the removed content itself, otherwise the log would leak it again.
    """

    step: RedactionStep
    kind: RedactionKind
    count: int = Field(ge=1)
    # None for deterministic steps without a detector (e.g. removing EXIF data)
    confidence: float | None = Field(default=None, ge=0, le=1)


class RedactionLog(ContractModel):
    """Everything the privacy layer removed from one report."""

    entries: list[RedactionEntry] = Field(default_factory=list)


class SanitizedReport(ContractModel):
    """The report after the privacy layer, the only form later agents may see.

    There is deliberately no user field: the plain identifier is replaced by a pseudonym.
    extra="forbid" (from ContractModel) rejects a leftover `user` field.
    """

    id: str = Field(min_length=1)  # same id as the IncomingReport
    received_at: AwareDatetime
    source_type: SourceType
    location: Location  # unchanged, it is the location of the defect
    text: str | None = None  # placeholders instead of personal data
    photos: list[Photo] = Field(default_factory=list)  # blurred
    pseudonym: str = Field(min_length=1)
    redaction_log: RedactionLog
