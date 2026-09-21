from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from instabotai.campaigns import Campaign, CampaignMode, CampaignStatus, CampaignStore
from instabotai.domain import ActionType, PlannedAction
from instabotai.evidence import (
    TrialEvidenceService,
    load_evidence_bundle,
    verify_evidence_bundle,
    write_evidence_bundle,
)
from instabotai.intelligence import (
    DecisionCandidate,
    DecisionJournal,
    DecisionReview,
    EvidenceItem,
    IntelligenceDecision,
)
from instabotai.settings import Settings
from instabotai.state import ActionLedger
from instabotai.storage import upgrade_state_database


def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        state_db_path=str(tmp_path / "state.sqlite3"),
        instagram_access_token="instagram-super-secret",
        instagram_account_id="account-123",
        ai_api_key="ai-super-secret",
        require_write_approval=True,
        ui_open_browser=False,
    )


def seed_trial_state(active: Settings) -> str:
    upgrade_state_database(active.state_db_path)
    execution_time = datetime.now(UTC)
    evidence = EvidenceItem(
        evidence_id="approved-brief",
        source="operator",
        content="Approved launch brief. ai-super-secret must never escape.",
        confidence=0.98,
    )
    candidate = DecisionCandidate(
        candidate_id="publish-1",
        action=ActionType.PUBLISH_IMAGE.value,
        rationale="Publish the approved launch asset.",
        confidence=0.94,
        expected_utility=0.9,
        risk=0.08,
        payload={
            "image_url": "https://cdn.example.test/launch.jpg",
            "caption": "Launch day",
            "password": "payload-password",
        },
        evidence_refs=(evidence.evidence_id,),
    )
    decision = IntelligenceDecision(
        objective="Publish the approved launch announcement",
        selected=candidate,
        score=0.91,
        review=DecisionReview(
            support_score=0.95,
            risk_score=0.08,
            should_abstain=False,
        ),
        explanation="Evidence and policy support one supervised publish action.",
        abstained=False,
        provider="scripted-test",
        model="decision-test",
    )
    journal = DecisionJournal(active.state_db_path)
    journal.record(decision)
    journal.close()

    store = CampaignStore(active.state_db_path)
    campaign = store.create_campaign(
        Campaign(
            name="Launch evidence trial",
            objective=decision.objective,
            mode=CampaignMode.SUPERVISED,
            evidence=(evidence,),
            context={
                "audience": "approved customers",
                "authorization": "Bearer context-secret",
            },
        )
    )
    action = PlannedAction(
        action_type=ActionType.PUBLISH_IMAGE,
        reason="Approved launch plan",
        confidence=0.94,
        payload={
            "image_url": "https://cdn.example.test/launch.jpg",
            "caption": "Launch day instagram-super-secret",
            "access_token": "payload-token",
        },
        idempotency_key="trial-evidence-publish-001",
    )
    job = store.enqueue_job(
        campaign=campaign,
        decision_id=decision.decision_id,
        action=action,
        settings=active,
        scheduled_for=execution_time,
    )
    approved = store.approve_job(job.job_id, now=execution_time)
    store.set_campaign_status(
        campaign.campaign_id,
        CampaignStatus.ACTIVE,
        now=execution_time,
    )

    ledger = ActionLedger(active.state_db_path)
    ledger.reserve(approved.action, daily_limit=active.daily_publish_limit)
    ledger.mark_succeeded(
        approved.action.idempotency_key,
        {
            "media_id": "media-123",
            "token": "provider-token",
            "detail": "Bearer upstream-secret",
        },
    )
    ledger.close()

    leased, lease_token = store.claim_job(
        approved.job_id,
        lease_seconds=active.campaign_action_lease_seconds,
        now=execution_time,
    )
    assert leased.job_id == approved.job_id
    store.mark_job_succeeded(
        approved.job_id,
        lease_token,
        {
            "media_id": "media-123",
            "api_key": "provider-api-key",
        },
        now=execution_time,
    )
    store.record_outcome(
        approved.job_id,
        reward=0.82,
        note="Measured conversion lift without storing credentials.",
        now=execution_time,
    )
    store.close()
    return approved.job_id


async def test_bundle_connects_trial_authorities_and_redacts_secrets(tmp_path: Path) -> None:
    active = settings(tmp_path)
    job_id = seed_trial_state(active)

    bundle = await TrialEvidenceService(active).build(job_id)
    serialized = bundle.model_dump_json()

    assert bundle.job_id == job_id
    assert bundle.readiness.ready
    assert bundle.runtime.app_version
    assert len(bundle.runtime.package_sha256) == 64
    assert bundle.campaign["name"] == "Launch evidence trial"
    assert bundle.job["status"] == "succeeded"
    assert bundle.job["outcome_reward"] == 0.82
    assert bundle.decision["decision_id"] == bundle.job["decision_id"]
    assert bundle.action_ledger is not None
    assert bundle.action_ledger["status"] == "succeeded"
    assert bundle.action_ledger["idempotency_key"] == "trial-evidence-publish-001"
    assert bundle.integrity.algorithm == "sha256"
    assert bundle.integrity.signed is False
    assert verify_evidence_bundle(bundle).valid

    for secret in (
        "instagram-super-secret",
        "ai-super-secret",
        "context-secret",
        "payload-token",
        "payload-password",
        "provider-token",
        "provider-api-key",
        "upstream-secret",
    ):
        assert secret not in serialized
    assert "[redacted]" in serialized


async def test_digest_detects_bundle_tampering(tmp_path: Path) -> None:
    active = settings(tmp_path)
    job_id = seed_trial_state(active)
    bundle = await TrialEvidenceService(active).build(job_id)

    tampered = bundle.model_copy(
        update={
            "campaign": {
                **bundle.campaign,
                "objective": "tampered objective",
            }
        }
    )

    verification = verify_evidence_bundle(tampered)
    assert not verification.valid
    assert verification.actual_digest != verification.expected_digest


async def test_bundle_round_trip_and_private_file_permissions(tmp_path: Path) -> None:
    active = settings(tmp_path)
    job_id = seed_trial_state(active)
    bundle = await TrialEvidenceService(active).build(job_id)
    output = tmp_path / "exports" / "trial-evidence.json"

    written = write_evidence_bundle(bundle, output)
    loaded = load_evidence_bundle(written)

    assert written == output.resolve()
    assert verify_evidence_bundle(loaded).valid
    assert loaded.integrity.digest == bundle.integrity.digest
    if os.name == "posix":
        assert written.stat().st_mode & 0o777 == 0o600


async def test_bundle_fails_when_job_is_missing(tmp_path: Path) -> None:
    active = settings(tmp_path)
    upgrade_state_database(active.state_db_path)

    try:
        await TrialEvidenceService(active).build("missing-job")
    except RuntimeError as exc:
        assert "missing-job" in str(exc)
    else:
        raise AssertionError("missing job must not produce a trial evidence bundle")
