from collections import defaultdict

from models.sanitized_report import RedactionEntry, RedactionKind
from privacy.detectors import Entity, TextDetector

PLACEHOLDERS: dict[RedactionKind, str] = {
    "name": "<PERSON>",
    "organization": "<ORGANIZATION>",
    "address": "<ADDRESS>",
    "email": "<EMAIL>",
    "phone": "<PHONE>",
    "iban": "<IBAN>",
    "plate": "<PLATE>",
}

# Kinds that are replaced in the text by default.
# TODO: "address" is left out on purpose. The street named in a report is often the
#       defect location the authority needs. Decide with the model-assisted step which
#       addresses are the defect and which are private (see docs/pseudocode/privacy-agent.md).
DEFAULT_REDACT_KINDS: frozenset[RedactionKind] = frozenset(
    {"name", "organization", "email", "phone", "iban", "plate"}
)


def merge_entities(entities: list[Entity]) -> list[Entity]:
    """Resolve overlapping hits: the longer one wins, on a tie the more confident one.

    Several detectors may find the same piece (e.g. both find the same email).
    """
    ranked = sorted(entities, key=lambda e: (-(e.end - e.start), -(e.confidence or 1.0)))
    accepted: list[Entity] = []
    for entity in ranked:
        if all(entity.end <= other.start or entity.start >= other.end for other in accepted):
            accepted.append(entity)
    return sorted(accepted, key=lambda e: e.start)


def redact_text(
    text: str,
    entities: list[Entity],
    redact_kinds: frozenset[RedactionKind] = DEFAULT_REDACT_KINDS,
) -> tuple[str, list[RedactionEntry]]:
    """Replace the hits with placeholders and describe what was removed.

    Returns the new text and log entries (kind, count, lowest confidence), never the content.
    """
    hits = [e for e in merge_entities(entities) if e.kind in redact_kinds]

    clean = text
    for entity in sorted(hits, key=lambda e: e.start, reverse=True):  # from the end, so positions stay valid
        clean = clean[: entity.start] + PLACEHOLDERS[entity.kind] + clean[entity.end :]

    grouped: dict[RedactionKind, list[Entity]] = defaultdict(list)
    for entity in hits:
        grouped[entity.kind].append(entity)
    log = []
    for kind, group in grouped.items():
        scores = [e.confidence for e in group if e.confidence is not None]
        log.append(
            RedactionEntry(
                step="sanitize_text",
                kind=kind,
                count=len(group),
                confidence=min(scores) if scores else None,
            )
        )
    return clean, log


def sanitize_text(
    text: str,
    detectors: list[TextDetector],
    redact_kinds: frozenset[RedactionKind] = DEFAULT_REDACT_KINDS,
) -> tuple[str, list[RedactionEntry]]:
    """Run all detectors over the text and redact what they find."""
    entities: list[Entity] = []
    for detector in detectors:
        entities.extend(detector.detect(text))
    return redact_text(text, entities, redact_kinds)
