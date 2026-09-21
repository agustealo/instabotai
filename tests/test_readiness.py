from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from instabotai.intelligence import IntelligenceProbe
from instabotai.readiness import ConsumerTrialReadinessService
from instabotai.settings import Settings


def settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "state_db_path": str(tmp_path / "state.sqlite3"),
        "instagram_access_token": "secret-token",
        "instagram_account_id": "account-123",
        "ui_open_browser": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def check_map(report):
    return {check.key: check for check in report.checks}


async def test_static_readiness_passes_core_with_configured_official_provider(
    tmp_path: Path,
) -> None:
    report = await ConsumerTrialReadinessService(settings(tmp_path)).evaluate()
    checks = check_map(report)

    assert report.ready
    assert checks["state"].status == "pass"
    assert checks["instagram_configuration"].status == "pass"
    assert checks["write_approval"].status == "pass"
    assert checks["ai_live"].status == "skip"
    assert checks["instagram_live"].status == "skip"


async def test_readiness_rejects_in_memory_state_as_non_durable(tmp_path: Path) -> None:
    report = await ConsumerTrialReadinessService(
        settings(tmp_path, state_db_path=":memory:")
    ).evaluate()
    state = check_map(report)["state"]

    assert not report.ready
    assert state.status == "fail"
    assert "transient" in state.detail
    assert "INSTABOTAI_STATE_DB_PATH" in (state.remediation or "")


async def test_readiness_blocks_missing_official_credentials(tmp_path: Path) -> None:
    active = settings(
        tmp_path,
        instagram_access_token=None,
        instagram_account_id=None,
    )

    report = await ConsumerTrialReadinessService(active).evaluate()
    checks = check_map(report)

    assert not report.ready
    assert checks["instagram_configuration"].status == "fail"
    assert "Instagram provider configuration" in report.blockers
    remediation = checks["instagram_configuration"].remediation or ""
    assert "INSTABOTAI_INSTAGRAM_ACCOUNT_ID" in remediation
    assert "INSTABOTAI_INSTAGRAM_ACCESS_TOKEN" in remediation


async def test_readiness_blocks_empty_official_token(tmp_path: Path) -> None:
    report = await ConsumerTrialReadinessService(
        settings(tmp_path, instagram_access_token="   ")
    ).evaluate()
    configuration = check_map(report)["instagram_configuration"]

    assert not report.ready
    assert configuration.status == "fail"
    assert "INSTABOTAI_INSTAGRAM_ACCESS_TOKEN" in (configuration.remediation or "")


async def test_private_credential_bundle_is_a_supported_login_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = tmp_path / "private-credentials.json"
    bundle.write_text(
        json.dumps({"username": "bundle-user", "password": "bundle-password"}),
        encoding="utf-8",
    )
    original = importlib.util.find_spec

    def find_spec(name: str, package: str | None = None):
        if name == "instagrapi":
            return object()
        return original(name, package)

    monkeypatch.setattr("instabotai.readiness.importlib.util.find_spec", find_spec)
    active = settings(
        tmp_path,
        instagram_provider="private",
        private_instagram_username=None,
        private_instagram_password=None,
        private_research_mode=True,
        private_credentials_file=str(bundle),
    )

    report = await ConsumerTrialReadinessService(active).evaluate()
    configuration = check_map(report)["instagram_configuration"]

    assert report.ready
    assert configuration.status == "pass"
    assert "supported credential source" in configuration.detail


async def test_readiness_requires_supervised_write_guardrail(tmp_path: Path) -> None:
    report = await ConsumerTrialReadinessService(
        settings(tmp_path, require_write_approval=False)
    ).evaluate()

    assert not report.ready
    assert check_map(report)["write_approval"].status == "fail"


async def test_required_research_extra_becomes_a_blocker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original = importlib.util.find_spec

    def find_spec(name: str, package: str | None = None):
        if name == "crawl4ai":
            return None
        return original(name, package)

    monkeypatch.setattr("instabotai.readiness.importlib.util.find_spec", find_spec)

    report = await ConsumerTrialReadinessService(settings(tmp_path)).evaluate(
        require_research=True
    )

    assert not report.ready
    assert check_map(report)["research"].status == "fail"
    assert "Research capability" in report.blockers


async def test_optional_missing_research_extra_warns_without_blocking(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original = importlib.util.find_spec

    def find_spec(name: str, package: str | None = None):
        if name == "crawl4ai":
            return None
        return original(name, package)

    monkeypatch.setattr("instabotai.readiness.importlib.util.find_spec", find_spec)

    report = await ConsumerTrialReadinessService(settings(tmp_path)).evaluate()

    assert report.ready
    assert check_map(report)["research"].status == "warn"
    assert "Research capability" in report.warnings


async def test_live_readiness_runs_real_probe_contracts_via_injected_boundaries(
    tmp_path: Path,
) -> None:
    ai_calls = 0
    provider_calls = 0

    async def ai_probe() -> IntelligenceProbe:
        nonlocal ai_calls
        ai_calls += 1
        return IntelligenceProbe(
            ok=True,
            capability="reasoning",
            provider="scripted",
            model="scripted-model",
            latency_ms=11,
        )

    async def profile_probe() -> dict[str, object]:
        nonlocal provider_calls
        provider_calls += 1
        return {"id": "account-123", "username": "brand"}

    report = await ConsumerTrialReadinessService(
        settings(tmp_path),
        ai_probe=ai_probe,
        profile_probe=profile_probe,
    ).evaluate(live=True)
    checks = check_map(report)

    assert report.ready
    assert ai_calls == 1
    assert provider_calls == 1
    assert checks["ai_live"].status == "pass"
    assert checks["instagram_live"].status == "pass"


async def test_live_failures_do_not_leak_secret_exception_text(tmp_path: Path) -> None:
    async def ai_probe() -> IntelligenceProbe:
        raise RuntimeError("Bearer super-secret-ai-token")

    async def profile_probe() -> dict[str, object]:
        raise RuntimeError("Bearer super-secret-instagram-token")

    report = await ConsumerTrialReadinessService(
        settings(tmp_path),
        ai_probe=ai_probe,
        profile_probe=profile_probe,
    ).evaluate(live=True)
    serialized = report.model_dump_json()

    assert not report.ready
    assert "super-secret-ai-token" not in serialized
    assert "super-secret-instagram-token" not in serialized
    assert check_map(report)["ai_live"].status == "fail"
    assert check_map(report)["instagram_live"].status == "fail"
