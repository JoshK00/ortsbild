"""The gateway together with the real backend code (backend/), both in this process, with in-memory storage.

This checks the contract between the two: what the gateway sends is what the backend accepts, and the app gets the
same answer as from the backend alone. It needs the dependencies of the backend (backend/requirements.txt) and is
skipped without them, for example in the CI of the gateway.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("langgraph", reason="needs the dependencies of the backend")
pytest.importorskip("jwt", reason="needs the dependencies of the backend")

BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from api.main import create_app as create_backend  # noqa: E402
from api.reports import Services  # noqa: E402
from auth.apple import AppleIdentity  # noqa: E402
from auth.sessions import AuthManager, InMemoryRefreshTokenStore  # noqa: E402
from auth.tokens import TokenIssuer  # noqa: E402
from classification.provider import RuleBasedProvider  # noqa: E402
from classification.service import Classifier  # noqa: E402
from drafting.provider import TemplateDraftProvider  # noqa: E402
from drafting.service import Drafter  # noqa: E402
from orchestrator.graph import build_followup_graph, build_reclassify_graph, build_report_graph  # noqa: E402
from privacy.detectors import PatternDetector  # noqa: E402
from privacy.graph import build_privacy_graph  # noqa: E402
from privacy.photo_store import InMemoryPhotoStore  # noqa: E402
from privacy.pseudonyms import InMemoryPseudonymStore  # noqa: E402
from privacy.report_status import InMemoryReportStatusStore  # noqa: E402
from research.registry import InMemoryRegistryStore  # noqa: E402
from research.service import Researcher  # noqa: E402

from gateway.backend import BackendClient  # noqa: E402
from gateway.main import create_app as create_gateway  # noqa: E402
from tests.conftest import FORM, make_image  # noqa: E402

KEY = "gateway-key-for-tests"


class AnyAppleToken:
    def verify(self, identity_token, raw_nonce):
        return AppleIdentity(subject=identity_token)


class NoFace:
    def detect(self, image):
        return []


@pytest.fixture
def stack():
    """Backend and gateway, wired as in docker compose: one photo storage, the gateway calls the backend's entrance."""
    photos, status = InMemoryPhotoStore(), InMemoryReportStatusStore()
    auth = AuthManager(AnyAppleToken(), TokenIssuer("x" * 40), InMemoryRefreshTokenStore(), "pseudonym-secret")
    privacy = build_privacy_graph([PatternDetector()], photos, InMemoryPseudonymStore("s"), face_detector=NoFace())
    researcher, drafter = Researcher(InMemoryRegistryStore(), None), Drafter(TemplateDraftProvider())
    classifier = Classifier(RuleBasedProvider(), photos)
    services = Services(
        build_report_graph(privacy, classifier, researcher, drafter, status),
        photos,
        status,
        InMemoryPseudonymStore("s"),
        auth,
        build_followup_graph(researcher, drafter, status),
        build_reclassify_graph(classifier, researcher, drafter, status),
        [PatternDetector()],
    )
    backend_app = create_backend(
        checks={}, services=services, configure_logging=False, gateway_key=KEY, demo_reporters=[]
    )
    with TestClient(backend_app) as backend:
        gateway = TestClient(
            create_gateway(raw_store=photos, backend=BackendClient("http://testserver", KEY, 10, http=backend))
        )
        token = backend.post("/v1/auth/apple", json={"identity_token": "anna", "nonce": "n"}).json()["access_token"]
        yield backend, gateway, {"Authorization": f"Bearer {token}"}, photos, status


def test_a_report_through_the_gateway_runs_the_whole_chain(stack):
    backend, gateway, token, photos, status = stack
    data = {**FORM, "text": "Schlagloch auf der Straße", "municipality": "Stuttgart", "street": "Königstraße"}
    response = gateway.post(
        "/v1/reports", data=data, files={"photo": ("p.jpg", make_image(), "image/jpeg")}, headers=token
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "sanitized" and payload["classification"] is not None
    report_id = payload["id"]
    assert status.get(report_id).status in ("classified", "needs_input", "researched", "drafted")
    # the privacy layer took the raw photo and deleted it, the clean copy exists
    assert not [ref for ref in photos.files if ref.startswith("raw/")]
    assert photos.load(f"clean/{report_id}/p1.jpg")
    # the app reaches the report on its usual way, straight at the backend
    assert backend.get(f"/v1/reports/{report_id}", headers=token).json()["id"] == report_id
    assert backend.get(f"/v1/reports/{report_id}/photos/p1", headers=token).status_code == 200


def test_the_answer_is_the_same_as_from_the_backend_alone(stack):
    backend, gateway, token, _, _ = stack
    direct = backend.post("/v1/reports", data={**FORM, "text": "Laterne kaputt"}, headers=token).json()
    through = gateway.post(
        "/v1/reports", data={**FORM, "client_report_id": "report-0002", "text": "Laterne kaputt"}, headers=token
    ).json()
    assert set(direct) == set(through)
    assert direct["classification"] == through["classification"]


def test_a_retry_through_the_gateway_creates_nothing_new_and_leaves_no_raw_photo(stack):
    _, gateway, token, photos, _ = stack
    files = {"photo": ("p.jpg", make_image(), "image/jpeg")}
    first = gateway.post("/v1/reports", data=FORM, files=files, headers=token).json()
    again = gateway.post("/v1/reports", data=FORM, files=files, headers=token).json()
    assert again["id"] == first["id"]
    assert not [ref for ref in photos.files if ref.startswith("raw/")]


def test_without_a_valid_token_the_backend_refuses_and_no_raw_photo_stays(stack):
    _, gateway, _, photos, _ = stack
    files = {"photo": ("p.jpg", make_image(), "image/jpeg")}
    response = gateway.post("/v1/reports", data=FORM, files=files, headers={"Authorization": "Bearer forged"})
    assert response.status_code == 401
    assert photos.files == {}
