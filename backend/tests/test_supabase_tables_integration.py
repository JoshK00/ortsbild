import os
import secrets

import pytest
from dotenv import load_dotenv

from privacy.pseudonyms import SupabasePseudonymStore, hash_identifier
from privacy.report_status import SupabaseReportStatusStore

load_dotenv()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SECRET_KEY")),
        reason="needs SUPABASE_URL and SUPABASE_SECRET_KEY in backend/.env",
    ),
]


@pytest.fixture
def client():
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])


def test_report_status_round_trip(client):
    """A status is written, changed and listed as blocked in the real table, then removed."""
    report_id = f"integration-test-{secrets.token_hex(4)}"
    store = SupabaseReportStatusStore(client)
    try:
        store.set_status(report_id, "processing", "app")
        assert report_id not in [row.report_id for row in store.list_blocked()]
        store.set_status(report_id, "blocked_privacy", "app", "sanitize_text: RuntimeError")
        blocked = {row.report_id: row for row in store.list_blocked()}
        assert blocked[report_id].block_reason == "sanitize_text: RuntimeError"
    finally:
        client.table("reports").delete().eq("id", report_id).execute()


def test_pseudonym_store_is_stable_and_stores_only_a_hash(client):
    """The same identifier gets the same pseudonym, and the table holds no plain identifier."""
    test_secret = secrets.token_hex(16)  # own secret, so the test does not touch real pseudonyms
    identifier = f"integration-{secrets.token_hex(4)}@example.com"
    store = SupabasePseudonymStore(client, test_secret)
    identifier_hash = hash_identifier(identifier, "email", test_secret)
    try:
        first = store.get_or_create(identifier, "email")
        assert store.get_or_create(identifier, "email") == first
        assert first.startswith("rep-")
        rows = client.table("pseudonyms").select("*").eq("identifier_hash", identifier_hash).execute().data
        assert len(rows) == 1 and identifier not in str(rows)
    finally:
        client.table("pseudonyms").delete().eq("identifier_hash", identifier_hash).execute()
