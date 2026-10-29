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
                code = str(getattr(error, "code", ""))  # database error code, no secret in it
                if code == "42501":
                    reason = "permission denied, run the GRANT lines of its SQL file"
                elif code in ("42P01", "PGRST205"):
                    reason = "table does not exist, run its SQL file"
                else:
                    reason = f"not reachable ({type(error).__name__} {code})".strip()
                raise HealthCheckError(f"table {name}: {reason}")

        return check

    checks: dict[str, Callable[[], None]] = {"storage": storage}
    for name in REQUIRED_TABLES:
        checks[f"table_{name}"] = table(name)
    return checks


def s3_storage_checks(client, buckets: dict[str, str]) -> dict[str, Callable[[], None]]:
    """Both buckets (raw, clean) exist and the credentials may use them."""

    def check(logical: str, real: str) -> Callable[[], None]:
        def run() -> None:
            try:
                client.head_bucket(Bucket=real)
            except Exception as error:
                status = getattr(error, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
                if status == 404:
                    raise HealthCheckError(f"bucket {logical} does not exist")
                if status == 403:
                    raise HealthCheckError(f"no access to bucket {logical}, check the storage keys")
                raise

        return run

    return {f"storage_{logical}": check(logical, real) for logical, real in buckets.items()}


def database_checks(dsn: str, connect=None) -> dict[str, Callable[[], None]]:
    """The database answers and both tables of the privacy layer exist."""
    import psycopg

    connect = connect or psycopg.connect

    def database() -> None:
        with connect(dsn, connect_timeout=5) as connection:
            rows = connection.execute(
                "select table_name from information_schema.tables where table_name = any(%s)",
                (list(REQUIRED_TABLES),),
            ).fetchall()
        missing = set(REQUIRED_TABLES) - {row[0] for row in rows}
        if missing:
            raise HealthCheckError(f"missing table: {', '.join(sorted(missing))}, run the SQL files")

    return {"database": database}
