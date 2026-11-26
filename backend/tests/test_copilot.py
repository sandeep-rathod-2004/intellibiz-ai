import asyncio
import logging
from io import BytesIO
from types import SimpleNamespace
from pathlib import Path

import httpx
import pandas as pd
import pytest

from app.core.config import BACKEND_ENV_FILE, settings
from app.services.analytics import profile, read_dataset
from app.services import copilot


@pytest.fixture(autouse=True)
def isolate_provider_state(monkeypatch):
    monkeypatch.setattr(copilot, "_OPENAI_CLIENT", None)
    monkeypatch.setattr(copilot, "_OPENAI_CLIENT_PROVIDER", None)
    monkeypatch.setattr(copilot, "_LAST_PROVIDER_STATUS", None)


def test_openai_request_is_bounded_and_excludes_raw_preview(monkeypatch):
    captured = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Computed answer."))]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key-not-a-real-credential")
    monkeypatch.setattr(settings, "openai_timeout_seconds", 12)
    monkeypatch.setattr(settings, "openai_max_retries", 2)

    result = asyncio.run(
        copilot.ask_copilot(
            "Explain the strategic implications of the revenue pattern.",
            {
                "dataset": "sales.csv",
                "profile": {
                    "numeric_summary": [{"name": "revenue", "sum": 150}],
                    "preview": [{"customer_email": "private@example.com"}],
                },
            },
        )
    )

    assert result == {"answer": "Computed answer.", "provider": "openai"}
    assert captured["client"]["timeout"] == 12
    assert captured["client"]["max_retries"] == 0
    request = captured["request"]
    assert request["max_tokens"] == settings.openai_max_output_tokens
    assert "private@example.com" not in request["messages"][1]["content"]
    assert "150" in request["messages"][1]["content"]
    assert copilot.provider_readiness()["status"] == "operational"


def test_openai_client_is_created_once_and_reused(monkeypatch):
    captured = {"instances": 0}

    class FakeClient:
        def __init__(self, **kwargs):
            captured["instances"] += 1
            captured["api_key"] = kwargs["api_key"]

        async def close(self):
            return None

    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    monkeypatch.setattr(settings, "openai_api_key", "test-key-not-a-real-credential")
    monkeypatch.setattr(settings, "ai_provider", "openai")

    first = copilot._get_openai_client()
    second = copilot._get_openai_client()

    assert first is second
    assert captured["instances"] == 1
    assert captured["api_key"] == "test-key-not-a-real-credential"


