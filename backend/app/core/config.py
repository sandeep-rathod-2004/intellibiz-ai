import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import dotenv_values


BACKEND_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    app_name: str = "IntelliBiz AI"
    environment: str = "development"
    secret_key: str = "dev-only-change-this-secret-before-deploying"
    database_url: str = "sqlite:///./intellibiz.db"
    auto_create_schema: bool = True
    data_storage_backend: Literal["local", "supabase"] = "local"
    supabase_url: str = ""
    supabase_storage_bucket: str = "intellibiz-datasets"
    supabase_service_role_key: str = ""
    access_token_expire_minutes: int = Field(default=720, ge=1, le=10080)
    cors_origins: str = "http://localhost:5173"
    max_upload_mb: int = Field(default=15, ge=1, le=500)
    max_rows: int = Field(default=100000, ge=1, le=1000000)
    max_dataset_cells: int = Field(default=1000000, ge=10000, le=10000000)
    max_xlsx_uncompressed_mb: int = Field(default=128, ge=1, le=1024)
    ai_provider: Literal["none", "local", "groq", "openai", "gemini"] = "groq"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = Field(default=30, gt=0, le=120)
    openai_max_retries: int = Field(default=1, ge=0, le=5)
    openai_max_output_tokens: int = Field(default=1200, ge=64, le=4096)
    copilot_token_budget: int | None = Field(default=None, ge=64, le=4096)
    copilot_max_context_chars: int = Field(default=12000, ge=1000, le=50000)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
    login_requests_per_minute: int = Field(default=20, ge=1, le=1000)
    registration_requests_per_hour: int = Field(default=10, ge=1, le=100)
    copilot_requests_per_minute: int = Field(default=30, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_production_configuration(self) -> "Settings":
        if self.data_storage_backend == "supabase":
            if not self.supabase_url or not self.supabase_storage_bucket or not self.supabase_service_role_key:
                raise ValueError(
                    "Supabase storage requires SUPABASE_URL, SUPABASE_STORAGE_BUCKET, "
                    "and SUPABASE_SERVICE_ROLE_KEY"
                )
        if self.environment.lower() in {"prod", "production"}:
            if len(self.secret_key) < 32 or self.secret_key == "dev-only-change-this-secret-before-deploying":
                raise ValueError("Production requires a unique SECRET_KEY of at least 32 characters")
            if self.auto_create_schema:
                raise ValueError("Production must use Alembic migrations; set AUTO_CREATE_SCHEMA=false")
            if self.data_storage_backend != "supabase":
                raise ValueError(
                    "Production requires persistent object storage; configure "
                    "DATA_STORAGE_BACKEND=supabase and its credentials."
                )
            origins = {origin.strip() for origin in self.cors_origins.split(",") if origin.strip()}
            if not origins:
                raise ValueError("Production requires at least one HTTPS CORS origin.")
            for origin in origins:
                parsed_origin = urlsplit(origin)
                if (
                    parsed_origin.scheme != "https"
                    or not parsed_origin.netloc
                    or parsed_origin.path not in {"", "/"}
                    or parsed_origin.query
                    or parsed_origin.fragment
                ):
                    raise ValueError(
                        "Production CORS_ORIGINS must contain exact HTTPS origins only."
                    )
        return self

    model_config = SettingsConfigDict(
        env_file=BACKEND_ENV_FILE,
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()


def openai_configuration_metadata() -> dict[str, str | bool | None]:
    environment_key = "OPENAI_API_KEY"
    dotenv = dotenv_values(BACKEND_ENV_FILE)
    dotenv_configured = environment_key in dotenv and bool(dotenv[environment_key])
    dotenv_value = dotenv.get(environment_key) or ""
    if environment_key in os.environ:
        source = "process_environment"
        source_value = os.environ[environment_key]
    elif environment_key in dotenv:
        source = "backend_dotenv"
        source_value = dotenv_value
    else:
        source = "unset"
        source_value = ""
    return {
        "env_file": str(BACKEND_ENV_FILE),
        "key_source": source,
        "key_configured": bool(settings.openai_api_key.strip()),
        "process_environment_override_present": environment_key in os.environ,
        "dotenv_key_configured": dotenv_configured,
        "settings_match_backend_dotenv": (
            settings.openai_api_key == dotenv_value if dotenv_configured else None
        ),
        "settings_match_current_source": settings.openai_api_key == source_value,
    }
