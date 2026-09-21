"""Typed domain models for research and Instagram automation."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ActionType(StrEnum):
    """Supported write actions in the modern runtime."""

    PUBLISH_IMAGE = "publish_image"
    REPLY_TO_COMMENT = "reply_to_comment"
    HIDE_COMMENT = "hide_comment"


class ApprovalState(StrEnum):
    """Human approval state for a planned write action."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PlannedAction(BaseModel):
    """A concrete, auditable Instagram write action."""

    action_type: ActionType
    reason: str = Field(min_length=3, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)
    payload: dict[str, Any] = Field(default_factory=dict)
    target_id: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=200)
    approval: ApprovalState = ApprovalState.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UsageSnapshot(BaseModel):
    """Observed usage counters used by the policy engine."""

    published_today: int = Field(default=0, ge=0)
    comment_replies_today: int = Field(default=0, ge=0)
    comments_moderated_today: int = Field(default=0, ge=0)


class ResearchPage(BaseModel):
    """Normalized public-web page used by the adaptive researcher."""

    url: str
    title: str | None = None
    markdown: str
    outbound_links: tuple[str, ...] = ()
    relevance: float = Field(ge=0.0, le=1.0)


class ResearchReport(BaseModel):
    """Result of an adaptive research run."""

    objective: str
    pages: tuple[ResearchPage, ...]
    blocked_urls: tuple[str, ...] = ()
    failed_urls: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    stopped_early: bool = False
