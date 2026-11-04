import hmac
import logging
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse

from api.health import CheckResult, model_checks, run_checks
from api.auth import create_auth_router, make_current_user
from api.reports import Services, create_reports_router
from logging_config import setup_logging

logger = logging.getLogger("ortsbild.api")


def build_production() -> tuple[Services, dict[str, Callable[[], None]]]:
    """Create the real parts (models, object storage, database) once, and their health checks."""
    from dotenv import load_dotenv

    from api.health import database_checks, s3_storage_checks
    from auth.apple import DEFAULT_BUNDLE_ID, AppleTokenVerifier
    from auth.postgres_store import PostgresRefreshTokenStore
    from auth.sessions import AuthManager
    from auth.tokens import TokenIssuer
    from classification.provider import provider_from_env
    from classification.service import Classifier
    from drafting.provider import provider_from_env as draft_provider_from_env
    from drafting.service import Drafter
    from orchestrator.graph import build_followup_graph, build_reclassify_graph, build_report_graph
    from research.postgres_registry import PostgresRegistryStore
    from research.provider import provider_from_env as research_provider_from_env
    from research.service import Researcher
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
    pseudonym_store = postgres_pseudonym_store_from_env()

    privacy_graph = build_privacy_graph(
        detectors,
        photo_store,
        pseudonym_store,
        face_detector=face_detector,
        image_options=options,
        ocr_engine=ocr_engine,
    )
    status_store = postgres_status_store_from_env()
    researcher = Researcher(PostgresRegistryStore(os.environ["DATABASE_URL"]), research_provider_from_env())
    drafter = Drafter(draft_provider_from_env())
    # Below this confidence the user is asked what the picture shows, instead of researching on a guess
    min_confidence = float(os.getenv("CLASSIFICATION_MIN_CONFIDENCE", "0.6"))
    classifier = Classifier(provider_from_env(), photo_store)
    graph = build_report_graph(privacy_graph, classifier, researcher, drafter, status_store, min_confidence)
    followup_graph = build_followup_graph(researcher, drafter, status_store)
    answer_graph = build_reclassify_graph(classifier, researcher, drafter, status_store, min_confidence)

    # Without AUTH_SECRET the app does not start: nobody can sign in, and there is no open fallback
    auth = AuthManager(
        AppleTokenVerifier(os.getenv("APPLE_BUNDLE_ID", DEFAULT_BUNDLE_ID)),
        TokenIssuer(os.environ["AUTH_SECRET"]),
        PostgresRefreshTokenStore(os.environ["DATABASE_URL"]),
        os.environ["PSEUDONYM_SECRET"],
    )
    services = Services(graph, photo_store, status_store, pseudonym_store, auth, followup_graph, answer_graph, detectors)
    checks = model_checks(face_detector, detectors, ocr_engine)
    checks.update(s3_storage_checks(photo_store.client, photo_store.buckets))
    checks.update(database_checks(os.environ["DATABASE_URL"]))
    return services, checks


def create_app(
    checks: dict[str, Callable[[], None]] | None = None,
    services: Services | None = None,
    api_key: str | None = None,
    configure_logging: bool = True,
    reports_per_hour: int | None = None,
) -> FastAPI:
    """Create the API. Without arguments it builds the real parts at startup.

    Tests pass their own checks and services and switch the logging setup off.
    The API key only opens the details of /health, the app signs in with Apple instead.
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

    HEALTH_CACHE_SECONDS = 15

    def current_api_key() -> str | None:
        return api_key if api_key is not None else os.getenv("API_KEY")

    def cached_results() -> list[CheckResult]:
        """Run the checks at most every 15 seconds, so a flood of requests cannot make the server load models and call storage and database each time."""
        cache = getattr(app.state, "health_cache", None)
        if cache is None or time.monotonic() - cache[0] > HEALTH_CACHE_SECONDS:
            cache = (time.monotonic(), run_checks(app.state.checks))
            app.state.health_cache = cache
        return cache[1]

    @app.get("/health")
    def health(x_api_key: str | None = Header(default=None)) -> JSONResponse:
        """200 if every model, the object storage and the database work, 503 otherwise.

        Everybody gets only the status. The names of the checks and what is wrong are shown
        only with the API key, they tell a stranger how the system is built.
        """
        results = cached_results()
        healthy = all(result.ok for result in results)
        content: dict = {"status": "ok" if healthy else "degraded"}
        expected = current_api_key()
        if expected and x_api_key and hmac.compare_digest(x_api_key, expected):
            content["checks"] = {r.name: {"ok": r.ok, "detail": r.detail} for r in results}
        return JSONResponse(status_code=200 if healthy else 503, content=content)

    current_user = make_current_user(lambda: app.state.services.auth)
    app.include_router(create_auth_router(lambda: app.state.services.auth, current_user))
    app.include_router(
        create_reports_router(
            get_services=lambda: app.state.services,
            current_user=current_user,
            reports_per_hour=reports_per_hour or int(os.getenv("MAX_REPORTS_PER_HOUR", "20")),
            tenant=os.getenv("TENANT_ID", "pilot"),
        )
    )
    return app
