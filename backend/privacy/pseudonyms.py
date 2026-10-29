import hashlib
import hmac
import os
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


class SupabasePseudonymStore:
    """Keeps the pseudonyms in the Supabase table `pseudonyms` (see sql/001_pseudonyms.sql).

    TODO: Open question: may the authority contact the reporter? If yes, the identifier has to
          be stored (encrypted) as well, today only its hash is kept.
    """

    TABLE = "pseudonyms"

    def __init__(self, client, secret: str) -> None:
        self.client = client
        self.secret = secret

    def _find(self, identifier_hash: str) -> str | None:
        result = (
            self.client.table(self.TABLE)
            .select("pseudonym")
            .eq("identifier_hash", identifier_hash)
            .execute()
        )
        return result.data[0]["pseudonym"] if result.data else None

    def get_or_create(self, identifier: str, identifier_type: str) -> str:
        identifier_hash = hash_identifier(identifier, identifier_type, self.secret)
        existing = self._find(identifier_hash)
        if existing:
            return existing
        # ignore_duplicates: if a parallel request created the row first, keep that one
        self.client.table(self.TABLE).upsert(
            {"identifier_hash": identifier_hash, "pseudonym": new_pseudonym()},
            on_conflict="identifier_hash",
            ignore_duplicates=True,
        ).execute()
        return self._find(identifier_hash)


def supabase_pseudonym_store_from_env() -> SupabasePseudonymStore:
    """Build the store from SUPABASE_URL, SUPABASE_SECRET_KEY and PSEUDONYM_SECRET (backend/.env)."""
    from dotenv import load_dotenv
    from supabase import create_client

    load_dotenv()
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    return SupabasePseudonymStore(client, os.environ["PSEUDONYM_SECRET"])
