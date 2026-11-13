import re
from dataclasses import dataclass
from typing import Protocol

from models.sanitized_report import RedactionKind


@dataclass(frozen=True)
class Entity:
    """A piece of personal data found in a text: where it is and what it is.

    start and end are character positions (end is exclusive), so text[start:end] is the hit.
    The content itself is never stored here beyond the text it was found in.
    """

    start: int
    end: int
    kind: RedactionKind
    confidence: float | None = None  # None for rule-based hits without a score


class TextDetector(Protocol):
    """Anything that can find personal data in a text. Detectors are interchangeable."""

    def detect(self, text: str) -> list[Entity]: ...


# ---------------------------------------------------------------------------
# Rule-based detector: patterns with checksums, deterministic and fast
# ---------------------------------------------------------------------------

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+49|0049|0)[\s/-]?\d{2,5}[\s/-]?\d{3,9}(?!\w)")
IBAN_PATTERN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
# German license plate, e.g. "M-AB 1234" or "HH XY 99E"
PLATE_PATTERN = re.compile(r"\b[A-ZÄÖÜ]{1,3}[- ][A-Z]{1,2}[ -]?\d{1,4}[EH]?\b")


def is_valid_iban(iban: str) -> bool:
    """Check the IBAN checksum (mod 97), so random letter-digit strings are not flagged."""
    compact = iban.replace(" ", "")
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(char, 36)) for char in rearranged)  # A=10 ... Z=35
    return int(digits) % 97 == 1


class PatternDetector:
    """Finds structured personal data with patterns: email, phone, IBAN, license plate."""

    def detect(self, text: str) -> list[Entity]:
        entities = []
        for match in EMAIL_PATTERN.finditer(text):
            entities.append(Entity(match.start(), match.end(), "email"))
        for match in PHONE_PATTERN.finditer(text):
            entities.append(Entity(match.start(), match.end(), "phone"))
        for match in IBAN_PATTERN.finditer(text):
            if is_valid_iban(match.group()):
                entities.append(Entity(match.start(), match.end(), "iban"))
        for match in PLATE_PATTERN.finditer(text):
            entities.append(Entity(match.start(), match.end(), "plate"))
        return entities


# ---------------------------------------------------------------------------
# Model-based detector: GLiNER2-PII, finds names and free-text identifiers
# ---------------------------------------------------------------------------

GLINER2_MODEL = "fastino/gliner2-privacy-filter-PII-multi"

# model label -> our redaction kind
GLINER2_LABELS: dict[str, RedactionKind] = {
    "person": "name",
    "street_address": "address",
    "address": "address",
    "email": "email",
    "phone_number": "phone",
    "license_number": "plate",
    "iban": "iban",
}


class Gliner2Detector:
    """Finds personal data with the small local GLiNER2-PII model (CPU, no external call).

    The model is loaded on first use. The first load downloads it from Hugging Face.
    TODO: Check that the model is safe to call from several threads at once.
    """

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self._model = None

    def detect(self, text: str) -> list[Entity]:
        if self._model is None:
            from gliner2 import GLiNER2  # imported here, loading torch takes a while

            self._model = GLiNER2.from_pretrained(GLINER2_MODEL)
        result = self._model.extract_entities(
            text,
            list(GLINER2_LABELS),
            threshold=self.threshold,
            include_confidence=True,
            include_spans=True,
        )
        entities = []
        for label, hits in result["entities"].items():
            for hit in hits:
                entities.append(
                    Entity(hit["start"], hit["end"], GLINER2_LABELS[label], hit["confidence"])
                )
        return entities
