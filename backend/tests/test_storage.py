import httpx
import pytest

from app.core.config import settings
from app.services import storage


@pytest.fixture
def supabase_storage(monkeypatch):
    monkeypatch.setattr(settings, "data_storage_backend", "supabase")
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_storage_bucket", "private datasets")
    monkeypatch.setattr(settings, "supabase_service_role_key", "test-service-role-key")


def install_transport(monkeypatch, handler):
    client_type = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        storage.httpx,
        "Client",
        lambda **kwargs: client_type(transport=transport, **kwargs),
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
