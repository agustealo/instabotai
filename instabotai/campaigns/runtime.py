"""Campaign orchestration over the canonical intelligence and execution authorities."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from instabotai.automation import AutomationService
from instabotai.campaigns.domain import (
    Campaign,
    CampaignJob,
    CampaignMode,
    CampaignPlanOutcome,
    CampaignStatus,
    JobStatus,
    WorkerTick,
)
from instabotai.campaigns.store import CampaignStore
from instabotai.domain import ResearchReport
from instabotai.intelligence import EvidenceItem, ExperienceStore, build_intelligence_engine
from instabotai.policy import AutomationPolicy
from instabotai.providers import build_instagram_provider
from instabotai.research import AdaptiveResearchService, Crawl4AIFetcher, ResearchAccessPolicy
from instabotai.settings import Settings
from instabotai.state import ActionLedger


async def _close_resource(resource: Any) -> None:
    closer = getattr(resource, "aclose", None)
    if closer is not None:
        await closer()


class CampaignRuntime:
    """Durable planner/approval/scheduler worker for campaign automation."""

    def __init__(
        self,
        settings: Settings,
        store: CampaignStore | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or CampaignStore(settings.state_db_path)
        self._owns_store = store is None

    def create_campaign(
        self,
        *,
        name: str,
        objective: str,
        mode: CampaignMode = CampaignMode.SUPERVISED,
        cadence_minutes: int = 1440,
        action_delay_minutes: int = 0,
        evidence: list[EvidenceItem] | None = None,
        context: dict[str, Any] | None = None,
        research_seed_urls: list[str] | None = None,
        research_before_plan: bool = False,
    ) -> Campaign:
        campaign = Campaign(
            name=name.strip(),
            objective=objective.strip(),
            mode=mode,
            cadence_minutes=cadence_minutes,
            action_delay_minutes=action_delay_minutes,
            evidence=tuple(evidence or ()),
            context=context or {},
            research_seed_urls=tuple(
                url.strip() for url in (research_seed_urls or ()) if url.strip()
            ),
            research_before_plan=research_before_plan,
        )
        return self.store.create_campaign(campaign)

    def list_campaigns(self, limit: int = 100) -> tuple[Campaign, ...]:
        return self.store.list_campaigns(limit)

    def get_campaign(self, campaign_id: str) -> Campaign:
        return self.store.get_campaign(campaign_id)

    def activate_campaign(self, campaign_id: str) -> Campaign:
        return self.store.set_campaign_status(campaign_id, CampaignStatus.ACTIVE)

    def pause_campaign(self, campaign_id: str) -> Campaign:
        return self.store.set_campaign_status(campaign_id, CampaignStatus.PAUSED)

    def archive_campaign(self, campaign_id: str) -> Campaign:
        return self.store.set_campaign_status(campaign_id, CampaignStatus.ARCHIVED)

    def list_jobs(
        self,
        *,
        campaign_id: str | None = None,
        limit: int = 100,
    ) -> tuple[CampaignJob, ...]:
        return self.store.list_jobs(campaign_id=campaign_id, limit=limit)

    def approve_job(self, job_id: str) -> CampaignJob:
        return self.store.approve_job(job_id)

    def reject_job(self, job_id: str) -> CampaignJob:
        return self.store.reject_job(job_id)

    def cancel_job(self, job_id: str) -> CampaignJob:
        return self.store.cancel_job(job_id)

    async def plan_campaign_now(self, campaign_id: str) -> CampaignPlanOutcome:
        campaign, token = self.store.claim_campaign(
            campaign_id,
            lease_seconds=self.settings.campaign_plan_lease_seconds,
        )
        return await self._plan_claimed(campaign, token)

    async def plan_next_due(self) -> CampaignPlanOutcome | None:
        claimed = self.store.claim_due_campaign(
            lease_seconds=self.settings.campaign_plan_lease_seconds,
        )
        if claimed is None:
            return None
        campaign, token = claimed
        return await self._plan_claimed(campaign, token)

    async def execute_job(self, job_id: str) -> CampaignJob:
        job, token = self.store.claim_job(
            job_id,
            lease_seconds=self.settings.campaign_action_lease_seconds,
        )
        return await self._execute_claimed(job, token)

    async def execute_next_due(self) -> CampaignJob | None:
        claimed = self.store.claim_next_job(
            lease_seconds=self.settings.campaign_action_lease_seconds,
        )
        if claimed is None:
            return None
        job, token = claimed
        return await self._execute_claimed(job, token)

    def record_outcome(self, job_id: str, *, reward: float, note: str = "") -> CampaignJob:
        job = self.store.get_job(job_id)
        if job.status is not JobStatus.SUCCEEDED:
            raise RuntimeError("business outcome can only be recorded after successful execution")
        campaign = self.store.get_campaign(job.campaign_id)

        experience = ExperienceStore(self.settings.state_db_path)
        try:
            experience.record(
                objective=campaign.objective,
                action=job.action.action_type.value,
                reward=reward,
                note=note,
                metadata={
                    "campaign_id": campaign.campaign_id,
                    "job_id": job.job_id,
                    "decision_id": job.decision_id,
                },
                source_key=f"campaign-job:{job.job_id}",
            )
        finally:
            experience.close()
        return self.store.record_outcome(job_id, reward=reward, note=note)

    async def worker_tick(self) -> WorkerTick:
        tick = WorkerTick()
        try:
            planned = await self.plan_next_due()
            if planned is not None:
                tick.planned_campaign_id = planned.campaign.campaign_id
                tick.planned_decision_id = planned.decision.decision_id
                tick.created_job_id = planned.job.job_id if planned.job is not None else None
        except Exception as exc:
            tick.planning_error = str(exc)

        try:
            executed = await self.execute_next_due()
            if executed is not None:
                tick.executed_job_id = executed.job_id
                tick.execution_status = executed.status
        except Exception as exc:
            tick.execution_error = str(exc)
        return tick

    async def _plan_claimed(
        self,
        campaign: Campaign,
        claim_token: str,
    ) -> CampaignPlanOutcome:
        now = datetime.now(UTC)
        research_confidence: float | None = None
        try:
            evidence = list(campaign.evidence)
            context = dict(campaign.context)
            context["campaign"] = {
                "campaign_id": campaign.campaign_id,
                "name": campaign.name,
                "mode": campaign.mode.value,
                "cadence_minutes": campaign.cadence_minutes,
            }

            if campaign.research_before_plan:
                report = await self._research(campaign)
                research_confidence = report.confidence
                context["research"] = {
                    "confidence": report.confidence,
                    "stopped_early": report.stopped_early,
                    "blocked_urls": report.blocked_urls,
                    "failed_urls": report.failed_urls,
                }
                for page in report.pages:
                    digest = hashlib.sha256(page.url.encode("utf-8")).hexdigest()[:12]
                    evidence.append(
                        EvidenceItem(
                            evidence_id=f"research-{digest}",
                            source=page.url,
                            content=page.markdown[:12_000],
                            confidence=page.relevance,
                        )
                    )

            if not evidence:
                raise RuntimeError("campaign planning has no usable evidence")

            engine = build_intelligence_engine(self.settings)
            try:
                decision, action = await engine.plan_instagram_action(
                    objective=campaign.objective,
                    evidence=evidence,
                    context=context,
                    constraints=(
                        "Campaign actions must remain within configured write policy.",
                        "Do not create work unsupported by the supplied campaign evidence.",
                    ),
                )
            finally:
                await engine.aclose()

            job: CampaignJob | None = None
            if action is not None:
                job = self.store.enqueue_job(
                    campaign=campaign,
                    decision_id=decision.decision_id,
                    action=action,
                    settings=self.settings,
                    scheduled_for=now + timedelta(minutes=campaign.action_delay_minutes),
                )

            completed = self.store.complete_campaign_cycle(
                campaign.campaign_id,
                claim_token,
                next_run_at=now + timedelta(minutes=campaign.cadence_minutes),
                now=now,
            )
            return CampaignPlanOutcome(
                campaign=completed,
                decision=decision,
                job=job,
                research_confidence=research_confidence,
            )
        except Exception:
            exponent = min(campaign.consecutive_failures, 8)
            delay = min(
                self.settings.campaign_plan_retry_cap_seconds,
                self.settings.campaign_plan_retry_base_seconds * (2**exponent),
            )
            self.store.fail_campaign_cycle(
                campaign.campaign_id,
                claim_token,
                retry_at=now + timedelta(seconds=delay),
                now=now,
            )
            raise

    async def _research(self, campaign: Campaign) -> ResearchReport:
        service = AdaptiveResearchService(
            self.settings,
            Crawl4AIFetcher(self.settings),
            ResearchAccessPolicy(self.settings),
        )
        return await service.research(campaign.objective, list(campaign.research_seed_urls))

    async def _execute_claimed(self, job: CampaignJob, lease_token: str) -> CampaignJob:
        provider = build_instagram_provider(self.settings)
        ledger = ActionLedger(self.settings.state_db_path)
        try:
            service = AutomationService(
                AutomationPolicy(self.settings),
                ledger,
                provider,
            )
            result = await service.execute(job.action)
        except Exception as exc:
            self.store.mark_job_execution_failed(
                job.job_id,
                lease_token,
                str(exc),
                retry_base_seconds=self.settings.campaign_action_retry_base_seconds,
                retry_cap_seconds=self.settings.campaign_action_retry_cap_seconds,
            )
            raise
        else:
            return self.store.mark_job_succeeded(job.job_id, lease_token, result)
        finally:
            ledger.close()
            await _close_resource(provider)

    def close(self) -> None:
        if self._owns_store:
            self.store.close()
