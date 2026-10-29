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


class S3PhotoStore:
    """Stores the files in an S3-compatible object storage (IONOS, STACKIT, Hetzner, MinIO, ...).

    The first part of a ref ("raw", "clean") is a logical bucket. `buckets` maps it to the real
    bucket name, because bucket names are unique per provider ("raw" is surely taken).
    """

    def __init__(self, client, buckets: dict[str, str]) -> None:
        self.client = client
        self.buckets = buckets

    def _target(self, ref: str) -> tuple[str, str]:
        logical, path = split_ref(ref)
        if logical not in self.buckets:
            raise ValueError(f"unknown bucket: {logical}")
        return self.buckets[logical], path

    def load(self, ref: str) -> bytes:
        bucket, key = self._target(ref)
        return retry(lambda: self.client.get_object(Bucket=bucket, Key=key)["Body"].read(), "storage load")

    def save(self, ref: str, data: bytes, content_type: str) -> None:
        bucket, key = self._target(ref)
        retry(
            lambda: self.client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type),
            "storage save",
        )

    def delete(self, ref: str) -> None:
        bucket, key = self._target(ref)
        retry(lambda: self.client.delete_object(Bucket=bucket, Key=key), "storage delete")


def s3_buckets_from_env() -> dict[str, str]:
    """The real bucket names behind "raw" and "clean" (STORAGE_BUCKET_RAW, STORAGE_BUCKET_CLEAN)."""
    return {"raw": os.environ["STORAGE_BUCKET_RAW"], "clean": os.environ["STORAGE_BUCKET_CLEAN"]}


def s3_client_from_env():
    """Build the S3 client from STORAGE_ENDPOINT_URL, STORAGE_ACCESS_KEY, STORAGE_SECRET_KEY, STORAGE_REGION."""
    import boto3
    from botocore.config import Config
    from dotenv import load_dotenv

    load_dotenv()
    return boto3.client(
        "s3",
        endpoint_url=os.environ["STORAGE_ENDPOINT_URL"],
        aws_access_key_id=os.environ["STORAGE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["STORAGE_SECRET_KEY"],
        region_name=os.getenv("STORAGE_REGION", "us-east-1"),
        # one attempt only: our own retry (privacy/retry.py) decides, so there is no double retry
        config=Config(signature_version="s3v4", retries={"max_attempts": 1}, connect_timeout=5, read_timeout=30),
    )


def s3_store_from_env() -> S3PhotoStore:
    """Build the photo store for the real object storage from the environment (backend/.env)."""
    return S3PhotoStore(s3_client_from_env(), s3_buckets_from_env())
