from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from instabotai.campaigns import (
    Campaign,
    CampaignMode,
    CampaignRuntime,
    CampaignStatus,
    CampaignStore,
    JobStatus,
)
from instabotai.domain import ActionType, ApprovalState, PlannedAction
from instabotai.intelligence import (
    DecisionCandidate,
    DecisionReview,
    EvidenceItem,
    ExperienceStore,
    IntelligenceDecision,
)
from instabotai.settings import Settings
from instabotai.state import ActionLedger


def settings(path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "state_db_path": str(path),
        "require_write_approval": True,
        "write_confidence_threshold": 0.8,
        "campaign_action_retry_base_seconds": 5,
        "campaign_action_retry_cap_seconds": 30,
        "campaign_plan_retry_base_seconds": 5,
        "campaign_plan_retry_cap_seconds": 30,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="approved-brief",
        source="launch brief",
        content="The image and caption are approved for publication.",
        confidence=1.0,
    )


def action(key: str = "campaign-action-0001") -> PlannedAction:
    return PlannedAction(
        action_type=ActionType.PUBLISH_IMAGE,
        reason="Approved launch creative is ready.",
        confidence=0.95,
        payload={
            "image_url": "https://cdn.example.com/launch.jpg",
            "caption": "Launch day",
        },
        idempotency_key=key,
        approval=ApprovalState.PENDING,
    )


def decision() -> IntelligenceDecision:
    selected = DecisionCandidate(
        candidate_id="candidate-1",
        action=ActionType.PUBLISH_IMAGE.value,
        rationale="Approved launch creative is ready.",
        confidence=0.95,
        expected_utility=0.9,
        risk=0.05,
        payload={
            "image_url": "https://cdn.example.com/launch.jpg",
            "caption": "Launch day",
        },
        evidence_refs=("approved-brief",),
    )
    return IntelligenceDecision(
        decision_id="1234567890abcdef1234567890abcdef",
        objective="Publish the approved launch creative.",
        selected=selected,
        score=0.92,
        review=DecisionReview(
            support_score=0.95,
            risk_score=0.05,
            should_abstain=False,
        ),
        explanation="Candidate passed review.",
        abstained=False,
        provider="test",
        model="test-model",
    )


class FakeEngine:
    async def plan_instagram_action(
        self,
        *,
        objective: str,
        evidence: list[EvidenceItem],
        context: dict[str, Any],
        constraints: tuple[str, ...],
    ) -> tuple[IntelligenceDecision, PlannedAction]:
        assert objective
        assert evidence
        assert context["campaign"]["campaign_id"]
        assert constraints
        return decision(), action()

    async def aclose(self) -> None:
        return None


class FakeProvider:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish_image(self, image_url: str, caption: str = "") -> str:
        self.published.append((image_url, caption))
        return "media-123"

    async def reply_to_comment(
        self,
        comment_id: str,
        message: str,
        *,
        media_id: str | None = None,
    ) -> str:
        raise AssertionError("not expected")

    async def hide_comment(self, comment_id: str, *, hide: bool = True) -> bool:
        raise AssertionError("not expected")

    async def aclose(self) -> None:
        return None


