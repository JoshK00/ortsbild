import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from models.incoming_report import IncomingReport, Photo
from models.sanitized_report import RedactionEntry
from privacy.detectors import Gliner2Detector, PatternDetector, TextDetector
from privacy.photo_store import PhotoStore, supabase_store_from_env
from privacy.photos import strip_photo_metadata
from privacy.text import sanitize_text


class PrivacyState(TypedDict, total=False):
    """The work sheet that is passed from step to step.

    total=False: only `report` is there at the start, the steps add the rest.
    """

    report: IncomingReport
    summary: str
    photos: list[Photo]  # photos in the clean bucket, without metadata
    text: str | None  # sanitized text, placeholders instead of personal data
    # Annotated with operator.add: every step APPENDS its entries instead of replacing the list
    redactions: Annotated[list[RedactionEntry], operator.add]
    status: Literal["running", "blocked_privacy"]
    block_reason: str


def inspect_report(state: PrivacyState) -> dict:
    """First step: read the report and describe it in one sentence.

    A node receives the whole state and returns only what it changes.
    """
    report = state["report"]
    summary = (
        f"report {report.id} from {report.source.type}: "
        f"{len(report.photos)} photo(s), text: {'yes' if report.text else 'no'}"
    )
    return {"summary": summary, "status": "running"}


def blocked(step: str, error: Exception) -> dict:
    """Fail closed: block the report. Only the error type is kept, its message could hold raw data."""
    return {"status": "blocked_privacy", "block_reason": f"{step}: {type(error).__name__}"}


def make_strip_metadata_node(store: PhotoStore):
    """Build the strip_metadata step: copy the photos to the clean bucket without EXIF."""

    def strip_metadata_node(state: PrivacyState) -> dict:
        report = state["report"]
        try:
            photos, entries = strip_photo_metadata(report.photos, report.id, store)
        except Exception as error:  # fail closed
            return blocked("strip_metadata", error)
        return {"photos": photos, "redactions": entries}

    return strip_metadata_node


def make_sanitize_text_node(detectors: list[TextDetector]):
    """Build the sanitize_text step with the given detectors (tests pass fakes)."""

    def sanitize_text_node(state: PrivacyState) -> dict:
        text = state["report"].text
        if not text:
            return {"text": None}
        try:
            clean, entries = sanitize_text(text, detectors)
        except Exception as error:  # fail closed
            return blocked("sanitize_text", error)
        return {"text": clean, "redactions": entries}

    return sanitize_text_node


def continue_or_stop(state: PrivacyState) -> str:
    """Decide the next arrow: go on, or stop because a step blocked the report."""
    return "blocked" if state.get("status") == "blocked_privacy" else "continue"


def default_detectors() -> list[TextDetector]:
    """Detectors used in production: patterns first, then the GLiNER2-PII model."""
    return [PatternDetector(), Gliner2Detector()]


def build_privacy_graph(
    detectors: list[TextDetector] | None = None,
    photo_store: PhotoStore | None = None,
):
    """Wire the steps together and return the runnable graph.

    Without arguments the production parts are used: the GLiNER2 model and Supabase.
    Tests pass fakes, so they need neither the model nor a network.
    """
    if detectors is None:
        detectors = default_detectors()
    if photo_store is None:
        photo_store = supabase_store_from_env()

    graph = StateGraph(PrivacyState)
    graph.add_node("inspect_report", inspect_report)
    graph.add_node("strip_metadata", make_strip_metadata_node(photo_store))
    graph.add_node("sanitize_text", make_sanitize_text_node(detectors))

    graph.add_edge(START, "inspect_report")
    graph.add_edge("inspect_report", "strip_metadata")
    # Fail closed: a blocked report stops here instead of reaching the next step
    graph.add_conditional_edges(
        "strip_metadata", continue_or_stop, {"continue": "sanitize_text", "blocked": END}
    )
    graph.add_edge("sanitize_text", END)
    # TODO: Add sanitize_photos, pseudonymize_user and assemble.
    # TODO: Add the blocked branch after sanitize_text too, once more steps follow it.
    return graph.compile()
