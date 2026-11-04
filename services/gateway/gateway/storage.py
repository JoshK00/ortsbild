"""Object storage for photos.

``LocalStorage`` is for development and tests. ``S3Storage`` works with any S3-compatible service,
including Supabase Storage (S3 endpoint), MinIO and AWS S3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .config import Settings


class Storage(Protocol):
    def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, bucket: str, key: str) -> bytes: ...
    def delete(self, bucket: str, key: str) -> None: ...


class LocalStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, bucket: str, key: str) -> Path:
        path = (self.root / bucket / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("key escapes the storage root")
        return path

    def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        path = self._path(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, bucket: str, key: str) -> bytes:
        return self._path(bucket, key).read_bytes()

    def delete(self, bucket: str, key: str) -> None:
        self._path(bucket, key).unlink(missing_ok=True)


class S3Storage:
    def __init__(self, client):
        self.client = client

    @classmethod
    def from_settings(cls, settings: Settings) -> S3Storage:
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id.get_secret_value() if settings.s3_access_key_id else None,
            aws_secret_access_key=(
                settings.s3_secret_access_key.get_secret_value() if settings.s3_secret_access_key else None
            ),
        )
        return cls(client)

    def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, bucket: str, key: str) -> bytes:
        return self.client.get_object(Bucket=bucket, Key=key)["Body"].read()

    def delete(self, bucket: str, key: str) -> None:
        self.client.delete_object(Bucket=bucket, Key=key)


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        return S3Storage.from_settings(settings)
    return LocalStorage(settings.storage_local_root)
