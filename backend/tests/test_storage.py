from unittest.mock import Mock

import httpx
import pytest
from botocore.exceptions import ClientError

from app.core.config import settings
from app.services import storage


@pytest.fixture
def supabase_storage(monkeypatch):
    monkeypatch.setattr(settings, "data_storage_backend", "supabase")
    monkeypatch.setattr(settings, "supabase_storage_driver", "rest")
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_storage_bucket", "private datasets")
    monkeypatch.setattr(settings, "supabase_secret_key", "")
    monkeypatch.setattr(settings, "supabase_service_role_key", "test-service-role-key")


@pytest.fixture
def s3_storage(monkeypatch, supabase_storage):
    monkeypatch.setattr(settings, "supabase_storage_driver", "s3")
    monkeypatch.setattr(
        settings,
        "supabase_s3_endpoint_url",
        "https://rxoxymrcccaqxbmqfazp.storage.supabase.co/storage/v1/s3",
    )
    monkeypatch.setattr(settings, "supabase_s3_region", "ap-south-1")
    monkeypatch.setattr(settings, "supabase_s3_access_key_id", "test-access-key")
    monkeypatch.setattr(
        settings,
        "supabase_s3_secret_access_key",
        "test-s3-secret",
    )


def install_transport(monkeypatch, handler):
    client_type = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        storage.httpx,
        "Client",
        lambda **kwargs: client_type(transport=transport, **kwargs),
    )


def install_s3_client(monkeypatch, client):
    calls = {}

    def create_client(service_name, **kwargs):
        calls["service_name"] = service_name
        calls.update(kwargs)
        return client

    monkeypatch.setattr(storage.boto3, "client", create_client)
    return calls


