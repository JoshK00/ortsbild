import dataclasses
import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from auth.sessions import AuthManager, SessionError
from auth.tokens import AccessClaims, TokenError

logger = logging.getLogger("ortsbild.api")


class AppleLoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_token: str = Field(min_length=1, max_length=8000)
    nonce: str = Field(min_length=1, max_length=200)  # the raw nonce, Apple got its SHA-256


class RefreshBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=200)


def make_current_user(get_auth: Callable[[], AuthManager]) -> Callable[..., AccessClaims]:
    """The dependency that protects an endpoint: it needs `Authorization: Bearer <access token>`.

    The token must be valid and its session must not be ended (logout, deleted account).
    """
    bearer = HTTPBearer(auto_error=False)

    def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> AccessClaims:
        unauthorized = HTTPException(401, "sign in first", headers={"WWW-Authenticate": "Bearer"})
        if credentials is None:
            raise unauthorized
        auth = get_auth()
        try:
            claims = auth.issuer.verify(credentials.credentials)
        except TokenError:
            raise unauthorized from None
        if not auth.session_active(claims.session_id):
            raise unauthorized
        return claims

    return current_user


def create_auth_router(get_auth: Callable[[], AuthManager], current_user: Callable[..., AccessClaims]) -> APIRouter:
    """Sign in with Apple, refresh, logout. The app never sends a password or an API key."""
    router = APIRouter(prefix="/v1/auth")

    @router.post("/apple")
    def login_with_apple(body: AppleLoginBody) -> dict:
        """Swap the identity token of Apple for our own session: a short access token and a refresh token."""
        try:
            return dataclasses.asdict(get_auth().login_apple(body.identity_token, body.nonce))
        except SessionError as error:
            logger.warning("login refused: %s", error)
            raise HTTPException(401, "sign in was refused") from None

    @router.post("/refresh")
    def refresh(body: RefreshBody) -> dict:
        """Swap a refresh token for a new pair. The old refresh token is dead after this."""
        try:
            return dataclasses.asdict(get_auth().refresh(body.refresh_token))
        except SessionError as error:
            logger.warning("refresh refused: %s", error)
            raise HTTPException(401, "sign in again") from None

    @router.post("/logout", status_code=204)
    def logout(body: RefreshBody) -> Response:
        """End this session. Always 204, an unknown token is not a reason to tell the caller anything."""
        get_auth().logout(body.refresh_token)
        return Response(status_code=204)

    return router
