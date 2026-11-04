from datetime import datetime, timezone

import boto3
import botocore.exceptions
import psycopg
import pytest
from moto import mock_aws

from api.health import database_checks, run_checks, s3_storage_checks
from auth.postgres_store import PostgresRefreshTokenStore
from auth.sessions import RefreshRecord, hash_token
from privacy.photo_store import S3PhotoStore
from privacy.postgres_stores import PostgresPseudonymStore, PostgresReportStatusStore
from privacy.retry import is_transient_error

BUCKETS = {"raw": "ortsbild-test-raw", "clean": "ortsbild-test-clean"}


# ---------------------------------------------------------------------------
# S3PhotoStore (against moto, a pretend S3 inside the test)
# ---------------------------------------------------------------------------


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        for name in BUCKETS.values():
            client.create_bucket(Bucket=name)
        yield client


def test_s3_store_saves_loads_and_deletes(s3):
    """A file goes into the real bucket behind the logical name and comes back unchanged."""
    store = S3PhotoStore(s3, BUCKETS)
    store.save("raw/7c9e/p1.jpg", b"image-bytes", "image/jpeg")
    assert s3.get_object(Bucket="ortsbild-test-raw", Key="7c9e/p1.jpg")["ContentType"] == "image/jpeg"
    assert store.load("raw/7c9e/p1.jpg") == b"image-bytes"
    store.delete("raw/7c9e/p1.jpg")
    with pytest.raises(botocore.exceptions.ClientError):
        store.load("raw/7c9e/p1.jpg")


def test_s3_store_keeps_raw_and_clean_apart(s3):
    """The same path in raw and clean are two different files in two buckets."""
    store = S3PhotoStore(s3, BUCKETS)
    store.save("raw/a/p1.jpg", b"raw", "image/jpeg")
    store.save("clean/a/p1.jpg", b"clean", "image/jpeg")
    assert (store.load("raw/a/p1.jpg"), store.load("clean/a/p1.jpg")) == (b"raw", b"clean")


def test_s3_store_rejects_an_unknown_bucket(s3):
    """Only the logical buckets raw and clean exist."""
    with pytest.raises(ValueError):
        S3PhotoStore(s3, BUCKETS).save("secret/a/p1.jpg", b"x", "image/jpeg")


def test_s3_store_works_in_the_whole_privacy_flow(s3):
    """The store replaces the in-memory one without any change in the steps."""
    from tests.test_privacy_pseudonyms_assemble import make_report
    from privacy.detectors import PatternDetector
    from privacy.graph import build_privacy_graph
    from privacy.image_detectors import Box
    from privacy.pseudonyms import InMemoryPseudonymStore
    from tests.image_helpers import make_jpeg

    class OneFace:
        def detect(self, image):
            return [Box(10, 5, 20, 15, "face", 0.9)]

    store = S3PhotoStore(s3, BUCKETS)
    store.save("raw/7c9e/p1.jpg", make_jpeg(with_exif=True, size=(40, 20)), "image/jpeg")
    graph = build_privacy_graph(
        [PatternDetector()], store, InMemoryPseudonymStore("s"), face_detector=OneFace()
    )
    result = graph.invoke({"report": make_report()})
    assert result["status"] == "running"
    assert {"face", "exif"} <= {e.kind for e in result["sanitized_report"].redaction_log.entries}
    keys = [o["Key"] for b in BUCKETS.values() for o in s3.list_objects_v2(Bucket=b).get("Contents", [])]
    assert keys == ["7c9e/p1.jpg"]  # only the clean copy is left, the raw photo is deleted


# ---------------------------------------------------------------------------
# Retry knows the errors of boto3 and psycopg
# ---------------------------------------------------------------------------


def test_storage_and_database_connection_errors_are_transient():
    """A connection problem is repeated, a missing file is not."""
    assert is_transient_error(botocore.exceptions.EndpointConnectionError(endpoint_url="http://x"))
    assert is_transient_error(psycopg.OperationalError("server closed the connection"))
    not_found = botocore.exceptions.ClientError({"ResponseMetadata": {"HTTPStatusCode": 404}}, "GetObject")
    server_error = botocore.exceptions.ClientError({"ResponseMetadata": {"HTTPStatusCode": 503}}, "GetObject")
    assert not is_transient_error(not_found)
    assert is_transient_error(server_error)


# ---------------------------------------------------------------------------
# Postgres stores (with a fake connection, the real one is tested with docker)
# ---------------------------------------------------------------------------


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConnection:
    """Records the SQL it gets and answers with prepared rows."""

    def __init__(self, log, answers):
        self.log, self.answers = log, answers

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))
        return FakeResult(self.answers.pop(0) if self.answers else [])


def fake_connect(log, answers):
    return lambda dsn, **kwargs: FakeConnection(log, answers)


def test_postgres_pseudonym_store_inserts_by_hash_and_reads_back():
    """Only the hash goes into the SQL, never the identifier, and the stored pseudonym is returned."""
    log = []
    store = PostgresPseudonymStore("dsn", "secret", fake_connect(log, [[], [("rep-4f2a9c1b7d03",)]]))
    assert store.get_or_create("max@example.com", "email") == "rep-4f2a9c1b7d03"
    assert "on conflict (identifier_hash) do nothing" in log[0][0]
    assert "max@example.com" not in str(log)


def test_postgres_status_store_upserts_the_status():
    """The status is written as an upsert on the report id."""
    log = []
    PostgresReportStatusStore("dsn", fake_connect(log, [])).set_status("7c9e", "blocked_privacy", "app", "assemble: ValueError")
    sql, params = log[0]
    assert "on conflict (id) do update" in sql
    assert params == ("7c9e", "blocked_privacy", "app", "assemble: ValueError")


