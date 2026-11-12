from datetime import datetime, timezone

from classification.models import Classification
from classification.provider import RuleBasedProvider
from classification.service import Classifier
from drafting.provider import TemplateDraftProvider
from drafting.service import Drafter
from models.incoming_report import IncomingReport
from orchestrator.graph import build_report_graph
from privacy.detectors import PatternDetector
from privacy.graph import build_privacy_graph
from privacy.photo_store import InMemoryPhotoStore
from privacy.pseudonyms import InMemoryPseudonymStore
from privacy.report_status import InMemoryReportStatusStore
from research.registry import InMemoryRegistryStore
from research.service import Researcher


class Order:
    """Records which stage ran, so the tests can check the order and the skipped stages."""

    def __init__(self):
        self.calls = []


class RecordingProvider:
    def __init__(self, order):
        self.order = order

    def classify(self, data):
        self.order.calls.append("classify")
        return RuleBasedProvider().classify(data)


class BrokenDetector:
    def detect(self, text):
        raise RuntimeError("detector down")


def make_report(text="Schlagloch auf dem Radweg"):
    return IncomingReport(
        id="7c9e",
        received_at=datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc),
        source={"type": "app", "connector": "app-api", "raw_ref": "raw/7c9e/"},
        location={"lat": 48.1, "lon": 11.5},
        text=text,
        user={"identifier": "key-1", "identifier_type": "user_key"},
    )


def build(detector=None):
    order, store, photos = Order(), InMemoryReportStatusStore(), InMemoryPhotoStore()
    privacy = build_privacy_graph([detector or PatternDetector()], photos, InMemoryPseudonymStore("s"))
    graph = build_report_graph(privacy, Classifier(RecordingProvider(order), photos), Researcher(InMemoryRegistryStore(), None), Drafter(TemplateDraftProvider()), store)
    return graph, store, order


def test_a_clean_report_is_sanitized_then_classified():
    graph, store, order = build()
    result = graph.invoke({"report": make_report()})
    assert result["sanitized_report"].text == "Schlagloch auf dem Radweg"
    assert isinstance(result["classification"], Classification) and result["classification"].category == "pothole"
    assert store.rows["7c9e"].status == "drafted"  # the chain ends with the draft
    assert store.get("7c9e").classification["category"] == "pothole"
    assert store.get("7c9e").sanitized["pseudonym"].startswith("rep-")


def test_a_blocked_report_stops_before_the_classification():
    graph, store, order = build(BrokenDetector())
    result = graph.invoke({"report": make_report()})
    assert result["status"] == "blocked_privacy" and "classification" not in result
    assert order.calls == []
    assert store.rows["7c9e"].status == "blocked_privacy"


def test_the_classifier_never_sees_the_raw_report():
    """Its input is the sanitized report: a phone number in the raw text is already a placeholder."""
    graph, store, _ = build()
    graph.invoke({"report": make_report("Schlagloch, 0151 2345678")})
    assert "0151" not in repr(store.get("7c9e").classification)
    assert store.get("7c9e").sanitized["text"] == "Schlagloch, <PHONE>"


# ---------------------------------------------------------------------------
# The decision after the classification
# ---------------------------------------------------------------------------

from classification.models import Classification  # noqa: E402, F811
from orchestrator.graph import needs_clarification  # noqa: E402


def classification(**values):
    return Classification(**{"category": "pothole", "lane": "hazard", "emergency": False, "confidence": 0.9, **values})


def test_a_classification_is_unclear_if_it_is_other_or_below_the_threshold():
    assert needs_clarification(classification(confidence=0.59), 0.6)
    assert not needs_clarification(classification(confidence=0.6), 0.6)  # exactly the threshold is sure enough
    assert needs_clarification(classification(category="other", confidence=1.0), 0.6)
    assert not needs_clarification(classification(), 0.6)


def test_the_ask_node_waits_for_the_user_and_the_chain_ends_there():
    graph, store, order = build()
    # The stand-in finds no word for a text about a bus: category other, so the user is asked
    result = graph.invoke({"report": make_report("Wann fährt der nächste Bus?")})
    assert result["needs_input"] is True and "research" not in result and "draft" not in result
    assert store.rows["7c9e"].status == "needs_input"
