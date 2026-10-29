import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.health import CheckResult, model_checks, run_checks
from api.reports import Services, create_reports_router
from logging_config import setup_logging

logger = logging.getLogger("ortsbild.api")


def build_production() -> tuple[Services, dict[str, Callable[[], None]]]:
    """Create the real parts (models, object storage, database) once, and their health checks."""
    from dotenv import load_dotenv

    from api.health import database_checks, s3_storage_checks
    from privacy.graph import build_privacy_graph, default_detectors
    from privacy.image_detectors import YuNetFaceDetector
    from privacy.image_text import RapidOcrEngine
    from privacy.photo_sanitize import ImageOptions
    from privacy.photo_store import s3_store_from_env
    from privacy.postgres_stores import postgres_pseudonym_store_from_env, postgres_status_store_from_env

    load_dotenv()
    detectors = default_detectors()
    # Lower = fewer missed faces but more false boxes. Tune it with FACE_SCORE_THRESHOLD in .env.prod.
    face_detector = YuNetFaceDetector(score_threshold=float(os.getenv("FACE_SCORE_THRESHOLD", "0.3")))
    options = ImageOptions(max_faces=int(os.getenv("MAX_FACES", "10")))
    ocr_engine = RapidOcrEngine() if options.text_in_image else None
    photo_store = s3_store_from_env()

    graph = build_privacy_graph(
        detectors,
        photo_store,
        postgres_pseudonym_store_from_env(),
        face_detector=face_detector,
        image_options=options,
        ocr_engine=ocr_engine,
    )
    services = Services(graph, photo_store, postgres_status_store_from_env())
    checks = model_checks(face_detector, detectors, ocr_engine)
    checks.update(s3_storage_checks(photo_store.client, photo_store.buckets))
    checks.update(database_checks(os.environ["DATABASE_URL"]))
    return services, checks


def create_app(
    checks: dict[str, Callable[[], None]] | None = None,
    services: Services | None = None,
    api_key: str | None = None,
    configure_logging: bool = True,
) -> FastAPI:
    """Create the API. Without arguments it builds the real parts at startup.

    Tests pass their own checks, services and API key and switch the logging setup off.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if configure_logging:
            setup_logging()
        if services is None and checks is None:
            app.state.services, app.state.checks = build_production()
        else:
            app.state.services, app.state.checks = services, checks or {}
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

    app.include_router(
        create_reports_router(
            get_services=lambda: app.state.services,
            get_api_key=lambda: api_key if api_key is not None else os.getenv("API_KEY"),
        )
    )
    return app