def s3_error(code, status=404, operation="GetObject"):
    return ClientError(
        {
            "Error": {"Code": code, "Message": "mock S3 failure"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operation,
    )


def test_supabase_upload_uses_private_authenticated_object_request(
    monkeypatch,
    supabase_storage,
    tmp_path,
):
    content = b"private,csv\n1,2\n"
    local_path = tmp_path / "dataset.csv"

    def handler(request):
        assert request.method == "POST"
        assert request.url.raw_path == b"/storage/v1/object/private%20datasets/dataset.csv"
        assert request.headers["authorization"] == "Bearer test-service-role-key"
        assert request.headers["apikey"] == "test-service-role-key"
        assert request.headers["x-upsert"] == "false"
        assert request.content == content
        return httpx.Response(200, request=request)

    install_transport(monkeypatch, handler)
    storage.save_dataset("dataset.csv", content, local_path)
    assert not local_path.exists()


def test_supabase_secret_key_uses_apikey_without_bearer_authorization(
    monkeypatch,
    supabase_storage,
    tmp_path,
):
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_test-key")
    content = b"private,csv\n1,2\n"

    def handler(request):
        assert request.method == "POST"
        assert request.headers["apikey"] == "sb_secret_test-key"
        assert "authorization" not in request.headers
        assert request.content == content
        return httpx.Response(200, request=request)

    install_transport(monkeypatch, handler)
    storage.save_dataset("dataset.csv", content, tmp_path / "dataset.csv")


def test_supabase_download_returns_bytes_and_maps_missing_object(
    monkeypatch,
    supabase_storage,
    tmp_path,
):
    def handler(request):
        if request.url.path.endswith("/present.csv"):
            return httpx.Response(200, content=b"a,b\n1,2\n", request=request)
        return httpx.Response(404, request=request)

    install_transport(monkeypatch, handler)
    local_path = tmp_path / "unused.csv"
    assert storage.read_dataset("present.csv", local_path) == b"a,b\n1,2\n"
    with pytest.raises(FileNotFoundError):
        storage.read_dataset("missing.csv", local_path)


def test_supabase_delete_removes_only_the_named_object(
    monkeypatch,
    supabase_storage,
    tmp_path,
):
    def handler(request):
        assert request.method == "DELETE"
        assert request.url.raw_path == b"/storage/v1/object/private%20datasets"
        assert request.headers["authorization"] == "Bearer test-service-role-key"
        assert request.read() == b'{"prefixes":["dataset.csv"]}'
        return httpx.Response(200, request=request)

    install_transport(monkeypatch, handler)
    storage.delete_dataset("dataset.csv", tmp_path / "unused.csv")


def test_supabase_delete_is_idempotent_when_object_is_already_missing(
    monkeypatch,
    supabase_storage,
    tmp_path,
):
    install_transport(
        monkeypatch,
        lambda request: httpx.Response(404, request=request),
    )
    storage.delete_dataset("missing.csv", tmp_path / "unused.csv")


def test_s3_upload_uses_supabase_endpoint_region_and_sigv4(
    monkeypatch,
    s3_storage,
    tmp_path,
):
    content = b"private,csv\n1,2\n"
    client = Mock()
    calls = install_s3_client(monkeypatch, client)

    storage.save_dataset("0123456789abcdef.csv", content, tmp_path / "unused.csv")

    assert calls["service_name"] == "s3"
    assert calls["endpoint_url"] == (
        "https://rxoxymrcccaqxbmqfazp.storage.supabase.co/storage/v1/s3"
    )
    assert calls["region_name"] == "ap-south-1"
    assert calls["aws_access_key_id"] == "test-access-key"
    assert calls["aws_secret_access_key"] == "test-s3-secret"
    assert calls["config"].signature_version == "s3v4"
    client.put_object.assert_called_once_with(
        Bucket="private datasets",
        Key="0123456789abcdef.csv",
        Body=content,
        ContentType="application/octet-stream",
    )


def test_s3_download_returns_bytes_and_closes_response_body(
    monkeypatch,
    s3_storage,
    tmp_path,
):
    body = Mock()
    body.read.return_value = b"a,b\n1,2\n"
    client = Mock()
    client.get_object.return_value = {"Body": body}
    install_s3_client(monkeypatch, client)

    content = storage.read_dataset("0123456789abcdef.csv", tmp_path / "unused.csv")

    assert content == b"a,b\n1,2\n"
    client.get_object.assert_called_once_with(
        Bucket="private datasets",
        Key="0123456789abcdef.csv",
    )
    body.close.assert_called_once_with()


def test_s3_download_maps_missing_key_to_file_not_found(
    monkeypatch,
    s3_storage,
    tmp_path,
):
    client = Mock()
    client.get_object.side_effect = s3_error("NoSuchKey")
    install_s3_client(monkeypatch, client)

    with pytest.raises(FileNotFoundError, match="missing.csv"):
        storage.read_dataset("missing.csv", tmp_path / "unused.csv")


def test_s3_existence_check_distinguishes_missing_from_present(
    monkeypatch,
    s3_storage,
    tmp_path,
):
    client = Mock()
    client.head_object.side_effect = [None, s3_error("404", operation="HeadObject")]
    install_s3_client(monkeypatch, client)

    assert storage.dataset_exists("present.csv", tmp_path / "unused.csv") is True
    assert storage.dataset_exists("missing.csv", tmp_path / "unused.csv") is False
    assert client.head_object.call_count == 2


def test_s3_existence_check_surfaces_access_errors(
    monkeypatch,
    s3_storage,
    tmp_path,
):
    client = Mock()
    client.head_object.side_effect = s3_error(
        "AccessDenied",
        status=403,
        operation="HeadObject",
    )
    install_s3_client(monkeypatch, client)

    with pytest.raises(storage.DatasetStorageError):
        storage.dataset_exists("private.csv", tmp_path / "unused.csv")


def test_s3_delete_removes_only_the_named_object(
    monkeypatch,
    s3_storage,
    tmp_path,
):
    client = Mock()
    install_s3_client(monkeypatch, client)

    storage.delete_dataset("0123456789abcdef.csv", tmp_path / "unused.csv")

    client.delete_object.assert_called_once_with(
        Bucket="private datasets",
        Key="0123456789abcdef.csv",
    )


def test_s3_delete_surfaces_storage_errors(
    monkeypatch,
    s3_storage,
    tmp_path,
):
    client = Mock()
    client.delete_object.side_effect = s3_error(
        "AccessDenied",
        status=403,
        operation="DeleteObject",
    )
    install_s3_client(monkeypatch, client)

    with pytest.raises(storage.DatasetStorageError):
        storage.delete_dataset("private.csv", tmp_path / "unused.csv")


def test_s3_errors_are_sanitized_in_exception_and_logs(
    monkeypatch,
    s3_storage,
    tmp_path,
    caplog,
):
    client = Mock()
    client.put_object.side_effect = ClientError(
        {
            "Error": {"Code": "AccessDenied", "Message": "test-s3-secret"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        },
        "PutObject",
    )
    install_s3_client(monkeypatch, client)

    with pytest.raises(storage.DatasetStorageError) as raised:
        storage.save_dataset("dataset.csv", b"data", tmp_path / "unused.csv")

    assert "test-s3-secret" not in str(raised.value)
    assert "test-s3-secret" not in caplog.text


def test_supabase_errors_are_sanitized(
    monkeypatch,
    supabase_storage,
    tmp_path,
):
    def handler(request):
        return httpx.Response(503, request=request)

    install_transport(monkeypatch, handler)
    with pytest.raises(storage.DatasetStorageError) as raised:
        storage.save_dataset("dataset.csv", b"data", tmp_path / "dataset.csv")

    assert "test-service-role-key" not in str(raised.value)


def test_storage_readiness_requires_a_reachable_private_bucket(
    monkeypatch,
    supabase_storage,
):
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/storage/v1/bucket/private datasets"
        assert request.headers["authorization"] == "Bearer test-service-role-key"
        return httpx.Response(200, json={"id": "private datasets", "public": False}, request=request)

    install_transport(monkeypatch, handler)

    result = storage.storage_readiness()

    assert result["status"] == "ready"
    assert result["persistent"] is True
    assert result["private"] is True


def test_storage_readiness_rejects_public_bucket(
    monkeypatch,
    supabase_storage,
):
    install_transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={"id": "private datasets", "public": True},
            request=request,
        ),
    )

    result = storage.storage_readiness()

    assert result["status"] == "bucket_public"
    assert result["private"] is False


def test_local_storage_readiness_warns_about_host_persistence(monkeypatch):
    monkeypatch.setattr(settings, "data_storage_backend", "local")

    result = storage.storage_readiness()

    assert result["status"] == "local"
    assert result["persistent"] is False
    assert "restart" in result["message"]


def test_local_storage_operations_remain_file_based(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_storage_backend", "local")
    stored_name = "0123456789abcdef.csv"
    local_path = tmp_path / stored_name
    content = b"a,b\n1,2\n"

    storage.save_dataset(stored_name, content, local_path)

    assert storage.dataset_exists(stored_name, local_path) is True
    assert storage.read_dataset(stored_name, local_path) == content
    storage.delete_dataset(stored_name, local_path)
    assert storage.dataset_exists(stored_name, local_path) is False
