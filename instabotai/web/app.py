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
from instabotai.campaigns import (
    Campaign,
    CampaignJob,
    CampaignMode,
    CampaignNotFoundError,
    CampaignPlanOutcome,
    CampaignStateError,
)
from instabotai.domain import ResearchReport
from instabotai.intelligence import EvidenceItem, IntelligenceDecision, IntelligenceProbe
from instabotai.intelligence.providers import IntelligenceProviderError
from instabotai.providers.instagram import InstagramProviderError
from instabotai.settings import Settings, get_settings

LOGGER = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).with_name("static")


class ApplicationService(Protocol):
    def runtime_snapshot(self) -> RuntimeSnapshot: ...
    async def ai_check(self) -> IntelligenceProbe: ...
    async def plan(
        self,
        *,
        objective: str,
        evidence: list[EvidenceItem],
        context: dict[str, Any] | None = None,
    ) -> PlanResult: ...
    def recent_decisions(self, limit: int = 25) -> tuple[IntelligenceDecision, ...]: ...
    async def profile(self) -> dict[str, Any]: ...
    async def research(self, *, objective: str, seed_urls: list[str]) -> ResearchReport: ...
    def create_campaign(
        self,
        *,
        name: str,
        objective: str,
        mode: CampaignMode,
        cadence_minutes: int,
        action_delay_minutes: int,
        evidence: list[EvidenceItem],
        context: dict[str, Any],
        research_seed_urls: list[str],
        research_before_plan: bool,
    ) -> Campaign: ...
    def list_campaigns(self, limit: int = 100) -> tuple[Campaign, ...]: ...
    def activate_campaign(self, campaign_id: str) -> Campaign: ...
    def pause_campaign(self, campaign_id: str) -> Campaign: ...
    def archive_campaign(self, campaign_id: str) -> Campaign: ...
    async def plan_campaign_now(self, campaign_id: str) -> CampaignPlanOutcome: ...
    def list_campaign_jobs(
        self,
        *,
        campaign_id: str | None = None,
        limit: int = 100,
    ) -> tuple[CampaignJob, ...]: ...
    def approve_campaign_job(self, job_id: str) -> CampaignJob: ...
    def reject_campaign_job(self, job_id: str) -> CampaignJob: ...
    def cancel_campaign_job(self, job_id: str) -> CampaignJob: ...
    async def execute_campaign_job(self, job_id: str) -> CampaignJob: ...
    def record_campaign_outcome(
        self,
        job_id: str,
        *,
        reward: float,
        note: str = "",
    ) -> CampaignJob: ...


class PlanRequest(BaseModel):
    objective: str = Field(min_length=3, max_length=2_000)
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=100)
    context: dict[str, Any] = Field(default_factory=dict)


class ResearchRequest(BaseModel):
    objective: str = Field(min_length=3, max_length=2_000)
    seed_urls: list[str] = Field(min_length=1, max_length=20)


class CampaignCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    objective: str = Field(min_length=3, max_length=2_000)
    mode: CampaignMode = CampaignMode.SUPERVISED
    cadence_minutes: int = Field(default=1440, ge=5, le=43_200)
    action_delay_minutes: int = Field(default=0, ge=0, le=10_080)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=100)
    context: dict[str, Any] = Field(default_factory=dict)
    research_seed_urls: list[str] = Field(default_factory=list, max_length=20)
    research_before_plan: bool = False


class OutcomeRequest(BaseModel):
    reward: float = Field(ge=0.0, le=1.0)
    note: str = Field(default="", max_length=4_000)


class APIError(BaseModel):
    code: str
    message: str


def create_app(
    *,
    settings: Settings | None = None,
    service: ApplicationService | None = None,
) -> FastAPI:
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
    app.state.campaign_slots = asyncio.Semaphore(active_settings.ui_campaign_max_concurrency)

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

    @app.exception_handler(CampaignNotFoundError)
    async def campaign_not_found(_: Request, exc: CampaignNotFoundError) -> JSONResponse:
        return _error_response("campaign_not_found", str(exc), 404)

    @app.exception_handler(CampaignStateError)
    async def campaign_state_error(_: Request, exc: CampaignStateError) -> JSONResponse:
        return _error_response("campaign_state_error", str(exc), 409)

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

    @app.post("/api/campaigns", response_model=Campaign, status_code=201)
    async def create_campaign(payload: CampaignCreateRequest) -> Campaign:
        return application_service.create_campaign(
            name=payload.name,
            objective=payload.objective,
            mode=payload.mode,
            cadence_minutes=payload.cadence_minutes,
            action_delay_minutes=payload.action_delay_minutes,
            evidence=payload.evidence,
            context=payload.context,
            research_seed_urls=payload.research_seed_urls,
            research_before_plan=payload.research_before_plan,
        )

    @app.get("/api/campaigns", response_model=list[Campaign])
    async def campaigns(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[Campaign]:
        return list(application_service.list_campaigns(limit))

    @app.post("/api/campaigns/{campaign_id}/activate", response_model=Campaign)
    async def activate_campaign(campaign_id: str) -> Campaign:
        return application_service.activate_campaign(campaign_id)

    @app.post("/api/campaigns/{campaign_id}/pause", response_model=Campaign)
    async def pause_campaign(campaign_id: str) -> Campaign:
        return application_service.pause_campaign(campaign_id)

    @app.post("/api/campaigns/{campaign_id}/archive", response_model=Campaign)
    async def archive_campaign(campaign_id: str) -> Campaign:
        return application_service.archive_campaign(campaign_id)

    @app.post("/api/campaigns/{campaign_id}/plan-now", response_model=CampaignPlanOutcome)
    async def plan_campaign(campaign_id: str, request: Request) -> CampaignPlanOutcome:
        async with request.app.state.campaign_slots:
            return await application_service.plan_campaign_now(campaign_id)

    @app.get("/api/campaign-jobs", response_model=list[CampaignJob])
    async def campaign_jobs(
        campaign_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[CampaignJob]:
        return list(
            application_service.list_campaign_jobs(
                campaign_id=campaign_id,
                limit=limit,
            )
        )

    @app.post("/api/campaign-jobs/{job_id}/approve", response_model=CampaignJob)
    async def approve_job(job_id: str) -> CampaignJob:
        return application_service.approve_campaign_job(job_id)

    @app.post("/api/campaign-jobs/{job_id}/reject", response_model=CampaignJob)
    async def reject_job(job_id: str) -> CampaignJob:
        return application_service.reject_campaign_job(job_id)

    @app.post("/api/campaign-jobs/{job_id}/cancel", response_model=CampaignJob)
    async def cancel_job(job_id: str) -> CampaignJob:
        return application_service.cancel_campaign_job(job_id)

    @app.post("/api/campaign-jobs/{job_id}/execute", response_model=CampaignJob)
    async def execute_job(job_id: str, request: Request) -> CampaignJob:
        async with request.app.state.campaign_slots:
            return await application_service.execute_campaign_job(job_id)

    @app.post("/api/campaign-jobs/{job_id}/outcome", response_model=CampaignJob)
    async def record_outcome(job_id: str, payload: OutcomeRequest) -> CampaignJob:
        return application_service.record_campaign_outcome(
            job_id,
            reward=payload.reward,
            note=payload.note,
        )

    return app


def validate_ui_bind(settings: Settings, host: str) -> str:
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
