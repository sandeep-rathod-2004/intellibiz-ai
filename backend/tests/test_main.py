import asyncio

import app.main as main_module
from starlette.requests import Request


def _request(origin: str | None):
    headers = [(b"x-request-id", b"not-used")]
    if origin:
        headers.append((b"origin", origin.encode("ascii")))
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/v1/copilot/conversations",
        "headers": headers,
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 50000),
    })
    request.state.request_id = "diagnostic-request-id"
    return request


def test_unhandled_error_is_cors_readable_for_an_allowed_origin(monkeypatch):
    monkeypatch.setattr(main_module, "origins", ["http://localhost:5173"])
    response = asyncio.run(main_module.unexpected_error(
        _request("http://localhost:5173"),
        RuntimeError("private backend detail"),
    ))

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-expose-headers"] == "X-Request-ID"
    assert response.headers["x-request-id"] == "diagnostic-request-id"
    assert b"private backend detail" not in response.body


def test_unhandled_error_does_not_grant_cors_to_an_unlisted_origin(monkeypatch):
    monkeypatch.setattr(main_module, "origins", ["http://localhost:5173"])
    response = asyncio.run(main_module.unexpected_error(
        _request("https://unlisted.example.test"),
        RuntimeError("private backend detail"),
    ))

    assert "access-control-allow-origin" not in response.headers
    assert b"private backend detail" not in response.body
