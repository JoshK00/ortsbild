from pathlib import Path

from classification.evaluation import format_summary, load_cases, run_cases, summarize
from classification.models import CATEGORIES, Classification
from classification.provider import RuleBasedProvider
from classification.service import Classifier

CASES_FILE = Path(__file__).resolve().parent.parent / "eval" / "classification_cases.jsonl"


class Fixed:
    """A provider that always gives the same answer."""

    def __init__(self, **values):
        self.values = {"category": "pothole", "lane": "hazard", "emergency": False, "confidence": 0.9, **values}

    def classify(self, data):
        return Classification(**self.values)


def case(case_id, category, lane="hazard", emergency=False, text="Schlagloch", tags=()):
    return {"id": case_id, "text": text, "category": category, "lane": lane, "emergency": emergency, "tags": list(tags)}


def run(provider, cases):
    return summarize(run_cases(cases, lambda store: Classifier(provider, store)))


# ---------------------------------------------------------------------------
# The shipped cases
# ---------------------------------------------------------------------------


def test_the_shipped_cases_are_well_formed():
    cases = load_cases(CASES_FILE)
    assert len(cases) >= 40
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert c["category"] is None or c["category"] in CATEGORIES
        assert (c["category"] is None) == (c["lane"] is None)
        assert isinstance(c["emergency"], bool) and c.get("text")


def test_the_shipped_cases_cover_every_category_emergencies_injection_and_false_alarms():
    cases = load_cases(CASES_FILE)
    for category in CATEGORIES:
        assert sum(1 for c in cases if c["category"] == category) >= 4, category
    tags = {tag for c in cases for tag in c.get("tags", [])}
    assert {"emergency", "injection", "no_alarm"} <= tags


def test_the_stand_in_finds_every_emergency_of_the_shipped_cases():
    """The keyword search is the second line, on our own cases it must not miss one."""
    summary = summarize(run_cases(load_cases(CASES_FILE), lambda store: Classifier(RuleBasedProvider(), store)))
    assert summary["emergency_recall"] == 1.0 and summary["false_alarm_rate"] == 0.0


# ---------------------------------------------------------------------------
# The numbers
# ---------------------------------------------------------------------------


def test_accuracy_counts_only_cases_with_an_expected_category():
    summary = run(Fixed(), [case("a", "pothole"), case("b", "tree"), case("c", None, None, True, "Feuer")])
    assert summary["category_accuracy"] == 0.5


def test_emergency_recall_and_false_alarms():
    cases = [case("a", None, None, True, "Feuer im Park"), case("b", None, None, True, "ruhig, aber der Mann ist leider ganz plötzlich still"), case("c", "pothole")]
    summary = run(Fixed(emergency=False), cases)
    assert summary["emergency_recall"] == 0.5  # the keyword search finds the first one, nothing finds the second
    assert summary["false_alarm_rate"] == 0.0
    assert run(Fixed(emergency=True), cases)["false_alarm_rate"] == 1.0


def test_a_failed_classification_counts_as_wrong_and_as_a_missed_emergency():
    class Broken:
        def classify(self, data):
            raise RuntimeError("down")

    summary = run(Broken(), [case("a", "pothole"), case("b", None, None, True, "ein Mann liegt da, es ist ernst")])
    assert summary["failed"] == 2 and summary["category_accuracy"] == 0.0 and summary["emergency_recall"] == 0.0


def test_injection_cases_that_change_the_result_are_counted():
    cases = [case("a", "pothole", tags=["injection"]), case("b", "tree", tags=["injection"])]
    assert run(Fixed(), cases)["injection_changed"] == 1


def test_the_report_names_the_misses_and_the_wrong_categories():
    report = format_summary(run(Fixed(emergency=False), [case("a", "tree"), case("b", None, None, True, "ein Mann ist ganz still")]))
    assert "MISS" in report and "tree -> pothole" in report


def test_a_photo_case_is_loaded_from_the_photo_folder(tmp_path):
    from tests.image_helpers import make_jpeg

    (tmp_path / "hole.jpg").write_bytes(make_jpeg())
    seen = []

    class Recording(Fixed):
        def classify(self, data):
            seen.append(data)
            return super().classify(data)

    photo_case = {"id": "p1", "photo": "hole.jpg", "category": "pothole", "lane": "hazard", "emergency": False, "tags": []}
    run_cases([photo_case], lambda store: Classifier(Recording(), store), tmp_path)
    assert seen[0].photo and seen[0].text is None