def test_campaign_store_uses_leases_and_blocks_parallel_open_work(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite3"
    store = CampaignStore(str(db))
    campaign = store.create_campaign(
        Campaign(
            name="Launch",
            objective="Publish the approved launch creative.",
            evidence=(evidence(),),
        )
    )
    active = store.set_campaign_status(campaign.campaign_id, CampaignStatus.ACTIVE)
    now = datetime.now(UTC)
    claimed = store.claim_due_campaign(lease_seconds=60, now=now)
    assert claimed is not None
    claimed_campaign, token = claimed
    assert claimed_campaign.campaign_id == active.campaign_id

    store.complete_campaign_cycle(
        campaign.campaign_id,
        token,
        next_run_at=now + timedelta(hours=1),
        now=now,
    )
    job = store.enqueue_job(
        campaign=store.get_campaign(campaign.campaign_id),
        decision_id=decision().decision_id,
        action=action(),
        settings=settings(db),
        scheduled_for=now,
    )
    assert job.status is JobStatus.PENDING_APPROVAL
    assert store.claim_due_campaign(lease_seconds=60, now=now + timedelta(hours=2)) is None


def test_campaign_job_approval_and_stale_lease_recovery(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite3"
    config = settings(db)
    store = CampaignStore(str(db))
    campaign = store.create_campaign(
        Campaign(
            name="Launch",
            objective="Publish the approved launch creative.",
            mode=CampaignMode.SUPERVISED,
            evidence=(evidence(),),
        )
    )
    store.set_campaign_status(campaign.campaign_id, CampaignStatus.ACTIVE)
    job = store.enqueue_job(
        campaign=store.get_campaign(campaign.campaign_id),
        decision_id=decision().decision_id,
        action=action(),
        settings=config,
        scheduled_for=datetime.now(UTC),
    )
    approved = store.approve_job(job.job_id)
    assert approved.status is JobStatus.SCHEDULED
    assert approved.action.approval is ApprovalState.APPROVED

    now = datetime.now(UTC)
    leased = store.claim_job(job.job_id, lease_seconds=30, now=now)
    leased_job, first_token = leased
    assert leased_job.status is JobStatus.LEASED
    assert leased_job.attempt_count == 1

    recovered = store.claim_job(
        job.job_id,
        lease_seconds=30,
        now=now + timedelta(seconds=31),
    )
    recovered_job, second_token = recovered
    assert second_token != first_token
    assert recovered_job.attempt_count == 2


def test_failed_action_ledger_reservation_can_retry_same_action_only(tmp_path: Path) -> None:
    ledger = ActionLedger(str(tmp_path / "state.sqlite3"))
    approved = action().model_copy(update={"approval": ApprovalState.APPROVED})
    ledger.reserve(approved, daily_limit=4)
    ledger.mark_failed(approved.idempotency_key, "temporary upstream failure")
    assert ledger.status(approved.idempotency_key) == "failed"

    ledger.reserve(approved, daily_limit=4)
    assert ledger.status(approved.idempotency_key) == "reserved"


async def test_campaign_runtime_plans_approves_executes_and_learns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "state.sqlite3"
    config = settings(db)
    provider = FakeProvider()

    monkeypatch.setattr(
        "instabotai.campaigns.runtime.build_intelligence_engine",
        lambda _: FakeEngine(),
    )
    monkeypatch.setattr(
        "instabotai.campaigns.runtime.build_instagram_provider",
        lambda _: provider,
    )

    runtime = CampaignRuntime(config)
    campaign = runtime.create_campaign(
        name="Launch",
        objective="Publish the approved launch creative.",
        evidence=[evidence()],
    )
    runtime.activate_campaign(campaign.campaign_id)

    planned = await runtime.plan_campaign_now(campaign.campaign_id)
    assert planned.decision.abstained is False
    assert planned.job is not None
    assert planned.job.status is JobStatus.PENDING_APPROVAL

    approved = runtime.approve_job(planned.job.job_id)
    assert approved.status is JobStatus.SCHEDULED
    executed = await runtime.execute_job(planned.job.job_id)
    assert executed.status is JobStatus.SUCCEEDED
    assert executed.provider_result == "media-123"
    assert provider.published == [
        ("https://cdn.example.com/launch.jpg", "Launch day")
    ]

    learned = runtime.record_outcome(
        executed.job_id,
        reward=0.9,
        note="Strong conversion response after the campaign post.",
    )
    assert learned.outcome_reward == 0.9

    memory = ExperienceStore(str(db))
    try:
        summary = memory.summarize(
            objective=campaign.objective,
            action=ActionType.PUBLISH_IMAGE.value,
        )
    finally:
        memory.close()
    assert summary.samples == 1
    assert summary.mean_reward == pytest.approx(0.9)


def test_experience_source_key_is_idempotent(tmp_path: Path) -> None:
    store = ExperienceStore(str(tmp_path / "state.sqlite3"))
    try:
        for _ in range(2):
            store.record(
                objective="Launch",
                action=ActionType.PUBLISH_IMAGE.value,
                reward=0.8,
                source_key="campaign-job:abc",
            )
        summary = store.summarize(
            objective="Launch",
            action=ActionType.PUBLISH_IMAGE.value,
        )
    finally:
        store.close()
    assert summary.samples == 1
