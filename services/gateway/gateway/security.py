"""API key check for the app channel (one key per app build in the MVP)."""

import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(request: Request, api_key: str | None = Depends(api_key_header)) -> None:
    allowed = [k.get_secret_value() for k in request.app.state.settings.api_keys]
    if not allowed:
        return  # no keys configured: local development only
    if api_key and any(secrets.compare_digest(api_key, key) for key in allowed):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "invalid_api_key", "message": "Missing or invalid X-API-Key header."},
    )
