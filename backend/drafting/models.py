from pydantic import Field

from classification.models import Category, Lane
from models.incoming_report import ContractModel
from research.models import Channel


class DraftInput(ContractModel):
    """Everything that leaves our server for the writing of a draft, and nothing else.

    No address, no coordinates, no pseudonym, no photo: the model only writes the description. The address and the
    coordinates are put into the message by our own code, so the model cannot invent or change them.
    """

    category: Category
    lane: Lane
    text: str | None = None  # sanitized text, placeholders instead of personal data
    authority: str | None = Field(default=None, max_length=200)
    language: str = Field(default="de", pattern=r"^[a-z]{2,3}$")  # the draft is written in the language of the authority


class DraftContent(ContractModel):
    """What a draft provider writes."""

    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    summary_de: str = Field(min_length=1, max_length=300)  # one sentence in German, so the user knows what is written in a language they may not read


class Draft(ContractModel):
    """The message the user approves: the text of the model plus the facts that our code added."""

    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    summary_de: str = Field(min_length=1, max_length=300)
    language: str = Field(pattern=r"^[a-z]{2,3}$")
    authority: str | None = None  # None: no authority was found, the user adds the recipient
    contact: Channel | None = None
    version: int = Field(default=1, ge=1)
