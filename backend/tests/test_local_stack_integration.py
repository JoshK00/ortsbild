import os
import secrets

import pytest
from dotenv import load_dotenv

from models.incoming_report import Photo
from privacy.photo_store import S3PhotoStore, s3_buckets_from_env, s3_client_from_env
from privacy.photos import strip_photo_metadata
from privacy.postgres_stores import PostgresPseudonymStore, PostgresReportStatusStore
from privacy.pseudonyms import hash_identifier
from tests.image_helpers import make_jpeg

load_dotenv()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.getenv("DATABASE_URL") and os.getenv("STORAGE_ENDPOINT_URL")),
        reason="needs DATABASE_URL and STORAGE_ENDPOINT_URL (start docker compose, see .env.example)",
    ),
]


def test_real_postgres_pseudonyms_are_stable_and_store_only_a_hash():
    """Against the real database: same identifier, same pseudonym, no plain identifier in the table."""
    import psycopg

    dsn, secret_for_test = os.environ["DATABASE_URL"], secrets.token_hex(16)
    identifier = f"integration-{secrets.token_hex(4)}@example.com"
    identifier_hash = hash_identifier(identifier, "email", secret_for_test)
    store = PostgresPseudonymStore(dsn, secret_for_test)
    try:
        first = store.get_or_create(identifier, "email")
        assert store.get_or_create(identifier, "email") == first and first.startswith("rep-")
        with psycopg.connect(dsn) as connection:
            rows = connection.execute("select * from pseudonyms where identifier_hash = %s", (identifier_hash,)).fetchall()
        assert len(rows) == 1 and identifier not in str(rows)
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute("delete from pseudonyms where identifier_hash = %s", (identifier_hash,))


def test_real_postgres_report_status_round_trip():
    """Against the real database: a blocked report shows up in the operator list."""
    import psycopg

    dsn, report_id = os.environ["DATABASE_URL"], f"integration-test-{secrets.token_hex(4)}"
    store = PostgresReportStatusStore(dsn)
    try:
        store.set_status(report_id, "processing", "app")
        assert report_id not in [row.report_id for row in store.list_blocked()]
        store.set_status(report_id, "blocked_privacy", "app", "sanitize_text: RuntimeError")
        assert {r.report_id: r for r in store.list_blocked()}[report_id].block_reason == "sanitize_text: RuntimeError"
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute("delete from reports where id = %s", (report_id,))


def test_real_object_storage_round_trip_and_exif_stripping():
    """Against the real S3 storage (moto locally, IONOS later): upload, strip EXIF, check, clean up."""
    store = S3PhotoStore(s3_client_from_env(), s3_buckets_from_env())
    raw_ref, clean_ref = "raw/integration-test/p1.jpg", "clean/integration-test/p1.jpg"
    try:
        store.save(raw_ref, make_jpeg(with_exif=True), "image/jpeg")
        clean, log = strip_photo_metadata([Photo(id="p1", mime_type="image/jpeg", ref=raw_ref)], "integration-test", store)
        assert clean[0].ref == clean_ref and [(e.kind, e.count) for e in log] == [("exif", 1)]
        assert len(store.load(clean_ref)) > 0
    finally:
        store.delete(raw_ref)
        store.delete(clean_ref)
