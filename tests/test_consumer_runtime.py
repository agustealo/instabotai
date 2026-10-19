from __future__ import annotations

import asyncio

import httpx

from instabotai.campaigns.domain import WorkerTick
from instabotai.settings import Settings
from instabotai.web import create_app, validate_ui_bind


class WorkerOnlyService:
    def __init__(self) -> None:
        self.ticks = 0

    async def worker_tick(self) -> WorkerTick:
        self.ticks += 1
        return WorkerTick(planned_campaign_id="campaign-1")


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "state_db_path": ":memory:",
        "ui_open_browser": False,
        "campaign_worker_poll_seconds": 300.0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_consumer_bind_is_loopback_only_even_when_legacy_opt_in_is_set() -> None:
    assert validate_ui_bind(settings(), "127.0.0.1") == "127.0.0.1"
    assert validate_ui_bind(settings(), "localhost") == "localhost"
    assert validate_ui_bind(settings(), "::1") == "::1"

    for active_settings in (settings(), settings(ui_allow_remote=True)):
        try:
            validate_ui_bind(active_settings, "0.0.0.0")
        except ValueError as exc:
            assert "loopback-only" in str(exc)
        else:
            raise AssertionError("consumer alpha must reject non-loopback UI binds")


async def test_consumer_request_boundary_rejects_dns_rebinding_host() -> None:
    app = create_app(settings=settings(), service=WorkerOnlyService())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://evil.example") as client:
        response = await client.get("/healthz")
    assert response.status_code == 400
    assert response.json()["detail"] == "untrusted Host header"


async def test_consumer_request_boundary_rejects_cross_site_mutation() -> None:
    app = create_app(settings=settings(), service=WorkerOnlyService())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/ai/probe",
            headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://attacker.example"},
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "cross-site mutation denied"


async def test_consumer_request_boundary_rejects_non_json_mutation_body() -> None:
    app = create_app(settings=settings(), service=WorkerOnlyService())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/ai/probe",
            content="action=run",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    assert response.status_code == 415


async def test_consumer_request_boundary_rejects_oversized_declared_body() -> None:
    app = create_app(settings=settings(), service=WorkerOnlyService())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/ai/probe",
            headers={"Content-Length": str(1_048_577)},
        )
    assert response.status_code == 413


async def test_consumer_console_exposes_config_path_without_secrets() -> None:
    app = create_app(settings=settings(), service=WorkerOnlyService())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/consumer")
    assert response.status_code == 200
    payload = response.json()
    assert payload["loopback_only"] is True
    assert payload["embedded_scheduler"] is True
    assert payload["config_file"].endswith(".env")


async def test_embedded_worker_runs_and_reports_health() -> None:
    service = WorkerOnlyService()
    app = create_app(settings=settings(), service=service)

    await app.router.startup()
    try:
        for _ in range(50):
            if service.ticks:
                break
            await asyncio.sleep(0.001)
        assert service.ticks == 1

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/worker")
        payload = response.json()
        assert payload["enabled"] is True
        assert payload["running"] is True
        assert payload["last_planned_campaign_id"] == "campaign-1"
        assert payload["last_tick_at"] is not None
    finally:
        await app.router.shutdown()

    assert app.state.consumer_worker_status.running is False
