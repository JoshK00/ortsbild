import boto3
import pytest
from moto import mock_aws

from gateway.storage import LocalStorage, S3Storage


def test_local_storage_roundtrip(tmp_path):
    storage = LocalStorage(tmp_path)
    storage.put("bucket", "t/1/0.jpg", b"data", "image/jpeg")
    assert storage.get("bucket", "t/1/0.jpg") == b"data"
    storage.delete("bucket", "t/1/0.jpg")
    with pytest.raises(FileNotFoundError):
        storage.get("bucket", "t/1/0.jpg")


def test_local_storage_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        LocalStorage(tmp_path / "root").put("bucket", "../../etc/passwd", b"x", "text/plain")


@mock_aws
def test_s3_storage_roundtrip():
    client = boto3.client("s3", region_name="eu-central-1")
    client.create_bucket(Bucket="reports-raw", CreateBucketConfiguration={"LocationConstraint": "eu-central-1"})
    storage = S3Storage(client)
    storage.put("reports-raw", "t/1/0.jpg", b"jpeg", "image/jpeg")
    assert storage.get("reports-raw", "t/1/0.jpg") == b"jpeg"
    storage.delete("reports-raw", "t/1/0.jpg")
    assert client.list_objects_v2(Bucket="reports-raw").get("KeyCount") == 0
