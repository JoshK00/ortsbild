from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from classification.models import Classification
from classification.service import Classifier
from drafting.models import Draft
from drafting.service import Drafter
from models.incoming_report import IncomingReport
from models.sanitized_report import SanitizedReport
from privacy.report_status import ReportStatusStore
from privacy.service import process_report
from research.models import ResearchResult
from research.service import Researcher


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
    research: ResearchResult | None  # None if no authority was found, the user adds the recipient
    draft: Draft | None  # None if no draft was written (no defect, or the provider failed)
    needs_input: bool  # True if the picture was not clear and the user is asked, nothing is researched or drafted


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


def make_research_node(researcher: Researcher, status_store: ReportStatusStore):
    """The third stage: the responsible authority. It sees the place and the category, nothing else of the report."""

    def research_node(state: ReportState) -> dict:
        report = state["sanitized_report"]
        result = researcher.research(report, state["classification"])
        if result is not None:
            status_store.save_research(report.id, result.model_dump(mode="json"))
        return {"research": result}

    return research_node


def make_draft_node(drafter: Drafter, status_store: ReportStatusStore):
    """The fourth stage: the message for the user to approve. It works with or without an authority."""

    def draft_node(state: ReportState) -> dict:
        report = state["sanitized_report"]
        draft = drafter.draft(report, state["classification"], state.get("research"))
        if draft is not None:
            status_store.save_draft(report.id, draft.model_dump(mode="json"))
        return {"draft": draft}

    return draft_node


def needs_clarification(classification: Classification, min_confidence: float) -> bool:
    """True if the classification is not sure enough to go on: the picture shows no defect we know, or the model doubts."""
    return classification.category == "other" or classification.confidence < min_confidence


def make_ask_node(status_store: ReportStatusStore):
    """Stops the chain and waits for the answer of the user: no research and no draft on a guess."""

    def ask_node(state: ReportState) -> dict:
        report = state["sanitized_report"]
        status_store.set_status(report.id, "needs_input", report.source_type)
        return {"needs_input": True}

    return ask_node


def make_after_classify(min_confidence: float):
    """The decision after the classification: an emergency stops (only the hint to call 110 / 112, no ticket), an unclear
    picture is asked about, everything else is researched. No classification (the provider failed) stops as well."""

    def after_classify(state: ReportState) -> str:
        classification = state.get("classification")
        if classification is None or classification.emergency:
            return END
        return "ask" if needs_clarification(classification, min_confidence) else "research"

    return after_classify


def after_privacy(state: ReportState) -> str:
    """Only a report that passed the privacy layer goes on. Blocked and rejected reports end here."""
    return "classify" if "sanitized_report" in state else END


def build_report_graph(
    privacy_graph, classifier: Classifier, researcher: Researcher, drafter: Drafter, status_store: ReportStatusStore,
    min_confidence: float = 0.6,
):
    """The orchestrator: the stages of one report, in order.

    TODO: Add the next stages, each as one more node with a router in front of it: the duplicate check (before the
    research), the policy code, the approval pause (a LangGraph interrupt) and the sending (docs/documentation.md, section 3).
    """
    graph = StateGraph(ReportState)
    graph.add_node("privacy", make_privacy_node(privacy_graph, status_store))
    graph.add_edge(START, "privacy")
    graph.add_conditional_edges("privacy", after_privacy, {"classify": "classify", END: END})
    add_stages_after_privacy(graph, classifier, researcher, drafter, status_store, min_confidence)
    return graph.compile()


def add_stages_after_privacy(graph, classifier, researcher, drafter, status_store, min_confidence: float) -> None:
    """The stages from the classification on: classify, then ask, research or stop, then draft."""
    graph.add_node("classify", make_classify_node(classifier, status_store))
    graph.add_node("research", make_research_node(researcher, status_store))
    graph.add_node("ask", make_ask_node(status_store))
    graph.add_conditional_edges("classify", make_after_classify(min_confidence), {"research": "research", "ask": "ask", END: END})
    graph.add_edge("ask", END)
    graph.add_node("draft", make_draft_node(drafter, status_store))
    graph.add_edge("research", "draft")
    graph.add_edge("draft", END)


def build_reclassify_graph(
    classifier: Classifier, researcher: Researcher, drafter: Drafter, status_store: ReportStatusStore, min_confidence: float = 0.6
):
    """The chain from the classification on, for a report whose user described the problem in words. It starts with the
    sanitized report (the description is already sanitized and part of it) and can ask again if the picture is still unclear."""
    graph = StateGraph(ReportState)
    graph.add_edge(START, "classify")
    add_stages_after_privacy(graph, classifier, researcher, drafter, status_store, min_confidence)
    return graph.compile()


def build_followup_graph(researcher: Researcher, drafter: Drafter, status_store: ReportStatusStore):
    """The rest of the chain for a report whose question was answered: it starts with the classification the user settled
    and runs the research and the draft. The privacy layer and the classification already ran."""
    graph = StateGraph(ReportState)
    graph.add_node("research", make_research_node(researcher, status_store))
    graph.add_node("draft", make_draft_node(drafter, status_store))
    graph.add_edge(START, "research")
    graph.add_edge("research", "draft")
    graph.add_edge("draft", END)
    return graph.compile()
