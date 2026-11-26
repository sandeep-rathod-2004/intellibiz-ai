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
    supabase_storage_driver: Literal["s3", "rest"] = "rest"
    supabase_url: str = ""
    supabase_storage_bucket: str = ""
    supabase_secret_key: str = ""
    supabase_service_role_key: str = ""
    supabase_s3_endpoint_url: str = (
        "https://rxoxymrcccaqxbmqfazp.storage.supabase.co/storage/v1/s3"
    )
    supabase_s3_region: str = "ap-south-1"
    supabase_s3_access_key_id: str = ""
    supabase_s3_secret_access_key: str = ""
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
            if not self.supabase_url.strip():
                raise ValueError("Supabase storage requires SUPABASE_URL.")
            try:
                supabase_url = urlsplit(self.supabase_url.strip())
                valid_supabase_url = (
                    supabase_url.scheme == "https"
                    and bool(supabase_url.hostname)
                    and supabase_url.username is None
                    and supabase_url.password is None
                    and not supabase_url.query
                    and not supabase_url.fragment
                )
            except ValueError:
                valid_supabase_url = False
            if not valid_supabase_url:
                raise ValueError("SUPABASE_URL must be a valid HTTPS URL.")
            if not self.supabase_storage_bucket.strip():
                raise ValueError("Supabase storage requires SUPABASE_STORAGE_BUCKET.")
            if self.supabase_secret_key.strip() and not self.supabase_secret_key.strip().startswith(
                "sb_secret_"
            ):
                raise ValueError("SUPABASE_SECRET_KEY must use the sb_secret_ format.")
            if not (
                self.supabase_secret_key.strip()
                or self.supabase_service_role_key.strip()
            ):
                raise ValueError(
                    "Supabase storage requires SUPABASE_SECRET_KEY or "
                    "SUPABASE_SERVICE_ROLE_KEY."
                )
            if self.supabase_storage_driver == "s3":
                endpoint = urlsplit(self.supabase_s3_endpoint_url.strip())
                if (
                    endpoint.scheme != "https"
                    or not endpoint.netloc
                    or endpoint.query
                    or endpoint.fragment
                ):
                    raise ValueError(
                        "SUPABASE_S3_ENDPOINT_URL must be an HTTPS endpoint URL."
                    )
                if not self.supabase_s3_region.strip():
                    raise ValueError(
                        "Supabase S3 storage requires SUPABASE_S3_REGION."
                    )
                if not self.supabase_s3_access_key_id.strip():
                    raise ValueError(
                        "Supabase S3 storage requires SUPABASE_S3_ACCESS_KEY_ID."
                    )
                if not self.supabase_s3_secret_access_key.strip():
                    raise ValueError(
                        "Supabase S3 storage requires SUPABASE_S3_SECRET_ACCESS_KEY."
                    )
        if self.environment.lower() in {"prod", "production"}:
            database_url = self.database_url.strip()
            try:
                database = urlsplit(database_url)
            except ValueError:
                database = None
            if (
                database is None
                or database.scheme not in {"postgresql", "postgresql+psycopg"}
                or not database.hostname
                or database.path in {"", "/"}
            ):
                raise ValueError(
                    "Production requires DATABASE_URL to be a valid PostgreSQL URL "
                    "using postgresql:// or postgresql+psycopg://."
                )
            if database.scheme == "postgresql":
                self.database_url = "postgresql+psycopg://" + database_url.split(
                    "://",
                    1,
                )[1]
            else:
                self.database_url = database_url
            if len(self.secret_key) < 32 or self.secret_key == "dev-only-change-this-secret-before-deploying":
                raise ValueError("Production requires a unique SECRET_KEY of at least 32 characters")
            if self.auto_create_schema:
                raise ValueError("Production must use Alembic migrations; set AUTO_CREATE_SCHEMA=false")
            if self.data_storage_backend != "supabase":
                raise ValueError(
                    "Production requires persistent object storage; configure "
                    "DATA_STORAGE_BACKEND=supabase and its credentials."
                )
            if self.supabase_storage_driver != "rest":
                raise ValueError(
                    "Production currently requires SUPABASE_STORAGE_DRIVER=rest."
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
