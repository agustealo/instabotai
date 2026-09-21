"""Canonical application service shared by CLI and consumer UI surfaces."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from instabotai.campaigns import (
    Campaign,
    CampaignJob,
    CampaignMode,
    CampaignPlanOutcome,
    CampaignRuntime,
    WorkerTick,
)
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
from instabotai.storage import StateSchemaReport, inspect_state_database, upgrade_state_database


class AIStatus(BaseModel):
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
    provider: str
    graph_api_version: str
    account_configured: bool
    token_configured: bool
    private_username_configured: bool
    private_password_configured: bool
    private_session_path: str


class PolicyStatus(BaseModel):
    write_approval_required: bool
    write_confidence_threshold: float
    daily_publish_limit: int
    daily_comment_reply_limit: int
    daily_comment_moderation_limit: int


class ResearchStatus(BaseModel):
    max_pages: int
    min_pages: int
    confidence_threshold: float
    top_k_links: int
    blocked_domains: tuple[str, ...]
    allowed_domains: tuple[str, ...]


class SchedulerStatus(BaseModel):
    worker_poll_seconds: float
    plan_lease_seconds: int
    action_lease_seconds: int
    action_max_attempts: int
    action_retry_base_seconds: int
    action_retry_cap_seconds: int


class RuntimeSnapshot(BaseModel):
    environment: str
    state_db_path: str
    state_schema_version: int
    state_schema_target: int
    ai: AIStatus
    instagram: InstagramStatus
    policy: PolicyStatus
    research: ResearchStatus
    scheduler: SchedulerStatus
    supported_actions: tuple[str, ...]


class PlanResult(BaseModel):
    decision: IntelligenceDecision
    planned_action: PlannedAction | None = None


async def _close_resource(resource: Any) -> None:
    closer = getattr(resource, "aclose", None)
    if closer is not None:
        await closer()


class InstabotApplication:
    """Single orchestration surface for CLI, GUI, and worker consumers."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state_schema = self._prepare_state_schema(settings.state_db_path)

    @staticmethod
    def _prepare_state_schema(database_path: str) -> StateSchemaReport:
        if database_path == ":memory:":
            return inspect_state_database(database_path)
        return upgrade_state_database(database_path)

    def runtime_snapshot(self) -> RuntimeSnapshot:
        settings = self.settings
        return RuntimeSnapshot(
            environment=settings.environment,
            state_db_path=settings.state_db_path,
            state_schema_version=self.state_schema.schema_version,
            state_schema_target=self.state_schema.target_version,
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
            scheduler=SchedulerStatus(
                worker_poll_seconds=settings.campaign_worker_poll_seconds,
                plan_lease_seconds=settings.campaign_plan_lease_seconds,
                action_lease_seconds=settings.campaign_action_lease_seconds,
                action_max_attempts=settings.campaign_action_max_attempts,
                action_retry_base_seconds=settings.campaign_action_retry_base_seconds,
                action_retry_cap_seconds=settings.campaign_action_retry_cap_seconds,
            ),
            supported_actions=tuple(action.value for action in ActionType),
        )

    def doctor_payload(self) -> dict[str, Any]:
        snapshot = self.runtime_snapshot()
        return {
            "environment": snapshot.environment,
            "ai_provider": snapshot.ai.provider,
            "ai_model": snapshot.ai.model,
            "ai_base_url": snapshot.ai.base_url,
            "ai_api_key_configured": snapshot.ai.api_key_configured,
            "ai_critic_enabled": snapshot.ai.critic_enabled,
            "ai_min_decision_score": snapshot.ai.min_decision_score,
            "instagram_provider": snapshot.instagram.provider,
            "graph_api_version": snapshot.instagram.graph_api_version,
            "instagram_account_configured": snapshot.instagram.account_configured,
            "instagram_token_configured": snapshot.instagram.token_configured,
            "private_username_configured": snapshot.instagram.private_username_configured,
            "private_password_configured": snapshot.instagram.private_password_configured,
            "write_approval_required": snapshot.policy.write_approval_required,
            "research_max_pages": snapshot.research.max_pages,
            "state_db_path": snapshot.state_db_path,
            "state_schema_version": snapshot.state_schema_version,
            "state_schema_target": snapshot.state_schema_target,
            "state_schema_backup_created": self.state_schema.backup_path is not None,
        }

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

    def create_campaign(
        self,
        *,
        name: str,
        objective: str,
        mode: CampaignMode,
        cadence_minutes: int,
        action_delay_minutes: int,
        evidence: list[EvidenceItem],
        context: dict[str, Any],
        research_seed_urls: list[str],
        research_before_plan: bool,
    ) -> Campaign:
        runtime = CampaignRuntime(self.settings)
        try:
            return runtime.create_campaign(
                name=name,
                objective=objective,
                mode=mode,
                cadence_minutes=cadence_minutes,
                action_delay_minutes=action_delay_minutes,
                evidence=evidence,
                context=context,
                research_seed_urls=research_seed_urls,
                research_before_plan=research_before_plan,
            )
        finally:
            runtime.close()

    def list_campaigns(self, limit: int = 100) -> tuple[Campaign, ...]:
        runtime = CampaignRuntime(self.settings)
        try:
            return runtime.list_campaigns(limit)
        finally:
            runtime.close()

    def activate_campaign(self, campaign_id: str) -> Campaign:
        runtime = CampaignRuntime(self.settings)
        try:
            return runtime.activate_campaign(campaign_id)
        finally:
            runtime.close()

    def pause_campaign(self, campaign_id: str) -> Campaign:
        runtime = CampaignRuntime(self.settings)
        try:
            return runtime.pause_campaign(campaign_id)
        finally:
            runtime.close()

    def archive_campaign(self, campaign_id: str) -> Campaign:
        runtime = CampaignRuntime(self.settings)
        try:
            return runtime.archive_campaign(campaign_id)
        finally:
            runtime.close()

    async def plan_campaign_now(self, campaign_id: str) -> CampaignPlanOutcome:
        runtime = CampaignRuntime(self.settings)
        try:
            return await runtime.plan_campaign_now(campaign_id)
        finally:
            runtime.close()

    def list_campaign_jobs(
        self,
        *,
        campaign_id: str | None = None,
        limit: int = 100,
    ) -> tuple[CampaignJob, ...]:
        runtime = CampaignRuntime(self.settings)
        try:
            return runtime.list_jobs(campaign_id=campaign_id, limit=limit)
        finally:
            runtime.close()

    def approve_campaign_job(self, job_id: str) -> CampaignJob:
        runtime = CampaignRuntime(self.settings)
        try:
            return runtime.approve_job(job_id)
        finally:
            runtime.close()

    def reject_campaign_job(self, job_id: str) -> CampaignJob:
        runtime = CampaignRuntime(self.settings)
        try:
            return runtime.reject_job(job_id)
        finally:
            runtime.close()

    def cancel_campaign_job(self, job_id: str) -> CampaignJob:
        runtime = CampaignRuntime(self.settings)
        try:
            return runtime.cancel_job(job_id)
        finally:
            runtime.close()

    async def execute_campaign_job(self, job_id: str) -> CampaignJob:
        runtime = CampaignRuntime(self.settings)
        try:
            return await runtime.execute_job(job_id)
        finally:
            runtime.close()

    def record_campaign_outcome(
        self,
        job_id: str,
        *,
        reward: float,
        note: str = "",
    ) -> CampaignJob:
        runtime = CampaignRuntime(self.settings)
        try:
            return runtime.record_outcome(job_id, reward=reward, note=note)
        finally:
            runtime.close()

    async def worker_tick(self) -> WorkerTick:
        runtime = CampaignRuntime(self.settings)
        try:
            return await runtime.worker_tick()
        finally:
            runtime.close()
