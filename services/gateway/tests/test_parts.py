"""The parts of the gateway: the raw bucket and the way to the backend."""

import json

import boto3
import httpx
import pytest
from moto import mock_aws

from gateway.backend import BackendClient, BackendTimeout, BackendUnreachable
from gateway.raw_store import S3RawPhotoStore, raw_key

# --------------------------------------------------------------------------- raw bucket


def test_a_ref_maps_to_the_key_in_the_raw_bucket_like_in_the_backend():
    assert raw_key("raw/7c9e/p1.jpg") == "7c9e/p1.jpg"


@pytest.mark.parametrize("ref", ["clean/7c9e/p1.jpg", "raw/", "7c9e/p1.jpg"])
def test_the_gateway_writes_only_into_the_raw_bucket(ref):
    with pytest.raises(ValueError):
        raw_key(ref)


@mock_aws
def test_the_s3_store_writes_and_deletes_in_the_raw_bucket():
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket="ortsbild-raw")
    store = S3RawPhotoStore(client, "ortsbild-raw")
    store.save("raw/7c9e/p1.jpg", b"jpeg", "image/jpeg")
    stored = client.get_object(Bucket="ortsbild-raw", Key="7c9e/p1.jpg")
    assert stored["Body"].read() == b"jpeg" and stored["ContentType"] == "image/jpeg"
    store.delete("raw/7c9e/p1.jpg")
    assert client.list_objects_v2(Bucket="ortsbild-raw").get("KeyCount") == 0


# --------------------------------------------------------------------------- backend client


def client_with(handler) -> BackendClient:
    return BackendClient("http://backend:8000/", "key-1", 10, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_the_report_goes_to_the_entrance_with_the_token_and_the_gateway_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["headers"], seen["body"] = str(request.url), request.headers, json.loads(request.content)
        return httpx.Response(200, json={"id": "abc"})

    answer = client_with(handler).submit({"id": "abc"}, "Bearer t")
    assert seen["url"] == "http://backend:8000/internal/v1/reports"
    assert seen["headers"]["authorization"] == "Bearer t" and seen["headers"]["x-gateway-key"] == "key-1"
    assert seen["body"] == {"id": "abc"}
    assert answer.status_code == 200 and json.loads(answer.content) == {"id": "abc"}


@pytest.mark.parametrize(("error", "expected"), [
    (httpx.ConnectError("refused"), BackendUnreachable),
    (httpx.ConnectTimeout("slow"), BackendUnreachable),
    (httpx.ReadTimeout("slow"), BackendTimeout),
])  # fmt: skip
def test_connection_problems_are_told_apart(error, expected):
    def handler(request):
        raise error

    with pytest.raises(expected):
        client_with(handler).submit({}, "Bearer t")
