"""Typed campaign, scheduling, approval, and worker domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from instabotai.domain import PlannedAction
from instabotai.intelligence import EvidenceItem, IntelligenceDecision


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class CampaignMode(StrEnum):
    SUPERVISED = "supervised"
    POLICY_MANAGED = "policy_managed"


class JobStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    SCHEDULED = "scheduled"
    LEASED = "leased"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class Campaign(BaseModel):
    campaign_id: str = Field(default_factory=lambda: uuid4().hex, min_length=16, max_length=64)
    name: str = Field(min_length=2, max_length=160)
    objective: str = Field(min_length=3, max_length=2_000)
    status: CampaignStatus = CampaignStatus.DRAFT
    mode: CampaignMode = CampaignMode.SUPERVISED
    cadence_minutes: int = Field(default=1440, ge=5, le=43_200)
    action_delay_minutes: int = Field(default=0, ge=0, le=10_080)
    evidence: tuple[EvidenceItem, ...] = Field(default=(), max_length=100)
    context: dict[str, Any] = Field(default_factory=dict)
    research_seed_urls: tuple[str, ...] = Field(default=(), max_length=20)
    research_before_plan: bool = False
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    consecutive_failures: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_planning_inputs(self) -> Campaign:
        if self.research_before_plan and not self.research_seed_urls:
            raise ValueError("research_before_plan requires at least one research seed URL")
        if not self.evidence and not (self.research_before_plan and self.research_seed_urls):
            raise ValueError("campaign requires evidence or enabled research seed URLs")
        return self


class CampaignJob(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid4().hex, min_length=16, max_length=64)
    campaign_id: str
    decision_id: str
    action: PlannedAction
    status: JobStatus
    scheduled_for: datetime
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=20)
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    last_error: str | None = None
    provider_result: Any | None = None
    outcome_reward: float | None = Field(default=None, ge=0.0, le=1.0)
    outcome_note: str = Field(default="", max_length=4_000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class CampaignPlanOutcome(BaseModel):
    campaign: Campaign
    decision: IntelligenceDecision
    job: CampaignJob | None = None
    research_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class WorkerTick(BaseModel):
    planned_campaign_id: str | None = None
    planned_decision_id: str | None = None
    created_job_id: str | None = None
    planning_error: str | None = None
    executed_job_id: str | None = None
    execution_status: JobStatus | None = None
    execution_error: str | None = None
