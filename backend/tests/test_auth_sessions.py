import time
import jwt
import pytest

from auth.sessions import AuthManager, InMemoryRefreshTokenStore, SessionError, hash_token
from auth.tokens import AUDIENCE, ISSUER, TokenError, TokenIssuer
from tests.auth_helpers import SECRET, FakeVerifier


def make_manager(verifier=None, **kwargs):
    store = InMemoryRefreshTokenStore()
    manager = AuthManager(verifier or FakeVerifier(subject="apple-sub-1"), TokenIssuer(SECRET), store, "pseudonym-secret-for-tests", **kwargs)
    return manager, store


# ---------------------------------------------------------------------------
# access token
# ---------------------------------------------------------------------------


def test_the_access_token_carries_user_key_and_session():
    issuer = TokenIssuer(SECRET)
    claims = issuer.verify(issuer.issue("key-1", "session-1"))
    assert (claims.user_key, claims.session_id) == ("key-1", "session-1")


def test_a_short_secret_is_refused():
    with pytest.raises(ValueError):
        TokenIssuer("too-short")


def test_a_token_signed_with_another_secret_is_rejected():
    token = TokenIssuer("y" * 40).issue("key-1", "s")
    with pytest.raises(TokenError):
        TokenIssuer(SECRET).verify(token)


def test_an_expired_token_is_rejected():
    with pytest.raises(TokenError):
        TokenIssuer(SECRET, lifetime_seconds=-10).verify(TokenIssuer(SECRET, lifetime_seconds=-10).issue("k", "s"))


def test_a_token_for_another_audience_or_issuer_is_rejected():
    now = int(time.time())
    base = {"sub": "k", "sid": "s", "iat": now, "exp": now + 100, "iss": ISSUER, "aud": AUDIENCE}
    for change in ({"aud": "other"}, {"iss": "other"}):
        token = jwt.encode({**base, **change}, SECRET, algorithm="HS256")
        with pytest.raises(TokenError):
            TokenIssuer(SECRET).verify(token)


def test_the_none_algorithm_and_garbage_are_rejected():
    now = int(time.time())
    unsigned = jwt.encode({"sub": "k", "sid": "s", "iat": now, "exp": now + 100, "iss": ISSUER, "aud": AUDIENCE}, key=None, algorithm="none")
    for bad in (unsigned, "", "garbage", "a.b.c"):
        with pytest.raises(TokenError):
            TokenIssuer(SECRET).verify(bad)


def test_the_token_error_never_contains_the_token():
    token = TokenIssuer("y" * 40).issue("k", "s")
    with pytest.raises(TokenError) as error:
        TokenIssuer(SECRET).verify(token)
    assert token not in str(error.value)


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


def test_login_gives_a_token_pair_and_a_reporter_id():
    manager, _ = make_manager()
    pair = manager.login_apple("apple-token", "nonce")
    claims = manager.issuer.verify(pair.access_token)
    assert pair.reporter_id == "usr-" + claims.user_key[:12]
    assert pair.expires_in == 3600


def test_the_apple_id_does_not_appear_anywhere():
    """The plain Apple id is hashed at once, no token, record or reporter id contains it."""
    manager, store = make_manager(FakeVerifier(subject="001234.secret-apple-id.5678"))
    pair = manager.login_apple("apple-token", "nonce")
    everything = repr(store.records) + pair.access_token + pair.refresh_token + pair.reporter_id
    assert "secret-apple-id" not in everything
    assert "secret-apple-id" not in repr(manager.issuer.verify(pair.access_token))


def test_the_same_apple_user_always_gets_the_same_user_key():
    manager, _ = make_manager()
    first = manager.issuer.verify(manager.login_apple("t", "n").access_token).user_key
    second = manager.issuer.verify(manager.login_apple("t", "n").access_token).user_key
    assert first == second


def test_different_apple_users_get_different_keys():
    a = make_manager(FakeVerifier("user-a"))[0]
    b = make_manager(FakeVerifier("user-b"))[0]
    assert a.issuer.verify(a.login_apple("t", "n").access_token).user_key != b.issuer.verify(b.login_apple("t", "n").access_token).user_key


