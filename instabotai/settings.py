"""Canonical runtime configuration for InstabotAI."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed runtime settings."""

    model_config = SettingsConfigDict(
        env_prefix="INSTABOTAI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "development"
    state_db_path: str = "data/instabotai.sqlite3"

    ai_provider: Literal["ollama", "openai_compatible"] = "ollama"
    ai_model: str = "llama3.2:3b"
    ai_base_url: str = "http://127.0.0.1:11434"
    ai_api_key: SecretStr | None = None
    ai_timeout_seconds: float = Field(default=90.0, ge=1.0, le=300.0)
    ai_temperature: float = Field(default=0.15, ge=0.0, le=1.0)
    ai_max_retries: int = Field(default=2, ge=0, le=5)
    ai_max_context_chars: int = Field(default=24_000, ge=4_000, le=200_000)
    ai_min_decision_score: float = Field(default=0.65, ge=0.0, le=1.0)
    ai_enable_critic: bool = True

    instagram_provider: Literal["official", "private"] = "official"

    meta_graph_api_version: str = "v26.0"
    instagram_access_token: SecretStr | None = None
    instagram_account_id: str | None = None
    meta_graph_base_url: str = "https://graph.instagram.com"

    private_instagram_username: str | None = None
    private_instagram_password: SecretStr | None = None
    private_session_path: str = "data/private-instagram-session.json"
    private_proxy_url: SecretStr | None = None
    private_image_max_bytes: int = Field(default=15_000_000, ge=100_000, le=50_000_000)

    private_research_mode: bool = False
    private_credentials_file: str | None = None
    private_device_profile_file: str | None = None
    private_headers_file: str | None = None
    private_user_agent: str | None = None
    private_challenge_code: SecretStr | None = None
    private_replacement_password: SecretStr | None = None
    private_phone_number: str | None = None
    private_request_trace_path: str | None = None

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

    # Durable campaign/scheduler worker.
    campaign_worker_poll_seconds: float = Field(default=5.0, ge=1.0, le=300.0)
    campaign_plan_lease_seconds: int = Field(default=300, ge=30, le=3600)
    campaign_plan_retry_base_seconds: int = Field(default=60, ge=5, le=3600)
    campaign_plan_retry_cap_seconds: int = Field(default=1800, ge=30, le=86_400)
    campaign_action_lease_seconds: int = Field(default=180, ge=30, le=3600)
    campaign_action_max_attempts: int = Field(default=3, ge=1, le=20)
    campaign_action_retry_base_seconds: int = Field(default=30, ge=5, le=3600)
    campaign_action_retry_cap_seconds: int = Field(default=900, ge=30, le=86_400)

    # Consumer console is local-only by default.
    ui_host: str = "127.0.0.1"
    ui_port: int = Field(default=8765, ge=1024, le=65535)
    ui_open_browser: bool = True
    ui_allow_remote: bool = False
    ui_ai_max_concurrency: int = Field(default=2, ge=1, le=16)
    ui_research_max_concurrency: int = Field(default=1, ge=1, le=8)
    ui_campaign_max_concurrency: int = Field(default=1, ge=1, le=8)

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

    @field_validator("ai_model", "ai_base_url", "ui_host")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("required runtime text values must not be empty")
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable configuration snapshot."""

    return Settings()
