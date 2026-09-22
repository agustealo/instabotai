from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

import instabotai.evidence as evidence_module
from instabotai.campaigns import Campaign, CampaignMode, CampaignStatus, CampaignStore
from instabotai.domain import ActionType, PlannedAction
from instabotai.evidence import (
    EvidenceIntegrity,
    TrialEvidenceBundle,
    TrialEvidenceError,
    TrialEvidenceReadiness,
    TrialEvidenceReadinessCheck,
    TrialEvidenceRuntime,
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

ROOT = Path(__file__).resolve().parents[1]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        state_db_path=str(tmp_path / "state.sqlite3"),
        instagram_access_token="instagram-secret",
        instagram_account_id="account-123",
        ai_api_key="ai-secret",
        require_write_approval=True,
        ui_open_browser=False,
    )


def _seed_reserved_trial(active: Settings) -> tuple[str, str]:
    upgrade_state_database(active.state_db_path)
    now = datetime.now(UTC)
    evidence = EvidenceItem(
        evidence_id="brief",
        source="operator",
        content="Approved brief.",
        confidence=0.99,
    )
    candidate = DecisionCandidate(
        candidate_id="candidate",
        action=ActionType.PUBLISH_IMAGE.value,
        rationale="Approved publish.",
        confidence=0.95,
        expected_utility=0.9,
        risk=0.05,
        payload={"image_url": "https://cdn.example.test/image.jpg", "caption": "Hello"},
        evidence_refs=(evidence.evidence_id,),
    )
    decision = IntelligenceDecision(
        objective="Publish one approved image",
        selected=candidate,
        score=0.9,
        review=DecisionReview(
            support_score=0.95,
            risk_score=0.05,
            should_abstain=False,
        ),
        explanation="Approved evidence supports the action.",
        abstained=False,
        provider="test",
        model="test",
    )
    journal = DecisionJournal(active.state_db_path)
    journal.record(decision)
    journal.close()

    store = CampaignStore(active.state_db_path)
    campaign = store.create_campaign(
        Campaign(
            name="Snapshot trial",
            objective=decision.objective,
            mode=CampaignMode.SUPERVISED,
            evidence=(evidence,),
        )
    )
    action = PlannedAction(
        action_type=ActionType.PUBLISH_IMAGE,
        reason="Approved publish.",
        confidence=0.95,
        payload={"image_url": "https://cdn.example.test/image.jpg", "caption": "Hello"},
        idempotency_key="snapshot-proof-001",
    )
    job = store.enqueue_job(
        campaign=campaign,
        decision_id=decision.decision_id,
        action=action,
        settings=active,
        scheduled_for=now,
    )
    approved = store.approve_job(job.job_id, now=now)
    store.set_campaign_status(campaign.campaign_id, CampaignStatus.ACTIVE, now=now)
    store.close()

    ledger = ActionLedger(active.state_db_path)
    ledger.reserve(approved.action, daily_limit=active.daily_publish_limit)
    ledger.close()
    return approved.job_id, approved.action.idempotency_key


def _minimal_bundle(format_version: Literal[1, 2] = 2) -> TrialEvidenceBundle:
    readiness = TrialEvidenceReadiness(
        version="2.0.0a1",
        environment="test",
        generated_at=datetime(2026, 9, 22, tzinfo=UTC),
        live_probes=False,
        research_required=False,
        ready=True,
        checks=(
            TrialEvidenceReadinessCheck(
                key="runtime",
                label="Runtime",
                status="pass",
                detail="ready",
            ),
        ),
        blockers=(),
        warnings=(),
    )
    runtime = TrialEvidenceRuntime(
        app_version="2.0.0a1",
        package_sha256="0" * 64,
        environment="test",
        state_schema_version=3,
        state_schema_target=3,
        state_integrity="ok",
        ai_provider="ollama",
        ai_model="test",
        instagram_provider="official",
        graph_api_version="v23.0",
        write_approval_required=True,
        write_confidence_threshold=0.8,
        daily_publish_limit=1,
        daily_comment_reply_limit=1,
        daily_comment_moderation_limit=1,
    )
    content = {
        "format_version": format_version,
        "bundle_id": "a" * 32,
        "generated_at": datetime(2026, 9, 22, tzinfo=UTC),
        "job_id": "job-1",
        "runtime": runtime,
        "readiness": readiness,
        "campaign": {},
        "job": {},
        "decision": {},
        "action_ledger": None,
        "usage_snapshot": {},
    }
    metadata = {"algorithm": "sha256", "signed": False}
    digest_input = content if format_version == 1 else {**content, "integrity": metadata}
    digest = evidence_module._content_digest(digest_input)
    return TrialEvidenceBundle(
        **content,
        integrity=EvidenceIntegrity(digest=digest),
    )


