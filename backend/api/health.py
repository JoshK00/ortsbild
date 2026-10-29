import logging
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

from privacy.detectors import TextDetector
from privacy.image_detectors import FaceDetector
from privacy.image_text import OcrEngine

logger = logging.getLogger("ortsbild.api")

REQUIRED_BUCKETS = {"raw", "clean"}
REQUIRED_TABLES = ("pseudonyms", "reports")


class HealthCheckError(Exception):
    """A failed check with a message that is safe to show (no secrets, no raw data)."""


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str  # "ok", or what is wrong: our own message, else only the error type


def run_checks(checks: dict[str, Callable[[], None]]) -> list[CheckResult]:
    """Run every check. A check passes if it does not raise.

    For an unexpected error only the error type is reported, its message could hold secrets.
    """
    results = []
    for name, check in checks.items():
        try:
            check()
            results.append(CheckResult(name, True, "ok"))
        except HealthCheckError as error:
            results.append(CheckResult(name, False, str(error)))
        except Exception as error:
            results.append(CheckResult(name, False, type(error).__name__))
    for result in results:
        if not result.ok:
            logger.warning("health check failed: name=%s detail=%s", result.name, result.detail)
    return results


def model_checks(
    face_detector: FaceDetector,
    text_detectors: list[TextDetector],
    ocr_engine: OcrEngine | None,
) -> dict[str, Callable[[], None]]:
    """One check per model: it loads and answers on a tiny input.

    The OCR is only checked when it is switched on (ocr_engine is not None).
    """
    checks: dict[str, Callable[[], None]] = {
        "face_detector": lambda: face_detector.detect(Image.new("RGB", (64, 64))) and None,
    }
    for index, detector in enumerate(text_detectors):
        checks[f"text_detector_{index}_{type(detector).__name__}"] = (
            lambda detector=detector: detector.detect("Max Mueller, 0151 2345678") and None
        )
    if ocr_engine is not None:
        checks["ocr"] = lambda: ocr_engine.read(Image.new("RGB", (200, 60), "white")) and None
    return checks


def supabase_checks(client) -> dict[str, Callable[[], None]]:
    """The storage buckets and the tables of the privacy layer are reachable."""

    def storage() -> None:
        buckets = {bucket.name for bucket in client.storage.list_buckets()}
        missing = REQUIRED_BUCKETS - buckets
        if missing:
            raise HealthCheckError(f"missing bucket: {', '.join(sorted(missing))}")

    def table(name: str) -> Callable[[], None]:
        def check() -> None:
            try:
                client.table(name).select("*").limit(1).execute()
            except Exception as error:
                raise HealthCheckError(f"table {name} not reachable ({type(error).__name__}), was its SQL run?")

        return check

    checks: dict[str, Callable[[], None]] = {"storage": storage}
    for name in REQUIRED_TABLES:
        checks[f"table_{name}"] = table(name)
    return checks
