import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from classification.models import Category
from models.incoming_report import ContractModel

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


class Channel(ContractModel):
    """How to reach the authority. `target` is an address (email) or a web address (web_form, open311)."""

    type: Literal["email", "web_form", "open311"]
    target: str = Field(min_length=3, max_length=300)

    @model_validator(mode="after")
    def target_fits_the_type(self) -> "Channel":
        if self.type == "email":
            if not EMAIL.match(self.target):
                raise ValueError("an email channel needs an email address")
        elif urlparse(self.target).scheme != "https" or not urlparse(self.target).netloc:
            raise ValueError("a web channel needs an https address")
        return self


class ResearchQuery(ContractModel):
    """Everything that leaves our server for a research, and nothing else.

    No text, no photo, no pseudonym, no coordinates, no street: the research only needs to know the place
    and what kind of defect it is.
    """

    category: Category
    country_code: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    municipality: str = Field(min_length=1, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    exclude: list[str] = Field(default_factory=list)  # authorities the user already refused ("wrong authority")


class ResearchResult(ContractModel):
    """The answer of the research. Every answer carries the sources it rests on."""

    authority: str = Field(min_length=1, max_length=200)
    channel: Channel | None = None  # None: the authority is known but no way to reach it was found
    language: str | None = Field(default=None, pattern=r"^[A-Za-z]{2,3}$")  # of the place, for the draft
    sources: list[str] = Field(min_length=1)  # web addresses that support the answer
    confidence: float = Field(ge=0, le=1)
    origin: Literal["registry", "web"] = "web"  # where the answer came from

    @field_validator("sources")
    @classmethod
    def sources_are_https_addresses(cls, sources: list[str]) -> list[str]:
        for source in sources:
            parsed = urlparse(source)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("a source must be an https address")
        return sources
