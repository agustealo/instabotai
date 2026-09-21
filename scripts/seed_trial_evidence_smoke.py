"""Seed deterministic durable state for package/container evidence smoke tests."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from instabotai.campaigns import Campaign, CampaignMode, CampaignStatus, CampaignStore
from instabotai.domain import ActionType, PlannedAction
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


def seed(database: Path, job_id_file: Path) -> str:
    """Create one completed supervised trial using only canonical durable authorities."""

    database = database.expanduser().resolve()
    job_id_file = job_id_file.expanduser().resolve()
    settings = Settings(
        _env_file=None,
        state_db_path=str(database),
        instagram_account_id="ci-account",
        instagram_access_token="ci-readiness-token",
        require_write_approval=True,
        ui_open_browser=False,
    )
    upgrade_state_database(settings.state_db_path)
    moment = datetime.now(UTC)

    evidence = EvidenceItem(
        evidence_id="ci-approved-brief",
        source="quality-gate",
        content="Deterministic package evidence smoke record.",
        confidence=1.0,
    )
    candidate = DecisionCandidate(
        candidate_id="ci-publish",
        action=ActionType.PUBLISH_IMAGE.value,
        rationale="Exercise the durable supervised evidence path.",
        confidence=0.95,
        expected_utility=0.8,
        risk=0.05,
        payload={
            "image_url": "https://example.invalid/ci-evidence.jpg",
            "caption": "Quality gate evidence smoke",
            "access_token": "ci-evidence-secret",
        },
        evidence_refs=(evidence.evidence_id,),
    )
    decision = IntelligenceDecision(
        objective="Prove packaged consumer-trial evidence export",
        selected=candidate,
        score=0.9,
        review=DecisionReview(
            support_score=0.95,
            risk_score=0.05,
            should_abstain=False,
        ),
        explanation="Deterministic CI decision exercising the durable evidence projection.",
        abstained=False,
        provider="quality-gate",
        model="deterministic-ci",
        created_at=moment,
    )

    journal = DecisionJournal(settings.state_db_path)
    try:
        journal.record(decision)
    finally:
        journal.close()

    store = CampaignStore(settings.state_db_path)
    try:
        campaign = store.create_campaign(
            Campaign(
                name="Package evidence smoke",
                objective=decision.objective,
                mode=CampaignMode.SUPERVISED,
                evidence=(evidence,),
                context={"authorization": "Bearer ci-evidence-secret"},
                created_at=moment,
                updated_at=moment,
            )
        )
        job = store.enqueue_job(
            campaign=campaign,
            decision_id=decision.decision_id,
            action=PlannedAction(
                action_type=ActionType.PUBLISH_IMAGE,
                reason="Deterministic quality-gate evidence action",
                confidence=0.95,
                payload={
                    "image_url": "https://example.invalid/ci-evidence.jpg",
                    "caption": "Quality gate evidence smoke",
                    "api_key": "ci-evidence-secret",
                },
                idempotency_key=f"ci-evidence-{decision.decision_id}",
                created_at=moment,
            ),
            settings=settings,
            scheduled_for=moment,
        )
        approved = store.approve_job(job.job_id, now=moment)
        store.set_campaign_status(campaign.campaign_id, CampaignStatus.ACTIVE, now=moment)

        ledger = ActionLedger(settings.state_db_path)
        try:
            ledger.reserve(approved.action, daily_limit=settings.daily_publish_limit)
            ledger.mark_succeeded(
                approved.action.idempotency_key,
                {
                    "media_id": "ci-media-id",
                    "token": "ci-evidence-secret",
                },
            )
        finally:
            ledger.close()

        leased, lease_token = store.claim_job(
            approved.job_id,
            lease_seconds=settings.campaign_action_lease_seconds,
            now=moment,
        )
        if leased.job_id != approved.job_id:
            raise RuntimeError("quality-gate evidence seed leased the wrong job")
        store.mark_job_succeeded(
            approved.job_id,
            lease_token,
            {"media_id": "ci-media-id", "secret": "ci-evidence-secret"},
            now=moment,
        )
        store.record_outcome(
            approved.job_id,
            reward=0.75,
            note="Deterministic CI outcome for package evidence verification.",
            now=moment,
        )
    finally:
        store.close()

    job_id_file.parent.mkdir(parents=True, exist_ok=True)
    job_id_file.write_text(f"{approved.job_id}\n", encoding="utf-8")
    return approved.job_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--job-id-file", type=Path, required=True)
    args = parser.parse_args()
    print(seed(args.database, args.job_id_file))


if __name__ == "__main__":
    main()
