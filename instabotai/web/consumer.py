"""Consumer-console security and embedded scheduler control plane."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from pydantic import BaseModel
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from instabotai.campaigns.domain import WorkerTick
from instabotai.settings import Settings, get_settings, runtime_config_file
from instabotai.web.app import create_app as _create_app

LOGGER = logging.getLogger(__name__)
_MAX_API_BODY_BYTES = 1_048_576
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_TEST_HOST = "testserver"


class ConsumerWorkerStatus(BaseModel):
    """Secret-free health snapshot for the scheduler embedded in the GUI process."""

    enabled: bool
    running: bool = False
    poll_seconds: float
    started_at: datetime | None = None
    last_tick_at: datetime | None = None
    last_planned_campaign_id: str | None = None
    last_created_job_id: str | None = None
    last_executed_job_id: str | None = None
    last_execution_status: str | None = None
    last_error: str | None = None


class ConsumerConsoleInfo(BaseModel):
    """Non-secret consumer runtime facts useful during first-run setup."""

    config_file: str
    loopback_only: bool = True
    embedded_scheduler: bool = True


def _host_name(raw_host: str) -> str:
    parsed = urlsplit(f"//{raw_host.strip()}")
    return (parsed.hostname or "").lower().rstrip(".")


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]").rstrip(".")
    if normalized in {"localhost", _TEST_HOST}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _same_origin(request: Request, origin: str) -> bool:
    try:
        parsed_origin = urlsplit(origin)
        host_header = request.headers.get("host", "")
        parsed_host = urlsplit(f"//{host_header}")
        origin_port = parsed_origin.port or (443 if parsed_origin.scheme == "https" else 80)
        request_port = parsed_host.port or (443 if request.url.scheme == "https" else 80)
    except ValueError:
        return False
    return (
        parsed_origin.scheme == request.url.scheme
        and (parsed_origin.hostname or "").lower() == (parsed_host.hostname or "").lower()
        and origin_port == request_port
    )


def validate_ui_bind(_settings: Settings, host: str) -> str:
    """Keep the consumer alpha on loopback until an authenticated remote UI exists."""

    normalized = host.strip()
    if not normalized or not _is_loopback_host(normalized):
        raise ValueError(
            "InstabotAI 2.0 alpha consumer UI is loopback-only. "
            "Use 127.0.0.1, localhost, or ::1; authenticated remote access is not yet exposed."
        )
    return normalized


async def _run_worker(
    service: Any,
    status: ConsumerWorkerStatus,
    poll_seconds: float,
) -> None:
    status.running = True
    status.started_at = datetime.now(UTC)
    try:
        while True:
            try:
                raw_tick = await service.worker_tick()
                tick = raw_tick if isinstance(raw_tick, WorkerTick) else WorkerTick.model_validate(raw_tick)
                status.last_tick_at = datetime.now(UTC)
                status.last_planned_campaign_id = tick.planned_campaign_id
                status.last_created_job_id = tick.created_job_id
                status.last_executed_job_id = tick.executed_job_id
                status.last_execution_status = (
                    tick.execution_status.value if tick.execution_status is not None else None
                )
                errors = [value for value in (tick.planning_error, tick.execution_error) if value]
                status.last_error = " | ".join(errors) if errors else None
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive worker survival boundary
                status.last_tick_at = datetime.now(UTC)
                status.last_error = f"{type(exc).__name__}: {exc}"
                LOGGER.exception("Embedded campaign worker tick failed")
            await asyncio.sleep(poll_seconds)
    finally:
        status.running = False


def create_app(
    *,
    settings: Settings | None = None,
    service: Any | None = None,
) -> FastAPI:
    """Build the consumer console with browser and scheduler hardening around canonical APIs."""

    active_settings = settings or get_settings()
    app = _create_app(settings=active_settings, service=service)
    application_service = app.state.service
    worker_tick = getattr(application_service, "worker_tick", None)
    worker_status = ConsumerWorkerStatus(
        enabled=callable(worker_tick),
        poll_seconds=active_settings.campaign_worker_poll_seconds,
    )
    app.state.consumer_worker_status = worker_status
    app.state.consumer_worker_task = None

    @app.middleware("http")
    async def consumer_request_boundary(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        host_header = request.headers.get("host", "")
        if not _is_loopback_host(_host_name(host_header)):
            return JSONResponse(status_code=400, content={"detail": "untrusted Host header"})

        if request.url.path.startswith("/api/") and request.method.upper() in _UNSAFE_METHODS:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > _MAX_API_BODY_BYTES:
                        return JSONResponse(
                            status_code=413,
                            content={"detail": "request body exceeds consumer API limit"},
                        )
                except ValueError:
                    return JSONResponse(status_code=400, content={"detail": "invalid Content-Length"})

            if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
                return JSONResponse(status_code=403, content={"detail": "cross-site mutation denied"})

            origin = request.headers.get("origin")
            if origin is not None and not _same_origin(request, origin):
                return JSONResponse(status_code=403, content={"detail": "cross-origin mutation denied"})

            if content_length not in {None, "0"}:
                media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if media_type != "application/json":
                    return JSONResponse(
                        status_code=415,
                        content={"detail": "consumer API mutations require application/json"},
                    )

        return await call_next(request)

    async def start_embedded_worker() -> None:
        if not worker_status.enabled or app.state.consumer_worker_task is not None:
            return
        app.state.consumer_worker_task = asyncio.create_task(
            _run_worker(application_service, worker_status, active_settings.campaign_worker_poll_seconds),
            name="instabotai-consumer-campaign-worker",
        )

    async def stop_embedded_worker() -> None:
        task: asyncio.Task[None] | None = app.state.consumer_worker_task
        app.state.consumer_worker_task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    app.add_event_handler("startup", start_embedded_worker)
    app.add_event_handler("shutdown", stop_embedded_worker)

    @app.get("/api/worker", response_model=ConsumerWorkerStatus, include_in_schema=False)
    async def consumer_worker_status() -> ConsumerWorkerStatus:
        return worker_status.model_copy(deep=True)

    @app.get("/api/consumer", response_model=ConsumerConsoleInfo, include_in_schema=False)
    async def consumer_console_info() -> ConsumerConsoleInfo:
        return ConsumerConsoleInfo(config_file=str(runtime_config_file()))

    return app
