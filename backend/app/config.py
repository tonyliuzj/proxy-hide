from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_port_range(value: str) -> tuple[int, int]:
    first, _, last = value.strip().partition("-")
    try:
        low, high = int(first), int(last or first)
    except ValueError as exc:
        raise ValueError("listener ports must look like 10000-10019") from exc
    if not 1024 <= low <= high <= 65535:
        raise ValueError("listener ports must be an ascending range within 1024-65535")
    if high - low >= 1000:
        raise ValueError("listener ports may span at most 1000 ports")
    return low, high


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PH_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = Field(
        default="postgresql+asyncpg://proxyhide:proxyhide@postgres:5432/proxyhide",
        validation_alias=AliasChoices("PH_DATABASE_URL", "DATABASE_URL"),
    )
    redis_url: str = Field(
        default="redis://redis:6379/0", validation_alias=AliasChoices("PH_REDIS_URL", "REDIS_URL")
    )
    session_cookie_name: str = "proxyhide_session"
    csrf_cookie_name: str = "proxyhide_csrf"
    session_ttl_seconds: int = 60 * 60 * 12
    session_cookie_secure: bool = Field(
        default=False,
        validation_alias=AliasChoices("PH_SESSION_COOKIE_SECURE", "SESSION_COOKIE_SECURE"),
    )
    session_secret: str = Field(
        default="development-only-change-me",
        validation_alias=AliasChoices("PH_SESSION_SECRET", "PROXYHIDE_SESSION_SECRET"),
    )
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        validation_alias=AliasChoices("PH_ALLOWED_ORIGINS", "WEB_ORIGIN"),
    )
    encryption_keys: str = Field(
        default="",
        validation_alias=AliasChoices("PH_ENCRYPTION_KEYS", "PROXYHIDE_ENCRYPTION_KEY"),
    )
    endpoint_hmac_key: str = Field(
        default="development-only-change-me",
        validation_alias=AliasChoices("PH_ENDPOINT_HMAC_KEY", "PROXYHIDE_ENDPOINT_PEPPER"),
    )
    public_gateway_host: str = Field(
        default="localhost",
        validation_alias=AliasChoices("PH_PUBLIC_GATEWAY_HOST", "PUBLIC_PLAINTEXT_PROXY_HOST"),
    )
    public_gateway_http_port: int = Field(
        default=9000,
        validation_alias=AliasChoices("PH_PUBLIC_GATEWAY_HTTP_PORT", "PUBLIC_PLAINTEXT_PROXY_PORT"),
    )
    public_gateway_tls_host: str = Field(
        default="localhost",
        validation_alias=AliasChoices("PH_PUBLIC_GATEWAY_TLS_HOST", "PUBLIC_SECURE_PROXY_HOST"),
    )
    public_gateway_tls_port: int = Field(
        default=443,
        validation_alias=AliasChoices("PH_PUBLIC_GATEWAY_TLS_PORT", "PUBLIC_SECURE_PROXY_PORT"),
    )
    gateway_bind_host: str = Field(
        default="0.0.0.0",
        validation_alias=AliasChoices("PH_GATEWAY_HOST", "GATEWAY_HOST"),
    )
    gateway_bind_port: int = Field(
        default=9000,
        validation_alias=AliasChoices("PH_GATEWAY_PORT", "GATEWAY_PORT"),
    )
    public_gateway_socks_port: int = Field(
        default=1080,
        validation_alias=AliasChoices("PH_PUBLIC_GATEWAY_SOCKS_PORT", "PUBLIC_SOCKS_PROXY_PORT"),
    )
    gateway_socks_bind_port: int = Field(
        default=1080,
        validation_alias=AliasChoices("PH_GATEWAY_SOCKS_PORT", "GATEWAY_SOCKS_PORT"),
    )
    gateway_listener_ports: str = Field(
        default="10000-10019",
        validation_alias=AliasChoices("PH_GATEWAY_LISTENER_PORTS", "GATEWAY_LISTENER_PORTS"),
    )
    trusted_proxy_cidrs: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("PH_TRUSTED_PROXY_CIDRS", "TRUSTED_PROXY_CIDRS"),
    )
    jobs_stream: str = "proxyhide:jobs"
    jobs_consumer_group: str = "workers"
    jobs_dead_letter_stream: str = "proxyhide:jobs:dead"
    gateway_snapshot_key: str = "proxyhide:gateway:snapshot"
    gateway_reload_channel: str = "proxyhide:gateway:reload"
    max_page_size: int = 200
    source_fetch_timeout_seconds: float = 15.0
    source_max_bytes: int = 10 * 1024 * 1024
    general_probe_url: str = Field(
        default="https://api.ipify.org?format=json",
        validation_alias=AliasChoices("PH_GENERAL_PROBE_URL", "GENERAL_PROBE_URL", "PROBE_URL"),
    )
    geoip_database_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PH_GEOIP_DATABASE_PATH", "GEOIP_DATABASE_PATH"),
    )
    probe_requests_per_minute: int = 120
    trusted_api_proxy_cidrs: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("PH_TRUSTED_API_PROXY_CIDRS", "TRUSTED_API_PROXY_CIDRS"),
    )

    @field_validator("database_url")
    @classmethod
    def require_async_database_driver(cls, value: str) -> str:
        if "+asyncpg" not in value and "+aiosqlite" not in value:
            raise ValueError("database_url must use an async SQLAlchemy driver")
        return value

    @field_validator("gateway_listener_ports")
    @classmethod
    def validate_listener_ports(cls, value: str) -> str:
        value = value.strip()
        if value:
            parse_port_range(value)
        return value

    @property
    def listener_port_range(self) -> tuple[int, int] | None:
        """Inclusive range for dedicated endpoint ports; ``None`` disables them."""
        if not self.gateway_listener_ports:
            return None
        return parse_port_range(self.gateway_listener_ports)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip().rstrip("/") for part in value.split(",") if part.strip()]
        return value

    @field_validator("trusted_proxy_cidrs", "trusted_api_proxy_cidrs", mode="before")
    @classmethod
    def split_cidrs(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def keep_listener_ports_off_shared_ports(self) -> Settings:
        window = self.listener_port_range
        if window is not None:
            shared = {self.gateway_bind_port, self.gateway_socks_bind_port, 8000}
            if any(window[0] <= port <= window[1] for port in shared):
                raise ValueError("gateway listener ports must not include the shared gateway ports")
        return self

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> Settings:
        if self.environment == "production":
            if not self.encryption_keys:
                raise ValueError("an encryption key is required in production")
            if self.endpoint_hmac_key == "development-only-change-me":
                raise ValueError("a non-default endpoint HMAC key is required in production")
            if self.session_secret == "development-only-change-me":
                raise ValueError("a non-default session secret is required in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