def test_postgres_status_store_lists_blocked_reports():
    """The operator list is built from the rows of the table."""
    rows = [[("a", "blocked_privacy", "email", "sanitize_text: RuntimeError")]]
    [row] = PostgresReportStatusStore("dsn", fake_connect([], rows)).list_blocked()
    assert (row.report_id, row.source_type, row.block_reason) == ("a", "email", "sanitize_text: RuntimeError")


def test_postgres_claim_returns_the_id_that_owns_the_client_report_id():
    """A new report returns its own id, a retry returns the first one (decided by the unique index)."""
    log = []
    store = PostgresReportStatusStore("dsn", fake_connect(log, [[], [("first-id",)]]))
    assert store.claim("new-id", "key-1", "client-1", "app", "pilot") == "first-id"
    assert "on conflict do nothing" in log[0][0]
    assert log[0][1] == ("new-id", "app", "key-1", "client-1", "pilot")


def test_postgres_status_store_reads_a_record_and_deletes_a_user():
    row = ("a" * 32, "key-1", "sanitized", None, {"photos": []}, None, None, None)
    store = PostgresReportStatusStore("dsn", fake_connect([], [[row]]))
    assert store.get("a" * 32).user_key == "key-1"
    [deleted] = PostgresReportStatusStore("dsn", fake_connect([], [[row]])).delete_user("key-1")
    assert deleted.sanitized == {"photos": []}


def test_postgres_status_store_counts_the_recent_reports_of_a_user():
    log = []
    assert PostgresReportStatusStore("dsn", fake_connect(log, [[(3,)]])).count_recent("key-1", 3600) == 3
    assert log[0][1] == ("key-1", 3600)


def test_postgres_pseudonym_delete_uses_the_hash_only():
    log = []
    PostgresPseudonymStore("dsn", "secret", fake_connect(log, [])).delete("key-1", "user_key")
    assert "delete from pseudonyms" in log[0][0] and "key-1" not in str(log)


def test_postgres_refresh_token_store_marks_a_token_used_only_once():
    """The update only matches an unused token, so of two parallel refreshes only one wins."""
    log = []
    assert PostgresRefreshTokenStore("dsn", fake_connect(log, [[("id-1",)]])).mark_used("id-1") is True
    assert "used_at is null" in log[0][0]
    assert PostgresRefreshTokenStore("dsn", fake_connect([], [[]])).mark_used("id-1") is False


def test_postgres_refresh_token_store_keeps_the_hash_not_the_token():
    log = []
    record = RefreshRecord("id-1", "s-1", "key-1", hash_token("the-refresh-token"), datetime(2030, 1, 1, tzinfo=timezone.utc))
    PostgresRefreshTokenStore("dsn", fake_connect(log, [])).add(record)
    assert "the-refresh-token" not in str(log) and hash_token("the-refresh-token") in str(log)


def test_postgres_refresh_token_store_finds_a_token_and_checks_the_session():
    when = datetime(2030, 1, 1, tzinfo=timezone.utc)
    row = ("id-1", "s-1", "key-1", "hash", when, None, None)
    assert PostgresRefreshTokenStore("dsn", fake_connect([], [[row]])).find("hash").session_id == "s-1"
    assert PostgresRefreshTokenStore("dsn", fake_connect([], [[]])).find("nope") is None
    assert PostgresRefreshTokenStore("dsn", fake_connect([], [[(1,)]])).session_active("s-1") is True
    assert PostgresRefreshTokenStore("dsn", fake_connect([], [[]])).session_active("s-1") is False


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


def test_storage_health_passes_for_existing_buckets(s3):
    """Both buckets exist and can be reached."""
    assert all(r.ok for r in run_checks(s3_storage_checks(s3, BUCKETS)))


def test_storage_health_names_the_missing_bucket(s3):
    """A bucket that does not exist is named, so it is clear what to create."""
    results = {r.name: r for r in run_checks(s3_storage_checks(s3, {**BUCKETS, "clean": "does-not-exist"}))}
    assert results["storage_raw"].ok
    assert results["storage_clean"].detail == "bucket clean does not exist"


def test_database_health_lists_missing_tables():
    """The check says which tables are missing and what to do."""
    connect = fake_connect([], [[("pseudonyms",), ("refresh_tokens",), ("authority_registry",)]])
    [result] = run_checks(database_checks("dsn", connect))
    assert result.detail == "missing table: reports, run the SQL files"


def test_database_health_passes_when_all_tables_exist():
    """All tables are there."""
    connect = fake_connect([], [[("pseudonyms",), ("reports",), ("refresh_tokens",), ("authority_registry",)]])
    assert all(r.ok for r in run_checks(database_checks("dsn", connect)))


def test_postgres_status_store_saves_the_classification_and_moves_the_status():
    log = []
    PostgresReportStatusStore("dsn", fake_connect(log, [])).save_classification("a" * 32, {"category": "pothole"})
    sql, params = log[0]
    assert "status = 'classified'" in sql and "classification = %s" in sql
    assert params[1] == "a" * 32


def test_postgres_status_store_saves_the_draft_and_moves_the_status():
    log = []
    PostgresReportStatusStore("dsn", fake_connect(log, [])).save_draft("a" * 32, {"subject": "s"})
    sql, params = log[0]
    assert "status = 'drafted'" in sql and "draft = %s" in sql and params[1] == "a" * 32


def test_postgres_status_store_saves_the_research_and_moves_the_status():
    log = []
    PostgresReportStatusStore("dsn", fake_connect(log, [])).save_research("a" * 32, {"authority": "a"})
    assert "status = 'researched'" in log[0][0]
