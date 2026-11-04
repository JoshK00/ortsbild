from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from classification.models import Classification
from classification.service import Classifier
from models.incoming_report import IncomingReport
from models.sanitized_report import SanitizedReport
from privacy.report_status import ReportStatusStore
from privacy.service import process_report


class ReportState(TypedDict, total=False):
    """The work sheet of the whole chain: it starts with the raw report and grows with every stage.

    total=False: only `report` is there at the start. The privacy keys come from the privacy graph.
    """

    report: IncomingReport
    status: Literal["running", "blocked_privacy", "rejected"]  # the outcome of the privacy layer
    block_reason: str
    reject_reason: str
    sanitized_report: SanitizedReport  # from here on this is the only form of the report
    classification: Classification | None  # None if the classification failed, it is repeated later


def make_privacy_node(privacy_graph, status_store: ReportStatusStore):
    """The first stage: the privacy graph, with its statuses and the sanitized report kept in the store."""

    def privacy_node(state: ReportState) -> dict:
        result = process_report(state["report"], privacy_graph, status_store)
        update = {key: result[key] for key in ("status", "block_reason", "reject_reason", "sanitized_report") if key in result}
        if "sanitized_report" in update:
            status_store.save_sanitized(state["report"].id, update["sanitized_report"].model_dump(mode="json"))
        return update

    return privacy_node


def make_classify_node(classifier: Classifier, status_store: ReportStatusStore):
    """The second stage: category, lane and emergency of the sanitized report. It only ever sees the sanitized form."""

    def classify_node(state: ReportState) -> dict:
        report = state["sanitized_report"]
        classification = classifier.classify(report)
        if classification is not None:
            status_store.save_classification(report.id, classification.model_dump(mode="json"))
        return {"classification": classification}

    return classify_node


def after_privacy(state: ReportState) -> str:
    """Only a report that passed the privacy layer goes on. Blocked and rejected reports end here."""
    return "classify" if "sanitized_report" in state else END


def build_report_graph(privacy_graph, classifier: Classifier, status_store: ReportStatusStore):
    """The orchestrator: the stages of one report, in order.

    TODO: Add the next stages behind `classify`, each as one more node with a router in front of it:
    emergency (stop, only the hint to call 110 / 112), duplicate check, research of the responsible authority,
    policy code, drafting, the approval pause (a LangGraph interrupt) and sending (docs/documentation.md, section 3).
    """
    graph = StateGraph(ReportState)
    graph.add_node("privacy", make_privacy_node(privacy_graph, status_store))
    graph.add_node("classify", make_classify_node(classifier, status_store))
    graph.add_edge(START, "privacy")
    graph.add_conditional_edges("privacy", after_privacy, {"classify": "classify", END: END})
    graph.add_edge("classify", END)
    return graph.compile()
