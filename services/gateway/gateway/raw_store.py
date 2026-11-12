"""The raw bucket of the backend, where the gateway puts a photo before it hands the report over.

A ref has the form of the backend (backend/privacy/photo_store.py): "raw/<report id>/p1.jpg". "raw" stands for the
bucket STORAGE_BUCKET_RAW, the rest is the key. The privacy layer of the backend reads the photo from there and deletes
it once the sanitized copy exists. The gateway only writes, and deletes a photo only if the backend did not take
the report.
"""

from typing import Protocol

RAW = "raw"


class RawPhotoStore(Protocol):
    def save(self, ref: str, data: bytes, content_type: str) -> None: ...

    def delete(self, ref: str) -> None: ...


def raw_key(ref: str) -> str:
    """The key in the raw bucket of a ref like "raw/7c9e/p1.jpg"."""
    bucket, _, key = ref.partition("/")
    if bucket != RAW or not key:
        raise ValueError("the gateway writes only refs of the raw bucket")
    return key


class S3RawPhotoStore:
    def __init__(self, client, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    def save(self, ref: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=raw_key(ref), Body=data, ContentType=content_type)

    def delete(self, ref: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=raw_key(ref))


class InMemoryRawPhotoStore:
    """For tests."""

    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}

    def save(self, ref: str, data: bytes, content_type: str) -> None:
        raw_key(ref)
        self.files[ref] = (data, content_type)

    def delete(self, ref: str) -> None:
        self.files.pop(ref, None)


def s3_raw_store(settings) -> S3RawPhotoStore:
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.storage_endpoint_url,
        aws_access_key_id=settings.storage_access_key.get_secret_value(),
        aws_secret_access_key=settings.storage_secret_key.get_secret_value(),
        region_name=settings.storage_region,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=5),
    )
    return S3RawPhotoStore(client, settings.storage_bucket_raw)
