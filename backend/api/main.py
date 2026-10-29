import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.health import CheckResult, model_checks, run_checks
from logging_config import setup_logging

logger = logging.getLogger("ortsbild.api")


def build_production_checks() -> dict[str, Callable[[], None]]:
    """Create the real parts (models, object storage, database) and return their health checks.

    TODO: The same parts will be used by POST /reports, build them once and share them.
    """
    import os

    from dotenv import load_dotenv

    from api.health import database_checks, s3_storage_checks
    from privacy.graph import default_detectors
    from privacy.image_detectors import YuNetFaceDetector
    from privacy.photo_sanitize import ImageOptions
    from privacy.photo_store import s3_buckets_from_env, s3_client_from_env

    load_dotenv()
    options = ImageOptions()
    ocr_engine = None
    if options.text_in_image:
        from privacy.image_text import RapidOcrEngine

        ocr_engine = RapidOcrEngine()
    checks = model_checks(YuNetFaceDetector(), default_detectors(), ocr_engine)
    checks.update(s3_storage_checks(s3_client_from_env(), s3_buckets_from_env()))
    checks.update(database_checks(os.environ["DATABASE_URL"]))
    return checks


def create_app(checks: dict[str, Callable[[], None]] | None = None, configure_logging: bool = True) -> FastAPI:
    """Create the API. Without arguments it builds the real parts at startup.

    Tests pass their own checks and switch the logging setup off.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if configure_logging:
            setup_logging()
        app.state.checks = checks if checks is not None else build_production_checks()
        # Run once at startup: this loads the models, so the first real report is not slow,
        # and a missing model or table shows up in the log at once. The app starts anyway.
        results = run_checks(app.state.checks)
        logger.info("startup checks: %s", ", ".join(f"{r.name}={'ok' if r.ok else 'FAILED'}" for r in results))
        yield

    app = FastAPI(title="Ortsbild", lifespan=lifespan)

    @app.get("/health")
    def health() -> JSONResponse:
        """200 if every model, the object storage and the database work, 503 with the failing parts otherwise."""
        results: list[CheckResult] = run_checks(app.state.checks)
        healthy = all(result.ok for result in results)
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={
                "status": "ok" if healthy else "degraded",
                "checks": {r.name: {"ok": r.ok, "detail": r.detail} for r in results},
            },
        )

    return app
