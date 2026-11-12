from datetime import datetime, timezone

from models.incoming_report import IncomingReport
from privacy.detectors import PatternDetector
from privacy.graph import build_privacy_graph
from privacy.photo_store import InMemoryPhotoStore
from privacy.pseudonyms import InMemoryPseudonymStore
from tests.image_helpers import make_jpeg


def make_report(**overrides) -> IncomingReport:
    """Build a valid app report, tests change only what they check."""
    data = {
        "id": "7c9e",
        "received_at": datetime(2026, 10, 27, 12, 30, tzinfo=timezone.utc),
        "source": {"type": "app", "connector": "ortsbild-ios", "raw_ref": "raw/7c9e/"},
        "location": {"lat": 48.1371, "lon": 11.5754},
        "text": "The bin at the bus stop is overflowing.",
        "photos": [{"id": "p1", "mime_type": "image/jpeg", "ref": "raw/7c9e/p1.jpg"}],
        "user": {"identifier": "key-1", "identifier_type": "user_key"},
    }
    data.update(overrides)
    return IncomingReport(**data)


def test_graph_reads_the_report():
    """The report goes into the graph and the first step describes it."""
    store = InMemoryPhotoStore()
    store.save("raw/7c9e/p1.jpg", make_jpeg(), "image/jpeg")
    graph = build_privacy_graph([PatternDetector()], store, InMemoryPseudonymStore("test-secret"))
    result = graph.invoke({"report": make_report()})
    assert result["summary"] == "report 7c9e from app: 1 photo(s), text: yes"


def test_graph_handles_email_report_without_photo_and_text():
    """An email report without photo and text is read just as well."""
    graph = build_privacy_graph([PatternDetector()], InMemoryPhotoStore(), InMemoryPseudonymStore("test-secret"))
    report = make_report(
        source={"type": "email", "connector": "imap-inbox", "raw_ref": "raw/7c9e/m.eml"},
        photos=[],
        text=None,
    )
    result = graph.invoke({"report": report})
    assert result["summary"] == "report 7c9e from email: 0 photo(s), text: no"
