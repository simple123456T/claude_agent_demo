from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SQL_IDENTIFIER_PATTERN = r"^[a-z_][a-z0-9_]{0,62}$"


class Settings(BaseSettings):
    """Environment-backed settings. Secret values are never included in API models."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8001
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    database_url: SecretStr
    control_plane_schema: str = Field(default="datagent", pattern=SQL_IDENTIFIER_PATTERN)
    redis_url: SecretStr
    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: SecretStr | None = None

    db_connect_timeout: int = Field(default=3, ge=1, le=30)
    redis_connect_timeout: float = Field(default=2.0, ge=0.5, le=30)
    milvus_connect_timeout: float = Field(default=3.0, ge=0.5, le=30)

    model_base_url: str | None = None
    model_api_key: SecretStr | None = None
    model_name: str | None = None
    model_timeout_seconds: float = Field(default=60.0, ge=1, le=600)
    model_json_mode: bool = True

    query_timeout_ms: int = Field(default=15000, ge=1000, le=300000)
    demo_schema: str = Field(default="datagent_demo", pattern=SQL_IDENTIFIER_PATTERN)

    # Local-development sign-in. Only honoured when APP_ENV=development, requests come from
    # loopback, and no real OIDC provider is configured; refused outright in production.
    dev_auth_enabled: bool = False

    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_jwks_url: str | None = None
    oidc_bootstrap_admin_subjects: str = ""
    oidc_clock_skew_seconds: int = Field(default=60, ge=0, le=300)

    @field_validator(
        "milvus_token",
        "model_base_url",
        "model_api_key",
        "model_name",
        "oidc_issuer",
        "oidc_audience",
        "oidc_client_id",
        "oidc_client_secret",
        "oidc_jwks_url",
        mode="before",
    )
    @classmethod
    def blank_as_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def sqlalchemy_database_url(self) -> str:
        url = self.database_url.get_secret_value()
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def model_configured(self) -> bool:
        return bool(self.model_base_url and self.model_name)

    @property
    def effective_oidc_audience(self) -> str | None:
        return self.oidc_audience or self.oidc_client_id

    @property
    def oidc_configured(self) -> bool:
        return bool(self.oidc_issuer and self.effective_oidc_audience)

    @property
    def dev_auth_active(self) -> bool:
        return self.dev_auth_enabled and not self.is_production and not self.oidc_configured

    @property
    def bootstrap_admin_subjects(self) -> frozenset[str]:
        return frozenset(
            item.strip() for item in self.oidc_bootstrap_admin_subjects.split(",") if item.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
