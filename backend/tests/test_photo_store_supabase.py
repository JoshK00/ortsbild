import os

import pytest
from dotenv import load_dotenv

from privacy.photo_store import supabase_store_from_env
from privacy.photos import strip_photo_metadata
from models.incoming_report import Photo
from tests.image_helpers import make_jpeg

load_dotenv()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SECRET_KEY")),
        reason="needs SUPABASE_URL and SUPABASE_SECRET_KEY in backend/.env",
    ),
]


def test_supabase_store_round_trip_and_exif_stripping():
    """Upload a photo with EXIF to raw, strip it into clean, check it, and clean up again."""
    store = supabase_store_from_env()
    raw_ref, clean_ref = "raw/integration-test/p1.jpg", "clean/integration-test/p1.jpg"
    try:
        store.save(raw_ref, make_jpeg(with_exif=True), "image/jpeg")
        photos = [Photo(id="p1", mime_type="image/jpeg", ref=raw_ref)]
        clean, log = strip_photo_metadata(photos, "integration-test", store)
        assert clean[0].ref == clean_ref
        assert [(e.kind, e.count) for e in log] == [("exif", 1)]
        assert len(store.load(clean_ref)) > 0
    finally:
        store.delete(raw_ref)
        store.delete(clean_ref)
