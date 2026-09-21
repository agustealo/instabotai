"""Typed, domain-neutral models for model-assisted decision making."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    """One bounded fact supplied to the reasoning system."""

    evidence_id: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=12_000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DecisionCandidate(BaseModel):
    """One model-proposed option before deterministic selection and policy checks."""

    candidate_id: str = Field(min_length=1, max_length=120)
    action: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=3, max_length=2_000)
    confidence: float = Field(ge=0.0, le=1.0)
    expected_utility: float = Field(ge=0.0, le=1.0)
    risk: float = Field(ge=0.0, le=1.0)
    payload: dict[str, Any] = Field(default_factory=dict)
    target_id: str | None = Field(default=None, max_length=500)
    evidence_refs: tuple[str, ...] = ()


class ModelDecision(BaseModel):
    """Validated planner response from a reasoning model."""

    candidates: tuple[DecisionCandidate, ...] = Field(max_length=12)
    assumptions: tuple[str, ...] = Field(default=(), max_length=20)
    uncertainty: str = Field(default="", max_length=2_000)


class DecisionReview(BaseModel):
    """Independent critic response for the selected candidate."""

    support_score: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=1.0)
    should_abstain: bool = False
    missing_evidence: tuple[str, ...] = Field(default=(), max_length=20)
    objections: tuple[str, ...] = Field(default=(), max_length=20)


class ExperienceSummary(BaseModel):
    """Outcome-derived prior used by the deterministic scorer."""

    samples: int = Field(default=0, ge=0)
    mean_reward: float = Field(default=0.5, ge=0.0, le=1.0)
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)


class ModelReply(BaseModel):
    """Normalized response returned by any supported reasoning model adapter."""

    text: str
    provider: str
    model: str
    latency_ms: int = Field(ge=0)


class IntelligenceDecision(BaseModel):
    """Auditable result of model generation plus deterministic adjudication."""

    decision_id: str = Field(default_factory=lambda: uuid4().hex, min_length=16, max_length=64)
    objective: str
    selected: DecisionCandidate | None = None
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    review: DecisionReview | None = None
    assumptions: tuple[str, ...] = ()
    uncertainty: str = ""
    explanation: str
    abstained: bool
    provider: str | None = None
    model: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
