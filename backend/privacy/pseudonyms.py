import hashlib
import hmac
import secrets
from typing import Protocol


class PseudonymStore(Protocol):
    """Gives every reporter one stable pseudonym. Only the privacy layer may use it."""

    def get_or_create(self, identifier: str, identifier_type: str) -> str: ...


def hash_identifier(identifier: str, identifier_type: str, secret: str) -> str:
    """Keyed hash (HMAC) of the identifier. Without the secret it cannot be reversed or guessed."""
    message = f"{identifier_type}:{identifier}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def new_pseudonym() -> str:
    """A random pseudonym like "rep-4f2a9c1b7d03", unrelated to the identifier."""
    return "rep-" + secrets.token_hex(6)


class InMemoryPseudonymStore:
    """Keeps the pseudonyms in a dict. For tests and local experiments, nothing is persisted."""

    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.pseudonyms: dict[str, str] = {}

    def get_or_create(self, identifier: str, identifier_type: str) -> str:
        key = hash_identifier(identifier, identifier_type, self.secret)
        if key not in self.pseudonyms:
            self.pseudonyms[key] = new_pseudonym()
        return self.pseudonyms[key]
