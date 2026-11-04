"""FastAPI application factory.

Run locally:  uvicorn --factory gateway.main:create_app --reload
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .api import reports
from .config import Settings, get_settings
from .db import ReportRepository
from .ingest import IngestService
from .storage import Storage, build_storage

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, storage: Storage | None = None) -> FastAPI:
    settings = settings or get_settings()
    repo = ReportRepository.from_url(settings.database_url)
    storage = storage or build_storage(settings)

    app = FastAPI(
        title="Connector Gateway",
        version=__version__,
        description="Receives citizen reports from all channels and stores them in one canonical format.",
    )
    app.state.settings = settings
    app.state.repo = repo
    app.state.ingest = IngestService(settings, repo, storage)
    app.include_router(reports.router)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Same error shape as every other error: {"detail": {"code", "message", ...}}
        fields = [".".join(str(p) for p in err["loc"] if p != "body") for err in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "validation_error",
                    "message": "Invalid or missing fields: " + ", ".join(fields),
                    "fields": fields,
                }
            },
        )

    @app.get("/health", tags=["ops"], summary="Liveness check")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    if not settings.api_keys:
        log.warning("GATEWAY_API_KEYS is empty: the API accepts requests without a key (dev only).")
    return app
