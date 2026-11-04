import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from auth.apple import APPLE_ISSUER, AppleAuthError, AppleTokenVerifier, ThrottledJwks

BUNDLE = "com.Joshua-Kehrer.Ortsbild"
NONCE = "a-random-nonce-from-the-app"
SUB = "001234.abcdef0123456789.1234"


def make_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeKey:
    def __init__(self, key):
        self.key = key


class FakeJwks:
    """Stands in for the key server of Apple: always hands out the public key of the test key."""

    def __init__(self, private_key):
        self.public_key = private_key.public_key()

    def get_signing_key_from_jwt(self, token):
        return FakeKey(self.public_key)


PRIVATE = make_key()
VERIFIER = AppleTokenVerifier(BUNDLE, FakeJwks(PRIVATE))


def token(private_key=PRIVATE, **overrides):
    """Build a token like Apple does, tests change only what they check."""
    now = int(time.time())
    claims = {
        "iss": APPLE_ISSUER,
        "aud": BUNDLE,
        "sub": SUB,
        "iat": now,
        "exp": now + 600,
        "nonce": hashlib.sha256(NONCE.encode()).hexdigest(),
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test"})


def test_a_valid_token_gives_the_subject():
    """The normal case: the stable id of the user comes out, nothing else."""
    assert VERIFIER.verify(token(), NONCE).subject == SUB


def test_a_token_for_another_app_is_rejected():
    """The audience must be our bundle id, a token made for another app is worthless here."""
    with pytest.raises(AppleAuthError):
        VERIFIER.verify(token(aud="com.someone.else"), NONCE)


def test_the_bundle_id_must_match_exactly():
    """The case counts: the id in the project has capital letters."""
    with pytest.raises(AppleAuthError):
        VERIFIER.verify(token(aud=BUNDLE.lower()), NONCE)


def test_a_token_from_another_issuer_is_rejected():
    with pytest.raises(AppleAuthError):
        VERIFIER.verify(token(iss="https://evil.example.com"), NONCE)


def test_an_expired_token_is_rejected():
    with pytest.raises(AppleAuthError):
        VERIFIER.verify(token(exp=int(time.time()) - 10), NONCE)


def test_a_token_signed_with_a_different_key_is_rejected():
    """A forged token: right content, but not signed by Apple."""
    with pytest.raises(AppleAuthError):
        VERIFIER.verify(token(private_key=make_key()), NONCE)


def test_a_wrong_nonce_is_rejected():
    """Replay protection: the nonce of the app has to match the hash inside the token."""
    with pytest.raises(AppleAuthError):
        VERIFIER.verify(token(), "another-nonce")


def test_a_token_without_nonce_is_rejected():
    with pytest.raises(AppleAuthError):
        VERIFIER.verify(token(nonce=None), NONCE)


def test_a_token_without_subject_is_rejected():
    with pytest.raises(AppleAuthError):
        VERIFIER.verify(token(sub=None), NONCE)


def test_the_algorithm_none_attack_is_rejected():
    """An unsigned token that claims the algorithm 'none' must not pass."""
    unsigned = jwt.encode({"iss": APPLE_ISSUER, "aud": BUNDLE, "sub": SUB, "iat": 1, "exp": 4102444800}, key=None, algorithm="none")
    with pytest.raises(AppleAuthError):
        VERIFIER.verify(unsigned, NONCE)


def b64(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def test_an_hmac_token_signed_with_the_public_key_is_rejected():
    """Key confusion attack: a token signed with HS256, using the public key as the secret, must not pass.

    PyJWT refuses to build such a token on purpose, so it is made by hand here.
    """
    public_pem = PRIVATE.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    claims = {
        "iss": APPLE_ISSUER, "aud": BUNDLE, "sub": SUB, "iat": 1, "exp": 4102444800,
        "nonce": hashlib.sha256(NONCE.encode()).hexdigest(),
    }
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "test"}).encode())
    body = b64(json.dumps(claims).encode())
    signature = b64(hmac.new(public_pem, header + b"." + body, hashlib.sha256).digest())
    forged = (header + b"." + body + b"." + signature).decode()
    with pytest.raises(AppleAuthError):
        VERIFIER.verify(forged, NONCE)


def test_garbage_and_empty_input_are_rejected():
    for bad in ("", "not-a-token", "a.b.c"):
        with pytest.raises(AppleAuthError):
            VERIFIER.verify(bad, NONCE)
    with pytest.raises(AppleAuthError):
        VERIFIER.verify(token(), "")


def test_the_error_message_never_contains_the_token():
    """Tokens are credentials, they must not end up in logs through an error message."""
    value = token(aud="com.someone.else")
    with pytest.raises(AppleAuthError) as error:
        VERIFIER.verify(value, NONCE)
    assert value not in str(error.value)


# ---------------------------------------------------------------------------
# ThrottledJwks: forged tokens must not make us fetch Apple's keys again and again
# ---------------------------------------------------------------------------


class FakeKeyClient:
    """Counts how often the key list is fetched. `get_signing_keys(refresh=True)` is a fetch, `False` is the cache."""

    def __init__(self, key_ids):
        self.key_ids, self.cached, self.fetches = key_ids, list(key_ids), 0

    def get_signing_keys(self, refresh=False):
        if refresh:
            self.fetches += 1
            self.cached = list(self.key_ids)
        return [type("Key", (), {"key_id": key_id})() for key_id in self.cached]


def token_with_kid(kid):
    return jwt.encode({"sub": "x"}, "x" * 32, algorithm="HS256", headers={"kid": kid})


def test_a_known_key_id_never_triggers_a_fetch():
    client = FakeKeyClient(["abc"])
    assert ThrottledJwks(client).get_signing_key_from_jwt(token_with_kid("abc")).key_id == "abc"
    assert client.fetches == 0


def test_unknown_key_ids_fetch_only_once_a_minute():
    client, now = FakeKeyClient(["abc"]), [1000.0]
    jwks = ThrottledJwks(client, clock=lambda: now[0])
    for _ in range(50):  # a stranger sends forged tokens
        with pytest.raises(jwt.PyJWKClientError):
            jwks.get_signing_key_from_jwt(token_with_kid("forged"))
    assert client.fetches == 1
    now[0] += 61
    with pytest.raises(jwt.PyJWKClientError):
        jwks.get_signing_key_from_jwt(token_with_kid("forged"))
    assert client.fetches == 2


def test_a_newly_rotated_key_is_found_after_the_refresh():
    """Apple rotates its keys: the first token with the new key id causes one fetch and then works."""
    client = FakeKeyClient(["old"])
    jwks = ThrottledJwks(client)
    client.key_ids = ["old", "new"]
    assert jwks.get_signing_key_from_jwt(token_with_kid("new")).key_id == "new"
    assert client.fetches == 1


def test_a_token_without_a_readable_header_is_refused():
    with pytest.raises(jwt.PyJWTError):
        ThrottledJwks(FakeKeyClient([])).get_signing_key_from_jwt("garbage")
