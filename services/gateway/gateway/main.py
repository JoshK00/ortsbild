"""The gateway app.

Run locally:  uvicorn --factory gateway.main:create_app --port 8080
"""

from fastapi import FastAPI

from . import __version__
from .app_channel import router as app_router
from .backend import BackendClient
from .config import Settings, get_settings
from .raw_store import RawPhotoStore, s3_raw_store


def create_app(
    settings: Settings | None = None,
    raw_store: RawPhotoStore | None = None,
    backend: BackendClient | None = None,
) -> FastAPI:
    """Without arguments the real parts are built from the environment. Tests pass their own store and backend."""
    if raw_store is None or backend is None:
        settings = settings or get_settings()
    raw_store = raw_store or s3_raw_store(settings)
    backend = backend or BackendClient(
        settings.backend_url, settings.gateway_key.get_secret_value(), settings.backend_timeout_s
    )

    app = FastAPI(
        title="Kommunio Connector Gateway",
        version=__version__,
        description=(
            "Takes reports in from a channel and hands them to the backend in its format (IncomingReport). "
            "Channels: the app. TODO: email and partner apps."
        ),
    )
    app.state.raw_store = raw_store
    app.state.backend = backend
    app.include_router(app_router)

    @app.get("/health", tags=["ops"], summary="Liveness check, for the compose network")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