def test_groq_defaults_and_openai_compatible_client_configuration(monkeypatch):
    from app.core.config import Settings

    assert Settings.model_fields["ai_provider"].default == "groq"
    assert Settings.model_fields["groq_model"].default == "openai/gpt-oss-20b"
    assert Settings.model_fields["groq_base_url"].default == "https://api.groq.com/openai/v1"

    captured = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Groq response."))]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    monkeypatch.setattr(settings, "ai_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "test-groq-key-not-a-real-credential")
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-20b")
    monkeypatch.setattr(settings, "groq_base_url", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(settings, "copilot_token_budget", 384)

    result = asyncio.run(
        copilot.ask_copilot(
            "Explain possible strategic implications of the dataset.",
            {"profile": {}},
        )
    )

    assert result == {"answer": "Groq response.", "provider": "groq"}
    assert captured["client"]["api_key"] == "test-groq-key-not-a-real-credential"
    assert captured["client"]["base_url"] == "https://api.groq.com/openai/v1"
    assert captured["client"]["max_retries"] == 0
    assert captured["request"]["model"] == "openai/gpt-oss-20b"
    assert captured["request"]["max_tokens"] == 384


def test_groq_quota_failure_returns_explicitly_local_computed_analysis(monkeypatch):
    from openai import RateLimitError

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    error = RateLimitError(
        "quota unavailable",
        response=httpx.Response(429, request=request),
        body={"error": {"code": "insufficient_quota", "type": "insufficient_quota"}},
    )
    captured = {"calls": 0}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured["calls"] += 1
            raise error

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    monkeypatch.setattr(settings, "ai_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "test-groq-key-not-a-real-credential")
    monkeypatch.setattr(settings, "openai_max_retries", 4)
    facts = {
        "profile": {
            "rows": 14,
            "columns": 2,
            "numeric_summary": [
                {"name": "revenue", "mean": 250.0, "min": 100.0, "max": 400.0}
            ],
            "quality": [{"column": "revenue", "missing": 2}],
        },
    }

    result = asyncio.run(
        copilot.ask_copilot("Explain why revenue changed.", facts)
    )

    assert captured["calls"] == 1
    assert result["provider"] == "local_analytics"
    assert "Local computed analysis (not AI-generated)" in result["answer"]
    assert "Groq reports insufficient available quota or credits." in result["answer"]
    assert "Records: 14" in result["answer"]
    assert "revenue: mean 250" in result["answer"]
    assert copilot.provider_readiness()["status"] == "quota_exceeded"


def test_groq_missing_key_still_uses_local_summary_without_provider_call(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "")
    facts = {"profile": {"rows": 5, "columns": 1, "quality": []}}

    result = asyncio.run(
        copilot.ask_copilot("What conclusions should I draw?", facts)
    )

    assert result["provider"] == "local_analytics"
    assert "Groq is not configured." in result["answer"]
    assert "Records: 5" in result["answer"]
    assert copilot._OPENAI_CLIENT is None


def test_models_list_diagnostic_uses_short_timeout_and_no_completion(monkeypatch):
    captured = {}

    class FakeModels:
        async def list(self, **kwargs):
            captured["timeout"] = kwargs["timeout"]
            return SimpleNamespace(data=[])

    class FakeClient:
        def __init__(self, **kwargs):
            captured["key"] = kwargs["api_key"]
            self.models = FakeModels()

        async def close(self):
            return None

    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key-not-a-real-credential")

    result = asyncio.run(copilot.diagnose_openai_authentication())

    assert captured["timeout"] == 8.0
    assert captured["key"] == "test-key-not-a-real-credential"
    assert result["status"] == "authentication_verified"
    assert "model" in result["message"]
    assert copilot.provider_readiness()["status"] == "authentication_verified"


def test_models_list_diagnostic_requires_openai_configuration(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")

    with pytest.raises(copilot.CopilotConfigurationError):
        asyncio.run(copilot.diagnose_openai_authentication())


def test_missing_openai_model_is_a_configuration_error(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key-not-a-real-credential")
    monkeypatch.setattr(settings, "openai_model", "")

    with pytest.raises(copilot.CopilotConfigurationError, match="OPENAI_MODEL"):
        asyncio.run(copilot.diagnose_openai_authentication())


def test_application_shutdown_closes_and_clears_cached_client(monkeypatch):
    closed = []

    class FakeClient:
        async def close(self):
            closed.append(True)

    client = FakeClient()
    monkeypatch.setattr(copilot, "_OPENAI_CLIENT", client)

    asyncio.run(copilot.close_provider_clients())

    assert closed == [True]
    assert copilot._OPENAI_CLIENT is None


def _install_openai_error(monkeypatch, error):
    class FakeCompletions:
        async def create(self, **kwargs):
            raise error

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key-not-a-real-credential")
    monkeypatch.setattr(settings, "openai_max_retries", 0)
    monkeypatch.setattr(copilot, "_LAST_PROVIDER_STATUS", None)


def test_backend_dotenv_path_is_absolute():
    assert Path(BACKEND_ENV_FILE).is_absolute()
    assert Path(BACKEND_ENV_FILE).parent.name == "backend"


def test_openai_authentication_failure_has_safe_diagnostic_and_status(monkeypatch, caplog):
    from openai import AuthenticationError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(
        401,
        headers={"x-request-id": "provider-request-123"},
        request=request,
    )
    error = AuthenticationError(
        "credential rejected",
        response=response,
        body={"error": {"code": "invalid_api_key"}},
    )
    _install_openai_error(monkeypatch, error)

    with caplog.at_level(logging.WARNING, logger="app.services.copilot"):
        with pytest.raises(copilot.CopilotProviderError) as raised:
            asyncio.run(copilot.ask_copilot("Question", {"profile": {}}, "local-request-456"))

    assert raised.value.status_code == 503
    assert "active" in str(raised.value)
    assert copilot.provider_readiness()["status"] == "authentication_failed"
    assert "invalid_api_key" in caplog.text
    assert "local-request-456" in caplog.text
    assert "provider-request-123" in caplog.text
    assert "test-key-not-a-real-credential" not in caplog.text
    assert raised.value.upstream_status_code == 401
    assert raised.value.provider_error_code == "invalid_api_key"


def test_openai_403_is_classified_as_access_restriction(monkeypatch):
    from openai import PermissionDeniedError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    error = PermissionDeniedError(
        "permission denied",
        response=httpx.Response(403, request=request),
        body={"error": {"code": "permission_denied"}},
    )
    _install_openai_error(monkeypatch, error)

    with pytest.raises(copilot.CopilotProviderError) as raised:
        asyncio.run(copilot.ask_copilot("Question", {"profile": {}}))

    assert raised.value.provider_status == "access_restricted"
    assert raised.value.upstream_status_code == 403


@pytest.mark.parametrize(
    ("code", "provider_type", "expected_status", "readiness", "retryable"),
    [
        ("rate_limit_exceeded", "requests", 429, "rate_limited", True),
        ("slow_down", "requests", 429, "rate_limited", True),
        ("insufficient_quota", "insufficient_quota", 503, "quota_exceeded", False),
        ("credit_balance_exhausted", "insufficient_quota", 503, "quota_exceeded", False),
        (
            "project_spend_limit_exceeded",
            "billing",
            503,
            "project_spend_limit_exceeded",
            False,
        ),
        (
            "organization_spend_limit_exceeded",
            "billing",
            503,
            "organization_spend_limit_exceeded",
            False,
        ),
        (
            "organization_usage_limit_reached",
            "billing",
            503,
            "organization_usage_limit_reached",
            False,
        ),
    ],
)
def test_openai_rate_limit_and_quota_are_distinguished(
    monkeypatch,
    code,
    provider_type,
    expected_status,
    readiness,
    retryable,
):
    from openai import RateLimitError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    error = RateLimitError(
        "provider rejected request",
        response=httpx.Response(429, request=request),
        body={"error": {"code": code, "type": provider_type}},
    )
    _install_openai_error(monkeypatch, error)

    with pytest.raises(copilot.CopilotProviderError) as raised:
        asyncio.run(copilot.ask_copilot("Question", {"profile": {}}))

    assert raised.value.status_code == expected_status
    assert raised.value.provider_error_code == code
    assert raised.value.provider_error_type == provider_type
    assert raised.value.retryable is retryable
    assert copilot.provider_readiness()["status"] == readiness


def test_unknown_429_is_not_mislabeled_or_retried(monkeypatch):
    from openai import RateLimitError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    error = RateLimitError(
        "provider restriction",
        response=httpx.Response(429, request=request),
        body={"error": {"type": "requests"}},
    )
    _install_openai_error(monkeypatch, error)

    with pytest.raises(copilot.CopilotProviderError) as raised:
        asyncio.run(copilot.ask_copilot("Explain a business strategy.", {"profile": {}}))

    assert raised.value.provider_status == "unknown_restriction"
    assert raised.value.provider_error_code == "unknown"
    assert raised.value.provider_error_type == "requests"
    assert raised.value.retryable is False
    assert "usage" in str(raised.value)


def test_nested_provider_fields_and_retry_after_are_extracted(monkeypatch):
    from openai import RateLimitError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    error = RateLimitError(
        "provider restriction",
        response=httpx.Response(
            429,
            headers={"Retry-After": "17"},
            request=request,
        ),
        body={"error": {"code": "rate_limit_exceeded", "type": "requests"}},
    )
    _install_openai_error(monkeypatch, error)

    code, provider_type = copilot._openai_error_fields(error)
    assert code == "rate_limit_exceeded"
    assert provider_type == "requests"
    assert copilot._retry_after_seconds(error) == 17

    with pytest.raises(copilot.CopilotProviderError) as raised:
        asyncio.run(copilot.ask_copilot("Explain a business strategy.", {"profile": {}}))

    assert raised.value.retry_after_seconds == 17
    assert copilot.provider_readiness()["retry_after_seconds"] == 17


def test_temporary_rate_limit_retries_once_and_respects_retry_after(monkeypatch):
    from openai import RateLimitError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    error = RateLimitError(
        "provider rate limit",
        response=httpx.Response(
            429,
            headers={"Retry-After": "2"},
            request=request,
        ),
        body={"error": {"code": "rate_limit_exceeded", "type": "requests"}},
    )
    captured = {"calls": 0, "delays": [], "client_options": None}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured["calls"] += 1
            if captured["calls"] == 1:
                raise error
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Success."))]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_options"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    async def record_sleep(delay):
        captured["delays"].append(delay)

    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    monkeypatch.setattr(copilot.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key-not-a-real-credential")
    monkeypatch.setattr(settings, "openai_max_retries", 1)

    result = asyncio.run(
        copilot.ask_copilot("Explain a business strategy.", {"profile": {}})
    )

    assert result == {"answer": "Success.", "provider": "openai"}
    assert captured["calls"] == 2
    assert captured["delays"] == [2.0]
    assert captured["client_options"]["max_retries"] == 0


def test_quota_error_is_not_retried_even_when_retries_are_configured(monkeypatch):
    from openai import RateLimitError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    error = RateLimitError(
        "provider quota error",
        response=httpx.Response(429, request=request),
        body={"error": {"code": "insufficient_quota", "type": "insufficient_quota"}},
    )
    captured = {"calls": 0}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured["calls"] += 1
            raise error

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key-not-a-real-credential")
    monkeypatch.setattr(settings, "openai_max_retries", 4)

    with pytest.raises(copilot.CopilotProviderError) as raised:
        asyncio.run(copilot.ask_copilot("Explain a business strategy.", {"profile": {}}))

    assert captured["calls"] == 1
    assert raised.value.retryable is False
    assert raised.value.provider_status == "quota_exceeded"


def test_sanitized_429_logging_has_diagnostics_without_provider_message(monkeypatch, caplog):
    from openai import RateLimitError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    error = RateLimitError(
        "private prompt content must not be logged",
        response=httpx.Response(
            429,
            headers={"x-request-id": "provider-request-456", "Retry-After": "3"},
            request=request,
        ),
        body={
            "error": {
                "message": "sensitive provider message",
                "code": "unknown_vendor_limit",
                "type": "rate_limit_exceeded",
            }
        },
    )
    _install_openai_error(monkeypatch, error)
    monkeypatch.setattr(settings, "openai_model", "test-model")

    with caplog.at_level(logging.WARNING, logger="app.services.copilot"):
        with pytest.raises(copilot.CopilotProviderError):
            asyncio.run(copilot.ask_copilot("private user prompt", {"profile": {}}, "internal-123"))

    assert "internal-123" in caplog.text
    assert "provider-request-456" in caplog.text
    assert "http_status=429" in caplog.text
    assert "provider_error_code=unknown_vendor_limit" in caplog.text
    assert "provider_error_type=rate_limit_exceeded" in caplog.text
    assert "retry_after_seconds=3.0" in caplog.text
    assert "model=test-model" in caplog.text
    assert "duration_ms=" in caplog.text
    assert "private user prompt" not in caplog.text
    assert "sensitive provider message" not in caplog.text


def test_local_analytics_answers_from_computed_facts_without_provider(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "none")
    facts = {
        "dataset": "sales.csv",
        "profile": {
            "rows": 4,
            "columns": 3,
            "column_names": ["revenue", "region", "date"],
            "numeric_summary": [
                {
                    "name": "revenue",
                    "sum": 180.0,
                    "mean": 45.0,
                    "min": 20.0,
                    "max": 80.0,
                    "median": 40.0,
                    "valid_count": 4,
                }
            ],
            "quality": [
                {"column": "revenue", "missing": 1},
                {"column": "region", "missing": 0},
            ],
        },
    }

    result = asyncio.run(copilot.ask_copilot("What is the mean revenue?", facts))

    assert result["provider"] == "local_analytics"
    assert "Local computed analysis (not AI-generated)" in result["answer"]
    assert "revenue: mean 45" in result["answer"]
    assert copilot._OPENAI_CLIENT is None


def test_local_analytics_summary_and_missing_values_are_computed():
    facts = {
        "profile": {
            "rows": 8,
            "columns": 2,
            "column_names": ["amount", "region"],
            "numeric_summary": [
                {
                    "name": "amount",
                    "sum": 28.0,
                    "mean": 4.0,
                    "valid_count": 7,
                }
            ],
            "quality": [{"column": "amount", "missing": 1}, {"column": "region", "missing": 0}],
        },
    }

    summary = copilot._local_analytics_answer("Summarize this dataset.", facts)
    missing = copilot._local_analytics_answer("How many missing values are there?", facts)

    assert summary is not None and "8 records; 2 columns" in summary and "mean 4" in summary
    assert missing is not None and "Total missing values: 1" in missing and "amount: 1" in missing


def _local_copilot_facts():
    dataset = pd.DataFrame(
        [
            {"date": "2026-01-01", "region": "North", "revenue": 100, "quantity": 1},
            {"date": "2026-01-02", "region": "South", "revenue": 200, "quantity": 3},
            {"date": "2026-01-03", "region": "North", "revenue": None, "quantity": 5},
            {"date": "2026-01-01", "region": "North", "revenue": 100, "quantity": 1},
        ]
    )
    return {"profile": profile(dataset, include_all_summaries=True)}


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How many records and columns are in this dataset?", "4 records and 4 columns"),
        ("List the column names.", "date, region, revenue, quantity"),
        ("List column names and data types.", "revenue: float64"),
        ("Show missing values per column.", "revenue: 1"),
        ("How many duplicate records are there?", "1 duplicate records"),
        ("Show numeric summaries.", "revenue: sum 400; mean 133.33; median 100; minimum 100; maximum 200"),
        ("What are the min and max values for revenue?", "Highest observed numeric value: 200 in revenue; Lowest observed numeric value: 100 in revenue"),
        ("What are the mean and median for revenue?", "revenue: mean 133.33; median 100"),
        ("What is the highest value?", "Highest observed numeric value: 200 in revenue"),
        ("What is the lowest value?", "Lowest observed numeric value: 1 in quantity"),
        ("Show value counts for region.", "North: 3, South: 1"),
    ],
)
def test_local_copilot_question_types_use_only_computed_profile(monkeypatch, question, expected):
    monkeypatch.setattr(settings, "ai_provider", "groq")

    def reject_provider_call(*args, **kwargs):
        raise AssertionError("A local analytics question must not call an AI provider.")

    monkeypatch.setattr(copilot, "_get_openai_client", reject_provider_call)
    result = asyncio.run(copilot.ask_copilot(question, _local_copilot_facts()))

    assert result["provider"] == "local_analytics"
    assert result["answer"].startswith("Local computed analysis (not AI-generated)")
    assert expected in result["answer"]


@pytest.mark.parametrize("extension", [".csv", ".xlsx"])
def test_local_record_and_column_counts_support_csv_and_excel(monkeypatch, extension):
    monkeypatch.setattr(settings, "ai_provider", "groq")
    dataset = pd.DataFrame(
        [{"region": "North", "revenue": 10}, {"region": "South", "revenue": 20}]
    )
    source = BytesIO()
    if extension == ".csv":
        source.write(dataset.to_csv(index=False).encode("utf-8"))
    else:
        dataset.to_excel(source, index=False)
    source.seek(0)
    loaded_dataset = read_dataset(source, extension)
    facts = {"profile": profile(loaded_dataset, include_all_summaries=True)}

    def reject_provider_call(*args, **kwargs):
        raise AssertionError("A local analytics question must not call an AI provider.")

    monkeypatch.setattr(copilot, "_get_openai_client", reject_provider_call)
    result = asyncio.run(
        copilot.ask_copilot("How many records and columns are in this dataset?", facts)
    )

    assert result["provider"] == "local_analytics"
    assert "2 records and 2 columns" in result["answer"]
    assert "region, revenue" in result["answer"]


def test_openai_model_access_error_is_not_reported_as_bad_credentials(monkeypatch):
    from openai import APIStatusError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    error = APIStatusError(
        "model unavailable",
        response=httpx.Response(404, request=request),
        body={"error": {"code": "model_not_found"}},
    )
    _install_openai_error(monkeypatch, error)

    with pytest.raises(copilot.CopilotProviderError) as raised:
        asyncio.run(copilot.ask_copilot("Question", {"profile": {}}))

    assert raised.value.status_code == 503
    assert copilot.provider_readiness()["status"] == "model_unavailable"


def test_openai_service_outage_is_reported_as_unavailable(monkeypatch):
    from openai import APIStatusError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    error = APIStatusError(
        "provider outage",
        response=httpx.Response(503, request=request),
        body={"error": {"code": "server_error"}},
    )
    _install_openai_error(monkeypatch, error)

    with pytest.raises(copilot.CopilotProviderError) as raised:
        asyncio.run(copilot.ask_copilot("Question", {"profile": {}}))

    assert raised.value.status_code == 502
    assert copilot.provider_readiness()["status"] == "temporarily_unavailable"


def test_openai_timeout_maps_to_gateway_timeout(monkeypatch):
    from openai import APITimeoutError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")

    class FakeCompletions:
        async def create(self, **kwargs):
            raise APITimeoutError(request=request)

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key-not-a-real-credential")

    with pytest.raises(copilot.CopilotProviderError) as error:
        asyncio.run(copilot.ask_copilot("Question", {"profile": {}}))

    assert error.value.status_code == 504
    assert "timed out" in str(error.value)
    assert copilot.provider_readiness()["status"] == "temporarily_unavailable"


def test_openai_connection_error_maps_to_bad_gateway(monkeypatch):
    from openai import APIConnectionError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    _install_openai_error(monkeypatch, APIConnectionError(request=request))

    with pytest.raises(copilot.CopilotProviderError) as raised:
        asyncio.run(copilot.ask_copilot("Question", {"profile": {}}))

    assert raised.value.status_code == 502
    assert raised.value.provider_status == "temporarily_unavailable"


def test_models_list_diagnostic_uses_same_sanitized_401_classification(monkeypatch, caplog):
    from openai import AuthenticationError

    request = httpx.Request("GET", "https://api.openai.com/v1/models")
    error = AuthenticationError(
        "credential rejected",
        response=httpx.Response(401, request=request),
        body={"error": {"code": "invalid_api_key"}},
    )

    class FakeModels:
        async def list(self, **kwargs):
            raise error

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

        async def close(self):
            return None

    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key-not-a-real-credential")

    with caplog.at_level(logging.WARNING, logger="app.services.copilot"):
        with pytest.raises(copilot.CopilotProviderError) as raised:
            asyncio.run(copilot.diagnose_openai_authentication())

    assert raised.value.provider_status == "authentication_failed"
    assert raised.value.upstream_status_code == 401
    assert raised.value.provider_error_code == "invalid_api_key"
    assert "test-key-not-a-real-credential" not in caplog.text
