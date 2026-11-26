import asyncio

import pytest
from fastapi import HTTPException, Request

from app import main


class ReadyConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _statement):
        return 1


class ReadyEngine:
    def connect(self):
        return ReadyConnection()


def test_readiness_reports_local_storage_as_degraded(monkeypatch):
    monkeypatch.setattr(main, "engine", ReadyEngine())
    monkeypatch.setattr(
        main,
        "storage_readiness",
        lambda: {
            "backend": "local",
            "status": "local",
            "persistent": False,
            "private": True,
            "message": "Local storage persistence is not guaranteed.",
        },
    )

    result = main.readiness()

    assert result["status"] == "degraded"
    assert result["database"] == "ok"
    assert result["storage"]["persistent"] is False


def test_readiness_fails_when_supabase_storage_is_not_private(monkeypatch):
    monkeypatch.setattr(main, "engine", ReadyEngine())
    monkeypatch.setattr(
        main,
        "storage_readiness",
        lambda: {
            "backend": "supabase",
            "status": "bucket_public",
            "persistent": True,
            "private": False,
            "message": "The configured Supabase bucket is public; use a private bucket.",
        },
    )

    with pytest.raises(HTTPException) as raised:
        main.readiness()

    assert raised.value.status_code == 503
    assert raised.value.detail["storage"]["private"] is False


def test_unexpected_error_response_includes_request_id_without_exception_text():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 1234),
        }
    )
    request.state.request_id = "safe-request-id"

    response = asyncio.run(
        main.unexpected_error(request, ValueError("sensitive parser details"))
    )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "safe-request-id"
    assert b"sensitive parser details" not in response.body
