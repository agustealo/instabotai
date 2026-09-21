"""Canonical application service shared by CLI and consumer UI surfaces."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from instabotai.domain import ActionType, PlannedAction, ResearchReport
from instabotai.intelligence import (
    DecisionJournal,
    EvidenceItem,
    IntelligenceDecision,
    IntelligenceProbe,
    build_intelligence_engine,
    build_reasoning_model,
    probe_reasoning_model,
)
from instabotai.providers import build_instagram_provider
from instabotai.research import AdaptiveResearchService, Crawl4AIFetcher, ResearchAccessPolicy
from instabotai.settings import Settings


class AIStatus(BaseModel):
    """Safe-to-display AI runtime status."""

    provider: str
    model: str
    base_url: str
    api_key_configured: bool
    critic_enabled: bool
    min_decision_score: float
    timeout_seconds: float
    temperature: float
    max_retries: int
    max_context_chars: int


class InstagramStatus(BaseModel):
    """Safe-to-display Instagram provider status."""

    provider: str
    graph_api_version: str
    account_configured: bool
    token_configured: bool
    private_username_configured: bool
    private_password_configured: bool
    private_session_path: str


class PolicyStatus(BaseModel):
    """Safe-to-display write-policy status."""

    write_approval_required: bool
    write_confidence_threshold: float
    daily_publish_limit: int
    daily_comment_reply_limit: int
    daily_comment_moderation_limit: int


class ResearchStatus(BaseModel):
    """Safe-to-display adaptive-research status."""

    max_pages: int
    min_pages: int
    confidence_threshold: float
    top_k_links: int
    blocked_domains: tuple[str, ...]
    allowed_domains: tuple[str, ...]


class RuntimeSnapshot(BaseModel):
    """Complete secret-free runtime snapshot for operator surfaces."""

    environment: str
    state_db_path: str
    ai: AIStatus
    instagram: InstagramStatus
    policy: PolicyStatus
    research: ResearchStatus
    supported_actions: tuple[str, ...]


class PlanResult(BaseModel):
    """Reviewed AI decision plus its non-executing pending action."""

    decision: IntelligenceDecision
    planned_action: PlannedAction | None = None


async def _close_resource(resource: Any) -> None:
    closer = getattr(resource, "aclose", None)
    if closer is not None:
        await closer()


class InstabotApplication:
    """Single orchestration surface for CLI and GUI consumers.

    This layer intentionally owns no alternate policy or reasoning logic. It composes
    the canonical intelligence, provider, research, and durable state authorities.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def runtime_snapshot(self) -> RuntimeSnapshot:
        settings = self.settings
        return RuntimeSnapshot(
            environment=settings.environment,
            state_db_path=settings.state_db_path,
            ai=AIStatus(
                provider=settings.ai_provider,
                model=settings.ai_model,
                base_url=settings.ai_base_url,
                api_key_configured=settings.ai_api_key is not None,
                critic_enabled=settings.ai_enable_critic,
                min_decision_score=settings.ai_min_decision_score,
                timeout_seconds=settings.ai_timeout_seconds,
                temperature=settings.ai_temperature,
                max_retries=settings.ai_max_retries,
                max_context_chars=settings.ai_max_context_chars,
            ),
            instagram=InstagramStatus(
                provider=settings.instagram_provider,
                graph_api_version=settings.meta_graph_api_version,
                account_configured=bool(settings.instagram_account_id),
                token_configured=settings.instagram_access_token is not None,
                private_username_configured=bool(settings.private_instagram_username),
                private_password_configured=settings.private_instagram_password is not None,
                private_session_path=settings.private_session_path,
            ),
            policy=PolicyStatus(
                write_approval_required=settings.require_write_approval,
                write_confidence_threshold=settings.write_confidence_threshold,
                daily_publish_limit=settings.daily_publish_limit,
                daily_comment_reply_limit=settings.daily_comment_reply_limit,
                daily_comment_moderation_limit=settings.daily_comment_moderation_limit,
            ),
            research=ResearchStatus(
                max_pages=settings.research_max_pages,
                min_pages=settings.research_min_pages,
                confidence_threshold=settings.research_confidence_threshold,
                top_k_links=settings.research_top_k_links,
                blocked_domains=settings.research_blocked_domains,
                allowed_domains=settings.research_allowed_domains,
            ),
            supported_actions=tuple(action.value for action in ActionType),
        )

    async def ai_check(self) -> IntelligenceProbe:
        model = build_reasoning_model(self.settings)
        try:
            return await probe_reasoning_model(model)
        finally:
            await _close_resource(model)

    async def plan(
        self,
        *,
        objective: str,
        evidence: list[EvidenceItem],
        context: dict[str, Any] | None = None,
    ) -> PlanResult:
        engine = build_intelligence_engine(self.settings)
        try:
            decision, action = await engine.plan_instagram_action(
                objective=objective,
                evidence=evidence,
                context=context or {},
            )
            return PlanResult(decision=decision, planned_action=action)
        finally:
            await engine.aclose()

    def recent_decisions(self, limit: int = 25) -> tuple[IntelligenceDecision, ...]:
        journal = DecisionJournal(self.settings.state_db_path)
        try:
            return journal.recent(limit)
        finally:
            journal.close()

    async def profile(self) -> dict[str, Any]:
        provider = build_instagram_provider(self.settings)
        try:
            result: Any = await provider.get_profile()
            if not isinstance(result, dict):
                raise RuntimeError("Instagram provider returned a non-object profile")
            return {str(key): value for key, value in result.items()}
        finally:
            await _close_resource(provider)

    async def research(self, *, objective: str, seed_urls: list[str]) -> ResearchReport:
        service = AdaptiveResearchService(
            self.settings,
            Crawl4AIFetcher(self.settings),
            ResearchAccessPolicy(self.settings),
        )
        return await service.research(objective, seed_urls)
