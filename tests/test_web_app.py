from __future__ import annotations

from typing import Any

import httpx

from instabotai.application import InstabotApplication, PlanResult
from instabotai.domain import ActionType, ApprovalState, PlannedAction, ResearchPage, ResearchReport
from instabotai.intelligence import (
    DecisionCandidate,
    DecisionReview,
    EvidenceItem,
    IntelligenceDecision,
    IntelligenceProbe,
)
from instabotai.settings import Settings
from instabotai.web import create_app, validate_ui_bind


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "state_db_path": ":memory:",
        "ai_api_key": "super-secret-ai-key",
        "instagram_access_token": "super-secret-instagram-token",
        "instagram_account_id": "account-123",
        "ui_open_browser": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def sample_decision() -> IntelligenceDecision:
    candidate = DecisionCandidate(
        candidate_id="candidate-1",
        action="publish_image",
        rationale="The approved announcement is ready.",
        confidence=0.92,
        expected_utility=0.84,
        risk=0.08,
        payload={"image_url": "https://cdn.example.com/image.jpg", "caption": "Launch day"},
        evidence_refs=("evidence-1",),
    )
    return IntelligenceDecision(
        decision_id="1234567890abcdef1234567890abcdef",
        objective="Publish the approved announcement.",
        selected=candidate,
        score=0.88,
        review=DecisionReview(
            support_score=0.93,
            risk_score=0.07,
            should_abstain=False,
        ),
        assumptions=(),
        uncertainty="",
        explanation="Evidence and critic review support the selected action.",
        abstained=False,
        provider="scripted",
        model="scripted-model",
    )


class FakeService:
    def __init__(self, active_settings: Settings) -> None:
        self.snapshot = InstabotApplication(active_settings).runtime_snapshot()
        self.last_plan: dict[str, Any] | None = None
        self.last_limit: int | None = None
        self.last_research: dict[str, Any] | None = None
        self.decision = sample_decision()

    def runtime_snapshot(self):
        return self.snapshot

    async def ai_check(self) -> IntelligenceProbe:
        return IntelligenceProbe(
            ok=True,
            capability="reasoning",
            provider="scripted",
            model="scripted-model",
            latency_ms=7,
        )

    async def plan(
        self,
        *,
        objective: str,
        evidence: list[EvidenceItem],
        context: dict[str, Any] | None = None,
    ) -> PlanResult:
        self.last_plan = {
            "objective": objective,
            "evidence": evidence,
            "context": context,
        }
        action = PlannedAction(
            action_type=ActionType.PUBLISH_IMAGE,
            reason="AI-reviewed candidate awaiting approval.",
            confidence=0.88,
            payload={"image_url": "https://cdn.example.com/image.jpg", "caption": "Launch day"},
            idempotency_key="ai-test-web-123456",
            approval=ApprovalState.PENDING,
        )
        return PlanResult(decision=self.decision, planned_action=action)

    def recent_decisions(self, limit: int = 25) -> tuple[IntelligenceDecision, ...]:
        self.last_limit = limit
        return (self.decision,)

    async def profile(self) -> dict[str, Any]:
        return {
            "id": "account-123",
            "username": "instabotai_test",
            "account_type": "BUSINESS",
            "media_count": 12,
        }

    async def research(self, *, objective: str, seed_urls: list[str]) -> ResearchReport:
        self.last_research = {"objective": objective, "seed_urls": seed_urls}
        return ResearchReport(
            objective=objective,
            pages=(
                ResearchPage(
                    url=seed_urls[0],
                    title="Industry report",
                    markdown="Relevant market evidence.",
                    relevance=0.8,
                ),
            ),
            confidence=0.76,
            stopped_early=False,
        )


def client() -> tuple[httpx.AsyncClient, FakeService]:
    active_settings = settings()
    service = FakeService(active_settings)
    transport = httpx.ASGITransport(app=create_app(settings=active_settings, service=service))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver"), service


async def test_consumer_console_serves_real_ai_surface_and_security_headers() -> None:
    web, _ = client()
    async with web:
        response = await web.get("/")

    assert response.status_code == 200
    assert "AI Studio" in response.text
    assert "Decision Audit" in response.text
    assert "Research" in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]


async def test_runtime_api_is_secret_free_and_reports_canonical_authorities() -> None:
    web, _ = client()
    async with web:
        response = await web.get("/api/runtime")
    payload = response.json()
    serialized = response.text

    assert response.status_code == 200
    assert payload["ai"]["provider"] == "ollama"
    assert payload["instagram"]["account_configured"] is True
    assert payload["instagram"]["token_configured"] is True
    assert payload["policy"]["write_approval_required"] is True
    assert "super-secret-ai-key" not in serialized
    assert "super-secret-instagram-token" not in serialized
    assert response.headers["cache-control"] == "no-store"


async def test_ai_probe_endpoint_returns_real_contract_shape() -> None:
    web, _ = client()
    async with web:
        response = await web.post("/api/ai/probe")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "capability": "reasoning",
        "provider": "scripted",
        "model": "scripted-model",
        "latency_ms": 7,
    }


async def test_ai_plan_endpoint_preserves_evidence_context_and_pending_approval() -> None:
    web, service = client()
    async with web:
        response = await web.post(
            "/api/ai/plan",
            json={
                "objective": "Publish the approved announcement.",
                "evidence": [
                    {
                        "evidence_id": "evidence-1",
                        "source": "launch brief",
                        "content": "The announcement is approved.",
                        "confidence": 1.0,
                    }
                ],
                "context": {"campaign": "fall-launch"},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"]["decision_id"] == service.decision.decision_id
    assert payload["planned_action"]["approval"] == "pending"
    assert service.last_plan is not None
    assert service.last_plan["context"] == {"campaign": "fall-launch"}
    assert service.last_plan["evidence"][0].evidence_id == "evidence-1"


async def test_ai_plan_requires_at_least_one_evidence_record() -> None:
    web, _ = client()
    async with web:
        response = await web.post(
            "/api/ai/plan",
            json={
                "objective": "Publish the approved announcement.",
                "evidence": [],
                "context": {},
            },
        )

    assert response.status_code == 422


async def test_decision_audit_endpoint_honors_bounded_limit() -> None:
    web, service = client()
    async with web:
        response = await web.get("/api/ai/decisions?limit=11")

    assert response.status_code == 200
    assert service.last_limit == 11
    assert response.json()[0]["decision_id"] == service.decision.decision_id


async def test_research_endpoint_routes_through_canonical_research_service() -> None:
    web, service = client()
    async with web:
        response = await web.post(
            "/api/research",
            json={
                "objective": "Research current fitness marketing themes.",
                "seed_urls": ["https://example.com/report"],
            },
        )

    assert response.status_code == 200
    assert response.json()["pages"][0]["relevance"] == 0.8
    assert service.last_research == {
        "objective": "Research current fitness marketing themes.",
        "seed_urls": ["https://example.com/report"],
    }


def test_remote_ui_bind_requires_explicit_opt_in() -> None:
    active_settings = settings()

    try:
        validate_ui_bind(active_settings, "0.0.0.0")
    except ValueError as exc:
        assert "INSTABOTAI_UI_ALLOW_REMOTE=true" in str(exc)
    else:
        raise AssertionError("remote bind should fail closed")

    allowed = settings(ui_allow_remote=True)
    assert validate_ui_bind(allowed, "0.0.0.0") == "0.0.0.0"
