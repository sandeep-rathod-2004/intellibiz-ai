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
        "database_url": (
            "postgresql+psycopg://test-user:test-password@localhost:5432/intellibiz_test"
        ),
        "auto_create_schema": False,
        "data_storage_backend": "supabase",
        "supabase_storage_driver": "rest",
        "supabase_url": "https://project.supabase.co",
        "supabase_storage_bucket": "intellibiz-datasets",
        "supabase_service_role_key": "test-service-role-key",
        "supabase_s3_access_key_id": "test-access-key",
        "supabase_s3_secret_access_key": "test-s3-secret",
        "cors_origins": "https://app.example.com",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_storage_defaults_keep_local_backend_and_recommend_rest_driver(monkeypatch):
    monkeypatch.delenv("DATA_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("SUPABASE_STORAGE_DRIVER", raising=False)

    config = Settings(_env_file=None)

    assert config.data_storage_backend == "local"
    assert config.supabase_storage_driver == "rest"


@pytest.mark.parametrize(
    "database_url",
    ["sqlite:///./intellibiz.db", "sqlite:///:memory:"],
)
def test_production_settings_reject_sqlite_database_urls(database_url):
    with pytest.raises(ValueError, match="valid PostgreSQL URL"):
        _production_settings(database_url=database_url)


@pytest.mark.parametrize(
    ("database_url", "expected_url"),
    [
        (
            "postgresql://test-user:test-password@localhost:5432/intellibiz_test",
            "postgresql+psycopg://test-user:test-password@localhost:5432/intellibiz_test",
        ),
        (
            "postgresql+psycopg://test-user:test-password@localhost:5432/intellibiz_test",
            "postgresql+psycopg://test-user:test-password@localhost:5432/intellibiz_test",
        ),
    ],
)
def test_production_settings_accept_postgresql_database_urls(database_url, expected_url):
    config = _production_settings(database_url=database_url)

    assert config.database_url == expected_url


@pytest.mark.parametrize("database_url", ["", "not-a-url", "mysql://db.example/test"])
def test_production_settings_reject_invalid_database_urls(database_url):
    with pytest.raises(ValueError, match="valid PostgreSQL URL"):
        _production_settings(database_url=database_url)


def test_development_settings_can_use_sqlite():
    config = Settings(
        _env_file=None,
        environment="development",
        database_url="sqlite:///:memory:",
    )

    assert config.database_url == "sqlite:///:memory:"


def test_supabase_configuration_requires_url():
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        _production_settings(supabase_url="")


def test_supabase_configuration_requires_bucket():
    with pytest.raises(ValueError, match="SUPABASE_STORAGE_BUCKET"):
        _production_settings(supabase_storage_bucket="")


def test_supabase_configuration_requires_a_server_side_key():
    with pytest.raises(ValueError, match="SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY"):
        _production_settings(
            supabase_secret_key="",
            supabase_service_role_key="",
        )


def test_supabase_configuration_accepts_new_secret_key():
    config = _production_settings(
        supabase_secret_key="sb_secret_test-key",
        supabase_service_role_key="",
    )

    assert config.supabase_secret_key == "sb_secret_test-key"


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("supabase_s3_access_key_id", "SUPABASE_S3_ACCESS_KEY_ID"),
        ("supabase_s3_secret_access_key", "SUPABASE_S3_SECRET_ACCESS_KEY"),
    ],
)
def test_supabase_s3_configuration_requires_distinct_s3_credentials(field, message):
    with pytest.raises(ValueError, match=message):
        _production_settings(supabase_storage_driver="s3", **{field: ""})


def test_supabase_s3_configuration_uses_project_endpoint_and_region_defaults():
    config = _production_settings(
        environment="development",
        supabase_storage_driver="s3",
    )

    assert config.supabase_s3_endpoint_url == (
        "https://rxoxymrcccaqxbmqfazp.storage.supabase.co/storage/v1/s3"
    )
    assert config.supabase_s3_region == "ap-south-1"


def test_supabase_s3_configuration_loads_the_named_environment_variables(
    monkeypatch,
):
    env_values = {
        "DATA_STORAGE_BACKEND": "supabase",
        "SUPABASE_STORAGE_DRIVER": "s3",
        "ENVIRONMENT": "development",
        "SECRET_KEY": "dev-only-change-this-secret-before-deploying",
        "AUTO_CREATE_SCHEMA": "true",
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_STORAGE_BUCKET": "private-datasets",
        "SUPABASE_SECRET_KEY": "",
        "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
        "SUPABASE_S3_ENDPOINT_URL": (
            "https://rxoxymrcccaqxbmqfazp.storage.supabase.co/storage/v1/s3"
        ),
        "SUPABASE_S3_REGION": "ap-south-1",
        "SUPABASE_S3_ACCESS_KEY_ID": "test-access-key",
        "SUPABASE_S3_SECRET_ACCESS_KEY": "test-s3-secret",
    }
    for key, value in env_values.items():
        monkeypatch.setenv(key, value)

    config = Settings(_env_file=None)

    assert config.supabase_storage_driver == "s3"
    assert config.supabase_s3_endpoint_url == env_values["SUPABASE_S3_ENDPOINT_URL"]
    assert config.supabase_s3_region == "ap-south-1"
    assert config.supabase_s3_access_key_id == "test-access-key"
    assert config.supabase_s3_secret_access_key == "test-s3-secret"


def test_supabase_s3_configuration_rejects_non_https_endpoint():
    with pytest.raises(ValueError, match="HTTPS endpoint URL"):
        _production_settings(
            supabase_storage_driver="s3",
            supabase_s3_endpoint_url="http://example.test/s3",
        )


def test_rest_storage_driver_remains_available_without_s3_credentials():
    config = _production_settings(
        supabase_storage_driver="rest",
        supabase_s3_access_key_id="",
        supabase_s3_secret_access_key="",
    )

    assert config.supabase_storage_driver == "rest"


def test_supabase_configuration_rejects_malformed_new_secret_key():
    with pytest.raises(ValueError, match="sb_secret_ format"):
        _production_settings(supabase_secret_key="not-a-supabase-secret-key")


def test_production_settings_require_persistent_storage():
    with pytest.raises(ValueError, match="persistent object storage"):
        _production_settings(data_storage_backend="local")


def test_production_settings_require_rest_storage_driver():
    with pytest.raises(ValueError, match="SUPABASE_STORAGE_DRIVER=rest"):
        _production_settings(supabase_storage_driver="s3")


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


@pytest.mark.parametrize(
    "supabase_url",
    [
        "http://project.supabase.co",
        "not-a-url",
        "https://",
        "https://user:password@project.supabase.co",
        "https://project.supabase.co?token=test",
    ],
)
def test_production_settings_reject_invalid_supabase_urls(supabase_url):
    with pytest.raises(ValueError, match="valid HTTPS URL"):
        _production_settings(supabase_url=supabase_url)


def test_production_settings_accept_valid_supabase_url():
    config = _production_settings(supabase_url="https://project.supabase.co")

    assert config.supabase_url == "https://project.supabase.co"