def test_a_refused_apple_token_gives_no_session():
    manager, store = make_manager(FakeVerifier(fail=True))
    with pytest.raises(SessionError):
        manager.login_apple("bad", "nonce")
    assert store.records == {}


def test_the_nonce_is_handed_to_the_check():
    verifier = FakeVerifier()
    make_manager(verifier)[0].login_apple("token", "my-nonce")
    assert verifier.seen == [("token", "my-nonce")]


def test_only_the_hash_of_the_refresh_token_is_stored():
    manager, store = make_manager()
    pair = manager.login_apple("t", "n")
    [record] = store.records.values()
    assert record.token_hash == hash_token(pair.refresh_token)
    assert pair.refresh_token not in repr(store.records)


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


def test_refresh_gives_a_new_pair_for_the_same_session():
    manager, _ = make_manager()
    first = manager.login_apple("t", "n")
    second = manager.refresh(first.refresh_token)
    assert second.refresh_token != first.refresh_token
    assert manager.issuer.verify(second.access_token).session_id == manager.issuer.verify(first.access_token).session_id


def test_a_refresh_token_works_only_once_and_reuse_ends_all_sessions():
    """A token that shows up twice was copied. The sessions of the user end, also the new one."""
    manager, _ = make_manager()
    first = manager.login_apple("t", "n")
    second = manager.refresh(first.refresh_token)
    with pytest.raises(SessionError):
        manager.refresh(first.refresh_token)  # the copy
    with pytest.raises(SessionError):
        manager.refresh(second.refresh_token)  # the honest one is revoked as well


def test_an_unknown_refresh_token_is_refused():
    with pytest.raises(SessionError):
        make_manager()[0].refresh("never-issued")


def test_an_expired_refresh_token_is_refused():
    manager, store = make_manager(refresh_days=-1)
    pair = manager.login_apple("t", "n")
    with pytest.raises(SessionError):
        manager.refresh(pair.refresh_token)


def test_logout_ends_the_session():
    manager, _ = make_manager()
    pair = manager.login_apple("t", "n")
    manager.logout(pair.refresh_token)
    with pytest.raises(SessionError):
        manager.refresh(pair.refresh_token)


def test_logout_of_an_unknown_token_is_ignored():
    make_manager()[0].logout("never-issued")


def test_logout_does_not_end_another_session_of_the_same_user():
    manager, _ = make_manager()
    phone, tablet = manager.login_apple("t", "n"), manager.login_apple("t", "n")
    manager.logout(phone.refresh_token)
    assert manager.refresh(tablet.refresh_token).access_token


def test_a_session_is_active_until_it_is_ended():
    manager, _ = make_manager()
    pair = manager.login_apple("t", "n")
    session = manager.issuer.verify(pair.access_token).session_id
    assert manager.session_active(session)
    manager.logout(pair.refresh_token)
    assert not manager.session_active(session)


def test_a_session_stays_active_after_a_refresh():
    """The old refresh token is used up, the new one keeps the session alive."""
    manager, _ = make_manager()
    pair = manager.refresh(manager.login_apple("t", "n").refresh_token)
    assert manager.session_active(manager.issuer.verify(pair.access_token).session_id)


def test_ending_all_sessions_deletes_the_tokens_of_the_user():
    manager, store = make_manager()
    pair = manager.login_apple("t", "n")
    manager.end_all_sessions(manager.issuer.verify(pair.access_token).user_key)
    assert store.records == {}


def test_a_token_that_loses_the_race_to_mark_it_used_raises_the_alarm():
    """Two parallel refreshes: the store lets only one mark the token, the other ends all sessions."""
    manager, store = make_manager()
    pair = manager.login_apple("t", "n")
    manager.store.mark_used = lambda record_id: False  # somebody else was faster
    with pytest.raises(SessionError):
        manager.refresh(pair.refresh_token)
    assert not manager.session_active(manager.issuer.verify(pair.access_token).session_id)
