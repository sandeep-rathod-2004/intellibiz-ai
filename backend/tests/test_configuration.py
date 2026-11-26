import pytest
from pathlib import Path

from app.core.config import (
    BACKEND_ENV_FILE,
    Settings,
    openai_configuration_metadata,
    settings,
)


def test_backend_dotenv_path_is_absolute_and_anchored_to_backend():
    assert Path(BACKEND_ENV_FILE).is_absolute()
    assert Path(BACKEND_ENV_FILE).parent.name == "backend"


def test_environment_variable_overrides_dotenv_key(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=dotenv-test-key\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "process-test-key")

    loaded = Settings(_env_file=env_file)

    assert loaded.openai_api_key == "process-test-key"


def test_groq_provider_and_token_budget_load_from_environment_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AI_PROVIDER=groq\n"
        "GROQ_API_KEY=test-groq-key\n"
        "GROQ_MODEL=openai/gpt-oss-20b\n"
        "GROQ_BASE_URL=https://api.groq.com/openai/v1\n"
        "COPILOT_TOKEN_BUDGET=384\n",
        encoding="utf-8",
    )
    for key in ("AI_PROVIDER", "GROQ_API_KEY", "GROQ_MODEL", "GROQ_BASE_URL", "COPILOT_TOKEN_BUDGET"):
        monkeypatch.delenv(key, raising=False)

    loaded = Settings(_env_file=env_file)

    assert loaded.ai_provider == "groq"
    assert loaded.groq_api_key == "test-groq-key"
    assert loaded.groq_model == "openai/gpt-oss-20b"
    assert loaded.groq_base_url == "https://api.groq.com/openai/v1"
    assert loaded.copilot_token_budget == 384


def test_key_source_metadata_does_not_expose_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=dotenv-test-key\n", encoding="utf-8")
    monkeypatch.setattr("app.core.config.BACKEND_ENV_FILE", env_file)
    monkeypatch.setattr(settings, "openai_api_key", "process-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "process-test-key")

    metadata = openai_configuration_metadata()

    assert metadata["key_source"] == "process_environment"
    assert metadata["settings_match_current_source"] is True
    assert metadata["settings_match_backend_dotenv"] is False
    assert "process-test-key" not in repr(metadata)
    assert "dotenv-test-key" not in repr(metadata)


def test_stale_loaded_key_is_detected_without_reporting_it(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=new-dotenv-test-key\n", encoding="utf-8")
    monkeypatch.setattr("app.core.config.BACKEND_ENV_FILE", env_file)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(settings, "openai_api_key", "old-loaded-test-key")

    metadata = openai_configuration_metadata()

    assert metadata["key_source"] == "backend_dotenv"
    assert metadata["settings_match_current_source"] is False
    assert "old-loaded-test-key" not in repr(metadata)
    assert "new-dotenv-test-key" not in repr(metadata)


def _production_settings(**overrides):
    values = {
        "environment": "production",
        "secret_key": "production-secret-" + ("x" * 40),
        "auto_create_schema": False,
        "data_storage_backend": "supabase",
        "supabase_url": "https://project.supabase.co",
        "supabase_service_role_key": "test-service-role-key",
        "cors_origins": "https://app.example.com",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_settings_require_persistent_storage():
    with pytest.raises(ValueError, match="persistent object storage"):
        _production_settings(data_storage_backend="local")


@pytest.mark.parametrize(
    "cors_origins",
    [
        "http://app.example.com",
        "*",
        "https://app.example.com/path",
        "",
    ],
)
def test_production_settings_require_exact_https_cors_origins(cors_origins):
    with pytest.raises(ValueError, match="HTTPS"):
        _production_settings(cors_origins=cors_origins)


def test_production_settings_accept_private_storage_and_exact_https_origin():
    config = _production_settings()

    assert config.data_storage_backend == "supabase"
    assert config.cors_origins == "https://app.example.com"
