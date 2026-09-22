from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from instabotai.domain import ActionType, PlannedAction
from instabotai.evidence import (
    EvidenceIntegrity,
    TrialEvidenceBundle,
    TrialEvidenceService,
    _state_snapshot,
)
from instabotai.settings import Settings
from instabotai.state import ActionLedger
from instabotai.storage import upgrade_state_database

ROOT = Path(__file__).resolve().parents[1]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        state_db_path=str(tmp_path / "state.sqlite3"),
        instagram_access_token="configured-instagram-secret",
        instagram_account_id="account-123",
        ai_api_key="configured-ai-secret",
        require_write_approval=True,
        ui_open_browser=False,
    )


def test_evidence_redacts_camel_case_credential_keys(tmp_path: Path) -> None:
    service = TrialEvidenceService(_settings(tmp_path))

    sanitized = service._sanitize(
        {
            "accessToken": "one",
            "refreshToken": "two",
            "apiKey": "three",
            "clientSecret": "four",
            "nested": {"instagramSessionId": "five"},
            "tokenCount": 7,
        }
    )

    assert sanitized == {
        "accessToken": "[redacted]",
        "refreshToken": "[redacted]",
        "apiKey": "[redacted]",
        "clientSecret": "[redacted]",
        "nested": {"instagramSessionId": "[redacted]"},
        "tokenCount": 7,
    }


def test_evidence_models_reject_unknown_fields_and_false_signature_claims() -> None:
    with pytest.raises(ValidationError) as unknown:
        TrialEvidenceBundle.model_validate({"unexpected": "discard-me"})
    assert any(
        error["type"] == "extra_forbidden" and error["loc"] == ("unexpected",)
        for error in unknown.value.errors()
    )

    with pytest.raises(ValidationError):
        EvidenceIntegrity(digest="0" * 64, signed=True)  # type: ignore[arg-type]


def test_state_snapshot_is_a_consistent_point_in_time(tmp_path: Path) -> None:
    database = str(tmp_path / "state.sqlite3")
    upgrade_state_database(database)
    action = PlannedAction(
        action_type=ActionType.PUBLISH_IMAGE,
        reason="snapshot regression",
        confidence=0.95,
        payload={"image_url": "https://example.test/image.jpg"},
        idempotency_key="snapshot-evidence-action",
    )
    ledger = ActionLedger(database)
    ledger.reserve(action, daily_limit=10)
    ledger.mark_succeeded(action.idempotency_key, {"media_id": "before-snapshot"})
    ledger.close()

    with _state_snapshot(database) as snapshot:
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                UPDATE automation_actions
                SET status = 'failed', retryable = 1, provider_result = NULL,
                    error = 'changed after snapshot'
                WHERE idempotency_key = ?
                """,
                (action.idempotency_key,),
            )
            connection.commit()

        snapshot_ledger = ActionLedger(str(snapshot))
        snapshot_record = snapshot_ledger.get_record(action.idempotency_key)
        snapshot_ledger.close()

        live_ledger = ActionLedger(database)
        live_record = live_ledger.get_record(action.idempotency_key)
        live_ledger.close()

    assert snapshot_record is not None
    assert snapshot_record.status == "succeeded"
    assert snapshot_record.provider_result == {"media_id": "before-snapshot"}
    assert live_record is not None
    assert live_record.status == "failed"


def test_release_burn_is_read_only_and_publication_is_tag_push_only() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    release_job, publish_job = workflow.split("\n  publish:\n", 1)

    assert "contents: write" not in release_job
    assert "packages: write" not in release_job
    assert "permissions:\n      contents: read" in release_job

    assert "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')" in publish_job
    assert "actions: read" in publish_job
    assert "contents: write" in publish_job
    assert "packages: write" in publish_job
    assert "gh run download \"$GITHUB_RUN_ID\"" in publish_job


def test_docs_capture_commits_image_provenance_and_inventory_together() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "docs-visual-capture.yml"
    ).read_text(encoding="utf-8")

    assert "docs/screenshots/consumer-console-overview.png" in workflow
    assert "docs/screenshots/CAPTURE_PROVENANCE.md" in workflow
    assert "docs/PRODUCT_SURFACES.md" in workflow
    assert "CAPTURE_SHA: ${{ github.sha }}" in workflow
    assert "CAPTURE_RUN_ID: ${{ github.run_id }}" in workflow
    assert "git add \\" in workflow
