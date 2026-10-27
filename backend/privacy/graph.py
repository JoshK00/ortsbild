from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from models.incoming_report import IncomingReport


class PrivacyState(TypedDict):
    """The work sheet that is passed from step to step."""

    report: IncomingReport
    summary: str


def inspect_report(state: PrivacyState) -> dict:
    """First step: read the report and describe it in one sentence.

    A node receives the whole state and returns only what it changes.
    """
    report = state["report"]
    summary = (
        f"report {report.id} from {report.source.type}: "
        f"{len(report.photos)} photo(s), text: {'yes' if report.text else 'no'}"
    )
    return {"summary": summary}


def build_privacy_graph():
    """Wire the steps together and return the runnable graph."""
    graph = StateGraph(PrivacyState)
    graph.add_node("inspect_report", inspect_report)
    graph.add_edge(START, "inspect_report")
    graph.add_edge("inspect_report", END)
    # TODO: Replace inspect_report step by step with the real steps (strip_metadata, ...)
    return graph.compile()
