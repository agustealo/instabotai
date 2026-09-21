"""FastAPI consumer console for the InstabotAI runtime."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Protocol

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from instabotai import __version__
from instabotai.application import InstabotApplication, PlanResult, RuntimeSnapshot
from instabotai.domain import ResearchReport
from instabotai.intelligence import EvidenceItem, IntelligenceDecision, IntelligenceProbe
from instabotai.intelligence.providers import IntelligenceProviderError
from instabotai.providers.instagram import InstagramProviderError
from instabotai.settings import Settings, get_settings

LOGGER = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).with_name("static")


class ApplicationService(Protocol):
    """Contract consumed by the HTTP presentation layer."""

    def runtime_snapshot(self) -> RuntimeSnapshot:
        """Return safe runtime configuration."""

    async def ai_check(self) -> IntelligenceProbe:
        """Perform one real model probe."""

    async def plan(
        self,
        *,
        objective: str,
        evidence: list[EvidenceItem],
        context: dict[str, Any] | None = None,
    ) -> PlanResult:
        """Create one reviewed, non-executing AI plan."""

    def recent_decisions(self, limit: int = 25) -> tuple[IntelligenceDecision, ...]:
        """Read recent durable decisions."""

    async def profile(self) -> dict[str, Any]:
        """Read the connected Instagram profile."""

    async def research(self, *, objective: str, seed_urls: list[str]) -> ResearchReport:
        """Run adaptive public-web research."""


class PlanRequest(BaseModel):
    """Browser request for one reviewed AI planning pass."""

    objective: str = Field(min_length=3, max_length=2_000)
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=100)
    context: dict[str, Any] = Field(default_factory=dict)


class ResearchRequest(BaseModel):
    """Browser request for one bounded adaptive research run."""

    objective: str = Field(min_length=3, max_length=2_000)
    seed_urls: list[str] = Field(min_length=1, max_length=20)


class APIError(BaseModel):
    """Stable error envelope used by consumer surfaces."""

    code: str
    message: str


def create_app(
    *,
    settings: Settings | None = None,
    service: ApplicationService | None = None,
) -> FastAPI:
    """Create the consumer web application without duplicating domain logic."""

    active_settings = settings or get_settings()
    application_service = service or InstabotApplication(active_settings)
    app = FastAPI(
        title="InstabotAI Consumer Console",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = active_settings
    app.state.service = application_service
    app.state.ai_slots = asyncio.Semaphore(active_settings.ui_ai_max_concurrency)
    app.state.research_slots = asyncio.Semaphore(active_settings.ui_research_max_concurrency)

    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(IntelligenceProviderError)
    async def intelligence_error(_: Request, exc: IntelligenceProviderError) -> JSONResponse:
        return _error_response("ai_provider_error", str(exc), 503)

    @app.exception_handler(InstagramProviderError)
    async def instagram_error(_: Request, exc: InstagramProviderError) -> JSONResponse:
        return _error_response("instagram_provider_error", str(exc), 503)

    @app.exception_handler(httpx.HTTPError)
    async def http_error(_: Request, exc: httpx.HTTPError) -> JSONResponse:
        return _error_response("upstream_http_error", str(exc), 503)

    @app.exception_handler(RuntimeError)
    async def runtime_error(_: Request, exc: RuntimeError) -> JSONResponse:
        return _error_response("runtime_error", str(exc), 503)

    @app.exception_handler(ValueError)
    async def value_error(_: Request, exc: ValueError) -> JSONResponse:
        return _error_response("invalid_operation", str(exc), 400)

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("Unhandled consumer-console error", exc_info=exc)
        return _error_response(
            "internal_error",
            "The operation failed unexpectedly. Review server logs for details.",
            500,
        )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/runtime", response_model=RuntimeSnapshot)
    async def runtime() -> RuntimeSnapshot:
        return application_service.runtime_snapshot()

    @app.post("/api/ai/probe", response_model=IntelligenceProbe)
    async def ai_probe(request: Request) -> IntelligenceProbe:
        async with request.app.state.ai_slots:
            return await application_service.ai_check()

    @app.post("/api/ai/plan", response_model=PlanResult)
    async def ai_plan(payload: PlanRequest, request: Request) -> PlanResult:
        async with request.app.state.ai_slots:
            return await application_service.plan(
                objective=payload.objective,
                evidence=payload.evidence,
                context=payload.context,
            )

    @app.get("/api/ai/decisions", response_model=list[IntelligenceDecision])
    async def decisions(
        limit: int = Query(default=25, ge=1, le=500),
    ) -> list[IntelligenceDecision]:
        return list(application_service.recent_decisions(limit))

    @app.get("/api/account/profile")
    async def account_profile() -> dict[str, Any]:
        return await application_service.profile()

    @app.post("/api/research", response_model=ResearchReport)
    async def research(payload: ResearchRequest, request: Request) -> ResearchReport:
        async with request.app.state.research_slots:
            return await application_service.research(
                objective=payload.objective,
                seed_urls=payload.seed_urls,
            )

    return app


def validate_ui_bind(settings: Settings, host: str) -> str:
    """Fail closed when the consumer console would be exposed remotely by accident."""

    normalized = host.strip()
    if not normalized:
        raise ValueError("UI host must not be empty")
    loopback_hosts = {"127.0.0.1", "::1", "localhost"}
    if normalized not in loopback_hosts and not settings.ui_allow_remote:
        raise ValueError(
            "refusing non-loopback UI bind; set INSTABOTAI_UI_ALLOW_REMOTE=true deliberately"
        )
    return normalized


def _error_response(code: str, message: str, status_code: int) -> JSONResponse:
    payload = APIError(code=code, message=message)
    return JSONResponse(status_code=status_code, content=payload.model_dump())