def test_evidence_redaction_covers_camel_case_credentials(tmp_path: Path) -> None:
    service = TrialEvidenceService(_settings(tmp_path))
    sanitized = service._sanitize(
        {
            "accessToken": "access-value",
            "refreshToken": "refresh-value",
            "apiKey": "api-value",
            "clientSecret": "client-value",
            "nested": {"sessionCookie": "cookie-value"},
        }
    )

    assert sanitized == {
        "accessToken": "[redacted]",
        "refreshToken": "[redacted]",
        "apiKey": "[redacted]",
        "clientSecret": "[redacted]",
        "nested": {"sessionCookie": "[redacted]"},
    }


def test_evidence_document_rejects_unknown_fields_and_signed_claims(tmp_path: Path) -> None:
    bundle = _minimal_bundle()
    path = write_evidence_bundle(bundle, tmp_path / "evidence.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    payload["unexpected"] = "not part of the evidence contract"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TrialEvidenceError):
        load_evidence_bundle(path)

    payload.pop("unexpected")
    payload["integrity"]["signed"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TrialEvidenceError):
        load_evidence_bundle(path)

    with pytest.raises(ValidationError):
        EvidenceIntegrity(
            digest="0" * 64,
            signed=True,  # type: ignore[arg-type]
        )


def test_evidence_digest_binds_integrity_metadata() -> None:
    bundle = _minimal_bundle()
    assert verify_evidence_bundle(bundle).valid

    tampered_integrity = bundle.integrity.model_construct(
        algorithm="sha256",
        digest=bundle.integrity.digest,
        signed=True,
    )
    tampered = bundle.model_copy(update={"integrity": tampered_integrity})

    assert not verify_evidence_bundle(tampered).valid


def test_format_one_bundle_keeps_legacy_digest_contract(tmp_path: Path) -> None:
    legacy = _minimal_bundle(format_version=1)
    assert verify_evidence_bundle(legacy).valid

    path = write_evidence_bundle(legacy, tmp_path / "legacy-evidence.json")
    loaded = load_evidence_bundle(path)

    assert loaded.format_version == 1
    assert verify_evidence_bundle(loaded).valid


async def test_evidence_reads_durable_records_from_one_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    active = _settings(tmp_path)
    job_id, idempotency_key = _seed_reserved_trial(active)
    original_get_job = evidence_module.CampaignStore.get_job
    mutated = False

    def get_job_then_mutate_live(self, requested_job_id: str):
        nonlocal mutated
        job = original_get_job(self, requested_job_id)
        if not mutated:
            mutated = True
            live_ledger = ActionLedger(active.state_db_path)
            try:
                live_ledger.mark_succeeded(
                    idempotency_key,
                    {"media_id": "live-state-moved-after-snapshot"},
                )
            finally:
                live_ledger.close()
        return job

    monkeypatch.setattr(
        evidence_module.CampaignStore,
        "get_job",
        get_job_then_mutate_live,
    )

    bundle = await TrialEvidenceService(active).build(job_id)

    assert bundle.format_version == 2
    assert bundle.action_ledger is not None
    assert bundle.action_ledger["status"] == "reserved"

    live_ledger = ActionLedger(active.state_db_path)
    try:
        assert live_ledger.status(idempotency_key) == "succeeded"
    finally:
        live_ledger.close()


def test_release_workflow_keeps_pr_and_manual_proofs_read_only() -> None:
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    proof, publish = text.split("\n  publish:\n", 1)

    assert "  proof:\n" in proof
    assert "permissions:\n      contents: read" in proof
    assert "contents: write" not in proof
    assert "packages: write" not in proof
    assert "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')" in publish
    assert "contents: write" in publish
    assert "packages: write" in publish
    assert 'if [[ "$GITHUB_EVENT_NAME" == "push" && "$GITHUB_REF" == refs/tags/* ]]' in proof


def test_docs_visual_capture_is_artifact_only_and_exact_sha() -> None:
    text = (ROOT / ".github" / "workflows" / "docs-visual-capture.yml").read_text(
        encoding="utf-8"
    )

    assert "permissions:\n  contents: read" in text
    assert "ref: ${{ github.sha }}" in text
    assert 'test "$checked_out_sha" = "$GITHUB_SHA"' in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text
    assert "git push" not in text
    assert "git commit" not in text
    assert "CAPTURE_PROVENANCE.md" in text


def test_code_of_conduct_scope_matches_available_reporting_channel() -> None:
    text = (ROOT / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")

    assert "GitHub-hosted project spaces" in text
    assert "offline event" not in text
    assert "official social media account" not in text
