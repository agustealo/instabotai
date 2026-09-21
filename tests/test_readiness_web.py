from __future__ import annotations

from pathlib import Path

import httpx

from instabotai.intelligence import IntelligenceProbe
from instabotai.settings import Settings
from instabotai.web import create_app


class ReadinessFakeService:
    def __init__(self) -> None:
        self.ai_calls = 0
        self.profile_calls = 0

    async def ai_check(self) -> IntelligenceProbe:
        self.ai_calls += 1
        return IntelligenceProbe(
            ok=True,
            capability="reasoning",
            provider="scripted",
            model="scripted-model",
            latency_ms=9,
        )

    async def profile(self) -> dict[str, object]:
        self.profile_calls += 1
        return {
            "id": "account-123",
            "username": "brand",
            "account_type": "BUSINESS",
        }


def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        state_db_path=str(tmp_path / "state.sqlite3"),
        instagram_access_token="super-secret-instagram-token",
        instagram_account_id="account-123",
        ui_open_browser=False,
    )


def client(
    tmp_path: Path,
) -> tuple[httpx.AsyncClient, ReadinessFakeService]:
    active_settings = settings(tmp_path)
    service = ReadinessFakeService()
    transport = httpx.ASGITransport(
        app=create_app(settings=active_settings, service=service)  # type: ignore[arg-type]
    )
    return httpx.AsyncClient(transport=transport, base_url="http://testserver"), service


async def test_static_readiness_api_reports_real_local_gate_without_secrets(
    tmp_path: Path,
) -> None:
    web, service = client(tmp_path)
    async with web:
        response = await web.get("/api/readiness")

    payload = response.json()
    checks = {check["key"]: check for check in payload["checks"]}

    assert response.status_code == 200
    assert payload["ready"] is True
    assert payload["live_probes"] is False
    assert checks["state"]["status"] == "pass"
    assert checks["instagram_configuration"]["status"] == "pass"
    assert checks["ai_live"]["status"] == "skip"
    assert checks["instagram_live"]["status"] == "skip"
    assert service.ai_calls == 0
    assert service.profile_calls == 0
    assert "super-secret-instagram-token" not in response.text
    assert response.headers["cache-control"] == "no-store"


async def test_live_readiness_api_uses_canonical_ai_and_provider_read_paths(
    tmp_path: Path,
) -> None:
    web, service = client(tmp_path)
    async with web:
        response = await web.post("/api/readiness/probe", json={})

    payload = response.json()
    checks = {check["key"]: check for check in payload["checks"]}

    assert response.status_code == 200
    assert payload["ready"] is True
    assert payload["live_probes"] is True
    assert checks["ai_live"]["status"] == "pass"
    assert checks["instagram_live"]["status"] == "pass"
    assert service.ai_calls == 1
    assert service.profile_calls == 1
    assert response.headers["cache-control"] == "no-store"


async def test_consumer_console_exposes_live_readiness_control(tmp_path: Path) -> None:
    web, _ = client(tmp_path)
    async with web:
        response = await web.get("/")

    assert response.status_code == 200
    assert "Consumer-trial readiness" in response.text
    assert 'id="run-readiness"' in response.text
    assert "Run live checks" in response.text
