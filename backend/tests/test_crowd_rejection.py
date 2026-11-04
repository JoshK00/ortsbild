from fastapi.testclient import TestClient

from api.main import create_app
from api.reports import Services
from tests.auth_helpers import make_auth_manager, sign_in
from privacy.detectors import PatternDetector
from privacy.graph import build_privacy_graph
from privacy.image_detectors import Box
from privacy.photo_sanitize import ImageOptions
from privacy.photo_store import InMemoryPhotoStore
from privacy.pseudonyms import InMemoryPseudonymStore
from privacy.report_status import InMemoryReportStatusStore
from privacy.service import process_report
from tests.image_helpers import make_jpeg
from tests.test_privacy_pseudonyms_assemble import make_report

FORM = {"client_report_id": "crowd-report-0001", "lat": "48.1", "lon": "11.5"}


class Faces:
    """Finds the given number of faces with the given score."""

    def __init__(self, count, score=0.9):
        self.count, self.score = count, score

    def detect(self, image):
        return [Box(i * 3, 0, i * 3 + 2, 4, "face", self.score) for i in range(self.count)]


def run(faces, max_faces=10):
    store = InMemoryPhotoStore()
    store.save("raw/7c9e/p1.jpg", make_jpeg(size=(80, 20)), "image/jpeg")
    graph = build_privacy_graph(
        [PatternDetector()], store, InMemoryPseudonymStore("s"),
        face_detector=faces, image_options=ImageOptions(max_faces=max_faces),
    )
    return graph.invoke({"report": make_report()}), store


def test_a_crowd_is_rejected_and_nothing_is_kept():
    """More faces than the limit: the photo is not accepted, raw and clean copies are deleted."""
    result, store = run(Faces(12))
    assert result["status"] == "rejected" and result["reject_reason"] == "too_many_faces"
    assert "sanitized_report" not in result
    assert store.files == {}  # neither the raw nor the clean photo is left


def test_exactly_the_limit_is_still_accepted():
    """The limit itself passes, only more is a crowd."""
    result, _ = run(Faces(10))
    assert result["status"] == "running" and "sanitized_report" in result


def test_weak_boxes_do_not_make_a_crowd():
    """30 uncertain boxes (score 0.3) are blacked out, but they do not count as people."""
    result, store = run(Faces(30, score=0.3))
    assert "sanitized_report" in result
    assert any(e.kind == "face" and e.count == 30 for e in result["sanitized_report"].redaction_log.entries)


def test_rejected_report_is_recorded_as_rejected_not_blocked():
    """The operator list shows blocked reports only, a rejected photo is no case for an operator."""
    store = InMemoryReportStatusStore()
    photo_store = InMemoryPhotoStore()
    photo_store.save("raw/7c9e/p1.jpg", make_jpeg(size=(80, 20)), "image/jpeg")
    graph = build_privacy_graph(
        [PatternDetector()], photo_store, InMemoryPseudonymStore("s"),
        face_detector=Faces(12), image_options=ImageOptions(max_faces=10),
    )
    process_report(make_report(), graph, store)
    assert store.rows["7c9e"].status == "rejected" and store.rows["7c9e"].block_reason == "too_many_faces"
    assert store.list_blocked() == []


def test_api_answers_rejected_with_a_reason_code_only():
    """The app learns that the photo is not suitable and why in one word, nothing else."""
    photo_store, status_store = InMemoryPhotoStore(), InMemoryReportStatusStore()
    graph = build_privacy_graph(
        [PatternDetector()], photo_store, InMemoryPseudonymStore("s"),
        face_detector=Faces(12), image_options=ImageOptions(max_faces=10),
    )
    app = create_app(checks={}, services=Services(graph, photo_store, status_store, InMemoryPseudonymStore("s"), make_auth_manager()[0]), configure_logging=False)
    with TestClient(app) as client:
        response = client.post("/v1/reports", data=FORM, files={"photo": ("p.jpg", make_jpeg(size=(80, 20)), "image/jpeg")}, headers=sign_in(client))
    body = response.json()
    assert response.status_code == 200
    assert (body["status"], body["reason"], body["report"], body["photo_urls"]) == ("rejected", "too_many_faces", None, [])
    assert photo_store.files == {}
