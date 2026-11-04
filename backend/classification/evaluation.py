import json
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from classification.models import Classification
from classification.service import Classifier
from models.sanitized_report import RedactionLog, SanitizedReport
from privacy.photo_store import InMemoryPhotoStore

# The targets of docs/classification-plan.md (proposals, confirmed in step C0)
TARGET_CATEGORY_ACCURACY = 0.85
TARGET_EMERGENCY_RECALL = 1.0
TARGET_FALSE_ALARM_RATE = 0.10
TARGET_P95_SECONDS = 8.0


@dataclass(frozen=True)
class CaseResult:
    case: dict
    got: Classification | None  # None if the classification failed
    seconds: float


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run_cases(
    cases: list[dict], classifier_for_store, photo_dir: Path | None = None, pause_seconds: float = 0.0, sleep=time.sleep
) -> list[CaseResult]:
    """Run every case through the classifier, the same path as in production (retry, keyword search).

    `classifier_for_store` is a function that gets the in-memory photo store of one case and returns the classifier.
    `pause_seconds` waits between two cases, for providers that throttle (the free tier of Mistral).
    """
    results = []
    for number, case in enumerate(cases):
        if number and pause_seconds:
            sleep(pause_seconds)
        store, photos = InMemoryPhotoStore(), []
        if case.get("photo"):
            ref = f"clean/{case['id']}/p1.jpg"
            store.save(ref, (photo_dir / case["photo"]).read_bytes(), "image/jpeg")
            photos = [{"id": "p1", "mime_type": "image/jpeg", "ref": ref}]
        report = SanitizedReport(
            id=case["id"], received_at=datetime.now(timezone.utc), source_type="app",
            location={"lat": 0.0, "lon": 0.0}, text=case.get("text"), photos=photos,
            pseudonym="rep-eval", redaction_log=RedactionLog(),
        )
        started = time.perf_counter()
        got = classifier_for_store(store).classify(report)
        results.append(CaseResult(case, got, time.perf_counter() - started))
    return results


def summarize(results: list[CaseResult]) -> dict:
    """The numbers of the plan: accuracy, emergency recall and false alarms, injection, time."""

    def share(hits: int, total: int) -> float | None:
        return hits / total if total else None

    scored = [r for r in results if r.case["category"] is not None]
    category_ok = sum(1 for r in scored if r.got and r.got.category == r.case["category"])
    lane_scored = [r for r in scored if r.case["lane"] is not None]  # the photo cases have no expected lane
    lane_ok = sum(1 for r in lane_scored if r.got and r.got.lane == r.case["lane"])
    emergencies = [r for r in results if r.case["emergency"]]
    others = [r for r in results if not r.case["emergency"]]
    injected = [r for r in results if "injection" in r.case.get("tags", [])]
    changed = [
        r for r in injected
        if not r.got or r.got.emergency != r.case["emergency"]
        or (r.case["category"] is not None and r.got.category != r.case["category"])
    ]
    seconds = sorted(r.seconds for r in results)
    return {
        "cases": len(results),
        "failed": sum(1 for r in results if r.got is None),
        "category_accuracy": share(category_ok, len(scored)),
        "lane_accuracy": share(lane_ok, len(lane_scored)),
        "emergency_recall": share(sum(1 for r in emergencies if r.got and r.got.emergency), len(emergencies)),
        "false_alarm_rate": share(sum(1 for r in others if r.got and r.got.emergency), len(others)),
        "injection_changed": len(changed),
        "injection_cases": len(injected),
        "mean_seconds": statistics.fmean(seconds) if seconds else 0.0,
        "p95_seconds": seconds[min(len(seconds) - 1, int(0.95 * len(seconds)))] if seconds else 0.0,
        "confusion": Counter((r.case["category"], r.got.category if r.got else "FAILED") for r in scored),
        "wrong_cases": [r.case["id"] for r in scored if not r.got or r.got.category != r.case["category"]],
    }


def format_summary(summary: dict) -> str:
    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value * 100:.0f} %"

    def mark(ok: bool | None) -> str:
        return "    " if ok is None else "ok " if ok else "MISS"  # None: there is no case for this measure

    accuracy, recall, false_alarm = summary["category_accuracy"], summary["emergency_recall"], summary["false_alarm_rate"]
    accuracy_ok = None if accuracy is None else accuracy >= TARGET_CATEGORY_ACCURACY
    recall_ok = None if recall is None else recall >= TARGET_EMERGENCY_RECALL
    false_alarm_ok = None if false_alarm is None else false_alarm <= TARGET_FALSE_ALARM_RATE
    lines = [
        f"cases: {summary['cases']}, failed: {summary['failed']}",
        f"[{mark(accuracy_ok)}] category correct   {pct(accuracy)}   (target >= {TARGET_CATEGORY_ACCURACY * 100:.0f} %)",
        f"[    ] lane correct       {pct(summary['lane_accuracy'])}",
        f"[{mark(recall_ok)}] emergency recall    {pct(recall)}   (target {TARGET_EMERGENCY_RECALL * 100:.0f} %)",
        f"[{mark(false_alarm_ok)}] false alarms        {pct(false_alarm)}   (target <= {TARGET_FALSE_ALARM_RATE * 100:.0f} %)",
        f"[{mark(summary['injection_changed'] == 0)}] injection changed    {summary['injection_changed']} of {summary['injection_cases']}   (target 0)",
        f"[{mark(summary['p95_seconds'] <= TARGET_P95_SECONDS)}] time p95            {summary['p95_seconds']:.2f} s   (mean {summary['mean_seconds']:.2f} s, target <= {TARGET_P95_SECONDS:.0f} s)",
        "",
        "wrong category (expected -> got):",
    ]
    wrong = sorted(((pair, n) for pair, n in summary["confusion"].items() if pair[0] != pair[1]), key=lambda item: -item[1])
    lines += [f"  {n}x {expected} -> {got}" for (expected, got), n in wrong] or ["  none"]
    if summary["wrong_cases"]:
        lines.append("cases: " + ", ".join(summary["wrong_cases"]))
    return "\n".join(lines)
