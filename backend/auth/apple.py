import hashlib
import hmac
import time
from dataclasses import dataclass

import jwt

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
# The bundle id of the app, it is the "audience" Apple writes into the token.
# The server can override it with APPLE_BUNDLE_ID (see api/main.py).
DEFAULT_BUNDLE_ID = "com.Joshua-Kehrer.Ortsbild"


class AppleAuthError(Exception):
    """The identity token of Apple is not accepted. The message is safe to log, it never holds the token."""


class ThrottledJwks:
    """The public keys of Apple, loaded again at most once a minute when a token names a key we do not know.

    Without this limit the key client of PyJWT fetches Apple's list on every token with an unknown key id,
    so a stranger could keep our threads busy with forged tokens (the login endpoint is open to everybody).
    """

    def __init__(self, client=None, min_refresh_seconds: float = 60.0, clock=time.monotonic) -> None:
        self._client = client or jwt.PyJWKClient(APPLE_JWKS_URL, cache_keys=True, lifespan=3600)
        self._min_refresh = min_refresh_seconds
        self._clock = clock
        self._last_refresh = float("-inf")

    def get_signing_key_from_jwt(self, token: str):
        key_id = jwt.get_unverified_header(token).get("kid")
        for refresh in (False, True):
            if refresh:
                if self._clock() - self._last_refresh < self._min_refresh:
                    break
                self._last_refresh = self._clock()
            for key in self._client.get_signing_keys(refresh=refresh):
                if key.key_id == key_id:
                    return key
        raise jwt.PyJWKClientError("unknown key id")


@dataclass(frozen=True)
class AppleIdentity:
    """Who Apple says the user is. Only the stable, meaningless id (`sub`), no name and no email."""

    subject: str


class AppleTokenVerifier:
    """Checks the identity token that the app got from "Sign in with Apple".

    The token is a JWT signed by Apple. We check the signature against Apple's public keys, the issuer,
    the audience (our bundle id), the expiry and the nonce. Anything else is rejected.
    """

    def __init__(self, bundle_id: str = DEFAULT_BUNDLE_ID, jwks_client=None) -> None:
        self.bundle_id = bundle_id
        # Apple's keys are fetched and cached, tests pass a fake with their own key
        self._jwks = jwks_client or ThrottledJwks()

    def verify(self, identity_token: str, raw_nonce: str) -> AppleIdentity:
        """Return the identity or raise AppleAuthError.

        The app creates a random nonce, gives Apple its SHA-256 and sends us the raw nonce.
        Apple writes the hash into the token, so a stolen token cannot be replayed without the nonce.
        """
        if not identity_token or not raw_nonce:
            raise AppleAuthError("identity token and nonce are required")
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(identity_token)
            claims = jwt.decode(
                identity_token,
                signing_key.key,
                algorithms=["RS256"],  # never the algorithm named in the token itself
                audience=self.bundle_id,
                issuer=APPLE_ISSUER,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except (jwt.PyJWTError, jwt.PyJWKClientError):
            raise AppleAuthError("the identity token is not valid") from None

        expected_nonce = hashlib.sha256(raw_nonce.encode()).hexdigest()
        if not hmac.compare_digest(str(claims.get("nonce", "")), expected_nonce):
            raise AppleAuthError("the nonce does not match")
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject:
            raise AppleAuthError("the token has no subject")
        return AppleIdentity(subject=subject)
