import logging

from models.incoming_report import IncomingReport
from privacy.report_status import ReportStatusStore

logger = logging.getLogger("ortsbild.privacy")


def process_report(report: IncomingReport, graph, status_store: ReportStatusStore) -> dict:
    """Run one report through the privacy graph and keep its status up to date.

    processing -> sanitized, or blocked_privacy with the reason. An unexpected error that no
    step caught is also recorded as blocked, then raised again.
    """
    source_type = report.source.type
    status_store.set_status(report.id, "processing", source_type)
    try:
        result = graph.invoke({"report": report})
    except Exception as error:
        logger.error("privacy graph crashed: report_id=%s error=%s", report.id, type(error).__name__)
        status_store.set_status(
            report.id, "blocked_privacy", source_type, f"graph: {type(error).__name__}"
        )
        raise
    if result.get("status") == "blocked_privacy":
        status_store.set_status(report.id, "blocked_privacy", source_type, result.get("block_reason"))
    else:
        status_store.set_status(report.id, "sanitized", source_type)
    return result
