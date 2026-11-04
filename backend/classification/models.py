from typing import Literal

from pydantic import Field, model_validator

from models.incoming_report import ContractModel

# The fixed MVP list (decision D2). A municipality-specific list is a later step (plan.md 5.9).
Category = Literal["litter", "graffiti", "street_light", "playground_equipment", "pothole", "tree", "other"]
Lane = Literal["hazard", "nuisance"]

CATEGORIES: tuple[str, ...] = Category.__args__
# What the user can pick when the picture is not clear. "other" is no choice: it is the answer "nothing of these".
CLARIFICATION_CATEGORIES: tuple[str, ...] = tuple(category for category in CATEGORIES if category != "other")


class Classification(ContractModel):
    """What the classification says about a report.

    There is deliberately no free-text field (for example a reason): it would be one more place where
    personal data could leak, and nothing later in the chain uses it.
    """

    category: Category
    lane: Lane
    emergency: bool
    confidence: float = Field(ge=0, le=1)  # as reported by the model, how sure it is about the category


class ClassificationInput(ContractModel):
    """Everything that leaves our server for a classification, and nothing else.

    No coordinates, no pseudonym, no user key, no report id: classification does not need them,
    and what is not sent cannot leak at the provider.
    """

    text: str | None = None  # sanitized text, placeholders instead of personal data
    photo: bytes | None = None  # the clean photo, shrunk, always JPEG

    @model_validator(mode="after")
    def needs_text_or_photo(self) -> "ClassificationInput":
        if not (self.text and self.text.strip()) and not self.photo:
            raise ValueError("a classification needs a text or a photo")
        return self
