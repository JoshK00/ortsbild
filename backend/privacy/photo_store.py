import os
from typing import Protocol

from privacy.retry import retry


class PhotoStore(Protocol):
    """Where the image files live. The privacy layer only knows this interface.

    A ref has the form "<bucket>/<path>", e.g. "raw/7c9e/p1.jpg" or "clean/7c9e/p1.jpg".
    """

    def load(self, ref: str) -> bytes: ...

    def save(self, ref: str, data: bytes, content_type: str) -> None: ...

    def delete(self, ref: str) -> None: ...


def split_ref(ref: str) -> tuple[str, str]:
    """Split "raw/7c9e/p1.jpg" into the bucket "raw" and the path "7c9e/p1.jpg"."""
    bucket, _, path = ref.partition("/")
    if not bucket or not path:
        raise ValueError("ref must look like '<bucket>/<path>'")
    return bucket, path


class InMemoryPhotoStore:
    """Keeps the files in a dict. For tests and local experiments, nothing is persisted."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def load(self, ref: str) -> bytes:
        return self.files[ref]

    def save(self, ref: str, data: bytes, content_type: str) -> None:
        split_ref(ref)  # same validation as the real store
        self.files[ref] = data

    def delete(self, ref: str) -> None:
        self.files.pop(ref, None)


class SupabasePhotoStore:
    """Stores the files in Supabase Storage. The bucket is the first part of the ref.

    TODO: Use narrower access rules (RLS, own role) instead of the secret key in production.
    """

    def __init__(self, client) -> None:
        self.client = client

    def load(self, ref: str) -> bytes:
        bucket, path = split_ref(ref)
        return retry(lambda: self.client.storage.from_(bucket).download(path), "storage load")

    def save(self, ref: str, data: bytes, content_type: str) -> None:
        bucket, path = split_ref(ref)
        retry(
            lambda: self.client.storage.from_(bucket).upload(
                path, data, {"content-type": content_type, "upsert": "true"}
            ),
            "storage save",
        )

    def delete(self, ref: str) -> None:
        bucket, path = split_ref(ref)
        retry(lambda: self.client.storage.from_(bucket).remove([path]), "storage delete")


def supabase_store_from_env() -> SupabasePhotoStore:
    """Build the Supabase store from SUPABASE_URL and SUPABASE_SECRET_KEY (backend/.env)."""
    from dotenv import load_dotenv
    from supabase import create_client

    load_dotenv()
    return SupabasePhotoStore(
        create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
    )
