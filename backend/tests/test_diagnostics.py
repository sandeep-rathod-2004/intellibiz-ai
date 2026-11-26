import asyncio

import pytest
from fastapi import HTTPException, Request

from app.api import routes
from app.core.config import settings


def local_request(host="127.0.0.1"):
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/v1/copilot/diagnostics/openai",
        "headers": [],
        "query_string": b"",
        "scheme": "http",
        "server": ("127.0.0.1", 8000),
        "client": (host, 54321),
    })


def test_local_diagnostic_reports_live_configuration_without_secrets(monkeypatch):
    async def successful_check():
        return {
            "provider": "openai",
            "status": "authentication_verified",
            "message": "Models-list authentication succeeded; chat was not tested.",
            "checked_at": "test-time",
        }

    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(
        routes,
        "openai_configuration_metadata",
        lambda: {
            "env_file": r"D:\backend\.env",
            "key_source": "backend_dotenv",
            "key_configured": True,
            "settings_match_current_source": True,
        },
    )
    monkeypatch.setattr(routes, "diagnose_openai_authentication", successful_check)

    result = asyncio.run(routes.local_openai_diagnostic(local_request()))

    assert result["status"] == "authentication_verified"
    assert result["configuration"]["key_source"] == "backend_dotenv"
    assert "api_key" not in repr(result).lower()


@pytest.mark.parametrize(
    ("environment", "host"),
    [
        ("production", "127.0.0.1"),
        ("development", "192.0.2.10"),
        ("development", "not-an-ip"),
    ],
)
def test_local_diagnostic_is_hidden_outside_development_loopback(
    monkeypatch,
    environment,
    host,
):
    monkeypatch.setattr(settings, "environment", environment)
    monkeypatch.setattr(
        routes,
        "diagnose_openai_authentication",
        lambda: pytest.fail("Provider diagnostic must not run for rejected requests"),
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(routes.local_openai_diagnostic(local_request(host)))

    assert raised.value.status_code == 404
