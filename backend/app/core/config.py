from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
    app_port: int = 8000
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    database_url: SecretStr
    redis_url: SecretStr
    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: SecretStr | None = None

    db_connect_timeout: int = Field(default=3, ge=1, le=30)
    redis_connect_timeout: float = Field(default=2.0, ge=0.5, le=30)
    milvus_connect_timeout: float = Field(default=3.0, ge=0.5, le=30)

    model_base_url: str | None = None
    model_api_key: SecretStr | None = None
    model_name: str | None = None

    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None

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
    def model_configured(self) -> bool:
        return bool(self.model_base_url and self.model_name)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
