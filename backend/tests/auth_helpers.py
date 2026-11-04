from auth.apple import AppleAuthError, AppleIdentity
from auth.sessions import AuthManager, InMemoryRefreshTokenStore
from auth.tokens import TokenIssuer

SECRET = "x" * 40


class FakeVerifier:
    """Stands in for the check of the Apple token: the token text "apple:<id>" is user <id>."""

    def __init__(self, subject=None, fail=False):
        self.subject, self.fail, self.seen = subject, fail, []

    def verify(self, identity_token, raw_nonce):
        self.seen.append((identity_token, raw_nonce))
        if self.fail:
            raise AppleAuthError("no")
        return AppleIdentity(subject=self.subject or identity_token.removeprefix("apple:"))


def make_auth_manager(verifier=None):
    store = InMemoryRefreshTokenStore()
    return AuthManager(verifier or FakeVerifier(), TokenIssuer(SECRET), store, "pseudonym-secret-for-tests"), store


def sign_in(client, user="anna"):
    """Log in as the user through the endpoint and return the Authorization header."""
    response = client.post("/v1/auth/apple", json={"identity_token": f"apple:{user}", "nonce": "n"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
