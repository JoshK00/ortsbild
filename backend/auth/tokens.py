import time
from dataclasses import dataclass

import jwt

ISSUER = "ortsbild"
AUDIENCE = "ortsbild-api"
ACCESS_TOKEN_SECONDS = 3600  # one hour
MIN_SECRET_LENGTH = 32


class TokenError(Exception):
    """The access token is not accepted. The message never contains the token."""


@dataclass(frozen=True)
class AccessClaims:
    user_key: str  # pseudonymous key of the user (hash of the Apple id), never the Apple id itself
    session_id: str


class TokenIssuer:
    """Creates and checks the short access tokens that the app sends as `Authorization: Bearer`.

    HS256 with a secret that only the server knows. The token holds the user key and the session id,
    nothing else, and it lives for one hour. Longer sessions work through the refresh token.
    """

    def __init__(self, secret: str, lifetime_seconds: int = ACCESS_TOKEN_SECONDS) -> None:
        if len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"the token secret must have at least {MIN_SECRET_LENGTH} characters")
        self._secret = secret
        self.lifetime_seconds = lifetime_seconds

    def issue(self, user_key: str, session_id: str) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER, "aud": AUDIENCE, "sub": user_key, "sid": session_id,
            "iat": now, "exp": now + self.lifetime_seconds,
        }
        return jwt.encode(claims, self._secret, algorithm="HS256")

    def verify(self, token: str) -> AccessClaims:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],  # never the algorithm named in the token itself
                audience=AUDIENCE,
                issuer=ISSUER,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "sid"]},
            )
        except jwt.PyJWTError:
            raise TokenError("the access token is not valid") from None
        if not isinstance(claims["sub"], str) or not isinstance(claims["sid"], str):
            raise TokenError("the access token is not valid")
        return AccessClaims(user_key=claims["sub"], session_id=claims["sid"])
