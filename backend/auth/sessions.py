import hashlib
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import NoReturn, Protocol

from auth.apple import AppleAuthError, AppleTokenVerifier
from auth.tokens import TokenIssuer
from privacy.pseudonyms import hash_identifier

REFRESH_TOKEN_DAYS = 30


class SessionError(Exception):
    """A login or a refresh was refused. The message is safe to log, it never holds a token."""


@dataclass(frozen=True)
class RefreshRecord:
    id: str
    session_id: str
    user_key: str
    token_hash: str
    expires_at: datetime
    used_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    reporter_id: str  # shortened user key, shown in the app, not the Apple id and not the report pseudonym


class RefreshTokenStore(Protocol):
    """Keeps the refresh tokens. Only the hash of a token is stored, never the token."""

    def add(self, record: RefreshRecord) -> None: ...
    def find(self, token_hash: str) -> RefreshRecord | None: ...
    def mark_used(self, record_id: str) -> bool:
        """Mark the token as used. False if it was already used (atomic, so two parallel refreshes cannot both win)."""
        ...
    def revoke_session(self, session_id: str) -> None: ...
    def revoke_user(self, user_key: str) -> None: ...
    def delete_user(self, user_key: str) -> None: ...
    def session_active(self, session_id: str) -> bool: ...


class InMemoryRefreshTokenStore:
    """Keeps the refresh tokens in a dict. For tests, nothing is persisted."""

    def __init__(self) -> None:
        self.records: dict[str, RefreshRecord] = {}

    def add(self, record: RefreshRecord) -> None:
        self.records[record.id] = record

    def find(self, token_hash: str) -> RefreshRecord | None:
        return next((r for r in self.records.values() if r.token_hash == token_hash), None)

    def mark_used(self, record_id: str) -> bool:
        record = self.records[record_id]
        if record.used_at is not None:
            return False
        self.records[record_id] = replace(record, used_at=datetime.now(timezone.utc))
        return True

    def revoke_session(self, session_id: str) -> None:
        now = datetime.now(timezone.utc)
        for key, record in list(self.records.items()):
            if record.session_id == session_id and record.revoked_at is None:
                self.records[key] = replace(record, revoked_at=now)

    def revoke_user(self, user_key: str) -> None:
        now = datetime.now(timezone.utc)
        for key, record in list(self.records.items()):
            if record.user_key == user_key and record.revoked_at is None:
                self.records[key] = replace(record, revoked_at=now)

    def delete_user(self, user_key: str) -> None:
        self.records = {k: r for k, r in self.records.items() if r.user_key != user_key}

    def session_active(self, session_id: str) -> bool:
        return any(r.session_id == session_id and r.revoked_at is None for r in self.records.values())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def reporter_id_of(user_key: str) -> str:
    return "usr-" + user_key[:12]


class AuthManager:
    """Login with Apple, refresh and logout.

    The plain Apple id (`sub`) never leaves `login_apple`: it is turned into a keyed hash (the user key)
    at once, and that key is all the rest of the system knows about the user.
    """

    def __init__(
        self,
        verifier: AppleTokenVerifier,
        issuer: TokenIssuer,
        store: RefreshTokenStore,
        pseudonym_secret: str,
        refresh_days: int = REFRESH_TOKEN_DAYS,
    ) -> None:
        self.verifier = verifier
        self.issuer = issuer
        self.store = store
        self.pseudonym_secret = pseudonym_secret
        self.refresh_days = refresh_days

    def _new_pair(self, user_key: str, session_id: str) -> TokenPair:
        refresh_token = secrets.token_urlsafe(32)
        self.store.add(
            RefreshRecord(
                id=uuid.uuid4().hex,
                session_id=session_id,
                user_key=user_key,
                token_hash=hash_token(refresh_token),
                expires_at=datetime.now(timezone.utc) + timedelta(days=self.refresh_days),
            )
        )
        return TokenPair(
            access_token=self.issuer.issue(user_key, session_id),
            refresh_token=refresh_token,
            expires_in=self.issuer.lifetime_seconds,
            reporter_id=reporter_id_of(user_key),
        )

    def login_apple(self, identity_token: str, nonce: str) -> TokenPair:
        try:
            identity = self.verifier.verify(identity_token, nonce)
        except AppleAuthError:
            raise SessionError("the Apple identity token was refused") from None
        user_key = hash_identifier(identity.subject, "apple_sub", self.pseudonym_secret)
        return self._new_pair(user_key, uuid.uuid4().hex)

    def _reuse_alarm(self, record: RefreshRecord) -> NoReturn:
        self.store.revoke_user(record.user_key)
        raise SessionError("refresh token used twice, all sessions of the user were revoked")

    def refresh(self, refresh_token: str) -> TokenPair:
        """Swap a refresh token for a new pair. Every refresh token works once.

        If a token that was already used shows up again, somebody copied it. Then all sessions of the
        user are revoked and the user has to sign in again.
        (Two refreshes at the same moment look like that too, the app must refresh one at a time.)
        """
        record = self.store.find(hash_token(refresh_token))
        if record is None:
            raise SessionError("unknown refresh token")
        if record.revoked_at is not None:
            raise SessionError("the session was revoked")
        if record.used_at is not None:
            self._reuse_alarm(record)
        if record.expires_at <= datetime.now(timezone.utc):
            raise SessionError("the refresh token has expired")
        if not self.store.mark_used(record.id):
            self._reuse_alarm(record)
        return self._new_pair(record.user_key, record.session_id)

    def session_active(self, session_id: str) -> bool:
        """False after a logout, a reuse alarm or the deletion of the account, even if the access token has not expired yet."""
        return self.store.session_active(session_id)

    def end_all_sessions(self, user_key: str) -> None:
        """Delete every refresh token of the user (deleting the account)."""
        self.store.delete_user(user_key)

    def logout(self, refresh_token: str) -> None:
        """End the session of this refresh token. An unknown token is ignored."""
        record = self.store.find(hash_token(refresh_token))
        if record is not None:
            self.store.revoke_session(record.session_id)
