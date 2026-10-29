import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from models.incoming_report import IncomingReport, Photo
from models.sanitized_report import RedactionEntry, SanitizedReport
from privacy.assemble import assemble_report
from privacy.detectors import Gliner2Detector, PatternDetector, TextDetector
from privacy.image_detectors import FaceDetector, YuNetFaceDetector
from privacy.image_text import OcrEngine, RapidOcrEngine
from privacy.photo_sanitize import ImageOptions, sanitize_photos
from privacy.photo_store import PhotoStore, supabase_store_from_env
from privacy.photos import strip_photo_metadata
from privacy.pseudonyms import PseudonymStore, supabase_pseudonym_store_from_env
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
    pseudonym: str
    sanitized_report: SanitizedReport  # the result, only there if nothing blocked
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


def make_sanitize_photos_node(
    store: PhotoStore,
    face_detector: FaceDetector,
    options: ImageOptions,
    ocr_engine: OcrEngine | None,
    text_detectors: list[TextDetector],
):
    """Build the sanitize_photos step: black out faces (and personal text) in the clean copies."""

    def sanitize_photos_node(state: PrivacyState) -> dict:
        try:
            entries = sanitize_photos(
                state["photos"], store, face_detector, options, ocr_engine, text_detectors
            )
        except Exception as error:  # fail closed: a photo we cannot check is not passed on
            return blocked("sanitize_photos", error)
        return {"redactions": entries}

    return sanitize_photos_node


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


def make_pseudonymize_node(store: PseudonymStore):
    """Build the pseudonymize_user step: replace the plain identifier by a stable pseudonym."""

    def pseudonymize_node(state: PrivacyState) -> dict:
        user = state["report"].user
        try:
            pseudonym = store.get_or_create(user.identifier, user.identifier_type)
        except Exception as error:  # fail closed
            return blocked("pseudonymize_user", error)
        entry = RedactionEntry(step="pseudonymize_user", kind="user_identifier", count=1)
        return {"pseudonym": pseudonym, "redactions": [entry]}

    return pseudonymize_node


def make_assemble_node(photo_store: PhotoStore):
    """Build the assemble step: create the SanitizedReport, then delete the raw photos.

    TODO: Also delete the raw message (source.raw_ref, e.g. the email file) and define the
          deletion deadline and whether backups may hold raw data.
    """

    def assemble_node(state: PrivacyState) -> dict:
        report = state["report"]
        try:
            sanitized = assemble_report(
                report,
                text=state.get("text"),
                photos=state.get("photos", []),
                pseudonym=state["pseudonym"],
                redactions=state.get("redactions", []),
            )
            # Only after the sanitized report exists: a failed run keeps the raw data for the operator
            for photo in report.photos:
                photo_store.delete(photo.ref)
        except Exception as error:  # fail closed
            return blocked("assemble", error)
        return {"sanitized_report": sanitized}

    return assemble_node


def always(state: PrivacyState) -> bool:
    """For steps that have to run for every report."""
    return True


def has_photos(state: PrivacyState) -> bool:
    """True if the report carries at least one photo."""
    return bool(state["report"].photos)


def has_text(state: PrivacyState) -> bool:
    """True if the report carries free text."""
    return bool(state["report"].text)


@dataclass(frozen=True)
class Step:
    """One step of the pipeline: its name, the node, and when it has to run at all."""

    name: str
    node: Callable[[PrivacyState], dict]
    applies: Callable[[PrivacyState], bool]


def make_router(steps: list[Step], index: int):
    """Build the decision after step `index`: the next step that applies, or the end.

    A blocked report always ends. A step whose input is missing is skipped, so no
    detector runs on a report without photos or without text.
    """

    def router(state: PrivacyState) -> str:
        if state.get("status") == "blocked_privacy":
            return END
        for step in steps[index + 1 :]:
            if step.applies(state):
                return step.name
        return END

    return router


def default_detectors() -> list[TextDetector]:
    """Detectors used in production: patterns first, then the GLiNER2-PII model."""
    return [PatternDetector(), Gliner2Detector()]


def build_privacy_graph(
    detectors: list[TextDetector] | None = None,
    photo_store: PhotoStore | None = None,
    pseudonym_store: PseudonymStore | None = None,
    face_detector: FaceDetector | None = None,
    image_options: ImageOptions | None = None,
    ocr_engine: OcrEngine | None = None,
):
    """Wire the steps together and return the runnable graph.

    Without arguments the production parts are used: the GLiNER2 model and Supabase.
    Tests pass fakes, so they need neither the model nor a network.
    """
    if detectors is None:
        detectors = default_detectors()
    if photo_store is None:
        photo_store = supabase_store_from_env()
    if pseudonym_store is None:
        pseudonym_store = supabase_pseudonym_store_from_env()
    if face_detector is None:
        face_detector = YuNetFaceDetector()
    if image_options is None:
        image_options = ImageOptions()
    if ocr_engine is None and image_options.text_in_image:
        ocr_engine = RapidOcrEngine()  # only built when text in images is switched on

    # The order of this list is the order of the pipeline.
    steps = [
        Step("strip_metadata", make_strip_metadata_node(photo_store), has_photos),
        Step(
            "sanitize_photos",
            make_sanitize_photos_node(photo_store, face_detector, image_options, ocr_engine, detectors),
            has_photos,
        ),
        Step("sanitize_text", make_sanitize_text_node(detectors), has_text),
        Step("pseudonymize_user", make_pseudonymize_node(pseudonym_store), always),
        Step("assemble", make_assemble_node(photo_store), always),
    ]

    graph = StateGraph(PrivacyState)
    graph.add_node("inspect_report", inspect_report)
    for step in steps:
        graph.add_node(step.name, step.node)

    # After every node a router picks the next step that applies, or stops
    # (blocked report, nothing left to do).
    sources = ["inspect_report"] + [step.name for step in steps]
    graph.add_edge(START, "inspect_report")
    for position, source in enumerate(sources):
        targets = {step.name: step.name for step in steps[position:]}
        targets[END] = END
        graph.add_conditional_edges(source, make_router(steps, position - 1), targets)
    return graph.compile()
