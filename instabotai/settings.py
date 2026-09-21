"""Canonical runtime configuration for InstabotAI."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed runtime settings.

    Secrets are never accepted from browser sessions or checked into the repository.
    """

    model_config = SettingsConfigDict(
        env_prefix="INSTABOTAI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "development"

    meta_graph_api_version: str = "v26.0"
    instagram_access_token: SecretStr | None = None
    instagram_account_id: str | None = None
    meta_graph_base_url: str = "https://graph.instagram.com"

    research_user_agent: str = (
        "InstabotAI/2.0 (+https://github.com/agustealo/instabotai; compliant-public-web-research)"
    )
    research_blocked_domains: tuple[str, ...] = (
        "instagram.com",
        "facebook.com",
        "threads.net",
        "messenger.com",
    )
    research_allowed_domains: tuple[str, ...] = ()
    research_confidence_threshold: float = Field(default=0.80, ge=0.50, le=0.99)
    research_min_pages: int = Field(default=2, ge=1, le=20)
    research_max_pages: int = Field(default=20, ge=1, le=100)
    research_top_k_links: int = Field(default=4, ge=1, le=20)
    research_min_gain_threshold: float = Field(default=0.08, ge=0.0, le=1.0)

    require_write_approval: bool = True
    write_confidence_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    daily_publish_limit: int = Field(default=4, ge=0, le=50)
    daily_comment_reply_limit: int = Field(default=40, ge=0, le=500)
    daily_comment_moderation_limit: int = Field(default=100, ge=0, le=1000)

    request_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    provider_max_retries: int = Field(default=3, ge=0, le=8)

    @field_validator("meta_graph_api_version")
    @classmethod
    def validate_graph_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("v"):
            raise ValueError("meta_graph_api_version must look like vXX.X")
        major_minor = normalized[1:].split(".")
        if len(major_minor) != 2 or not all(part.isdigit() for part in major_minor):
            raise ValueError("meta_graph_api_version must look like vXX.X")
        return normalized

    @field_validator("research_blocked_domains", "research_allowed_domains")
    @classmethod
    def normalize_domains(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = []
        for value in values:
            domain = value.strip().lower().rstrip(".")
            if domain:
                normalized.append(domain)
        return tuple(dict.fromkeys(normalized))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable configuration snapshot."""

    return Settings()
