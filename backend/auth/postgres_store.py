import psycopg

from auth.sessions import RefreshRecord
from privacy.retry import retry

COLUMNS = "id, session_id, user_key, token_hash, expires_at, used_at, revoked_at"


class PostgresRefreshTokenStore:
    """Keeps the refresh tokens in the PostgreSQL table `refresh_tokens` (see sql/postgres/004_auth_and_owner.sql).

    Only the hash of a token is stored. `connect` can be replaced in tests.
    """

    def __init__(self, dsn: str, connect=psycopg.connect) -> None:
        self.dsn = dsn
        self.connect = connect

    def _execute(self, sql: str, params: tuple, what: str, fetch: str | None = None):
        def run():
            with self.connect(self.dsn) as connection:
                cursor = connection.execute(sql, params)
                if fetch == "one":
                    return cursor.fetchone()
                return None

        return retry(run, what)

    def add(self, record: RefreshRecord) -> None:
        self._execute(
            f"insert into refresh_tokens ({COLUMNS}) values (%s, %s, %s, %s, %s, %s, %s)",
            (record.id, record.session_id, record.user_key, record.token_hash,
             record.expires_at, record.used_at, record.revoked_at),
            "refresh token save",
        )

    def find(self, token_hash: str) -> RefreshRecord | None:
        row = self._execute(
            f"select {COLUMNS} from refresh_tokens where token_hash = %s", (token_hash,), "refresh token read", "one"
        )
        return RefreshRecord(*row) if row else None

    def mark_used(self, record_id: str) -> bool:
        # One statement: of two parallel refreshes only one finds `used_at is null`
        row = self._execute(
            "update refresh_tokens set used_at = now() where id = %s and used_at is null returning id",
            (record_id,), "refresh token update", "one",
        )
        return row is not None

    def revoke_session(self, session_id: str) -> None:
        self._execute(
            "update refresh_tokens set revoked_at = now() where session_id = %s and revoked_at is null",
            (session_id,), "refresh token revoke",
        )

    def revoke_user(self, user_key: str) -> None:
        self._execute(
            "update refresh_tokens set revoked_at = now() where user_key = %s and revoked_at is null",
            (user_key,), "refresh token revoke",
        )

    def delete_user(self, user_key: str) -> None:
        self._execute("delete from refresh_tokens where user_key = %s", (user_key,), "refresh token delete")

    def session_active(self, session_id: str) -> bool:
        row = self._execute(
            "select 1 from refresh_tokens where session_id = %s and revoked_at is null limit 1",
            (session_id,), "session check", "one",
        )
        return row is not None
