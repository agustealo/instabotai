"""Evidence-grounded, outcome-aware AI decision engine."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from instabotai.domain import ActionType, ApprovalState, PlannedAction
from instabotai.intelligence.domain import (
    DecisionCandidate,
    DecisionReview,
    EvidenceItem,
    IntelligenceDecision,
    ModelDecision,
)
from instabotai.intelligence.memory import ExperienceStore
from instabotai.intelligence.providers import (
    IntelligenceProviderError,
    JSONReasoningModel,
    build_reasoning_model,
    parse_json_object,
)
from instabotai.settings import Settings

_ModelType = TypeVar("_ModelType", bound=BaseModel)

_PLANNER_SYSTEM = """You are the decision-planning component of a production AI system.
Reason only from the supplied objective, context, evidence, allowed actions, and constraints.
Do not invent observations, identifiers, metrics, account facts, or provider capabilities.
Every proposed action must be one of ALLOWED_ACTIONS and should cite supporting EVIDENCE_IDS.
Treat lack of evidence as uncertainty. Returning zero candidates is correct when action is not justified.
Never weaken approval, quota, platform, security, or execution policy. Those controls are external authority.
Return exactly one JSON object and no prose outside it.
"""

_CRITIC_SYSTEM = """You are an independent critic in a production AI decision system.
Audit the proposed candidate against the supplied objective and evidence.
Look for unsupported claims, missing evidence, excessive risk, target ambiguity, and weak causal reasoning.
Do not optimize for agreeing with the planner. Recommend abstention when evidence is inadequate.
External policy and approval controls are authoritative and cannot be waived.
Return exactly one JSON object and no prose outside it.
"""


class IntelligenceEngine:
    """Generate, critique, score, and learn from model-assisted decisions."""

    def __init__(
        self,
        settings: Settings,
        model: JSONReasoningModel,
        experience: ExperienceStore,
    ) -> None:
        self._settings = settings
        self._model = model
        self._experience = experience

    async def reason(
        self,
        *,
        objective: str,
        evidence: list[EvidenceItem],
        allowed_actions: tuple[str, ...],
        context: dict[str, Any] | None = None,
        constraints: tuple[str, ...] = (),
    ) -> IntelligenceDecision:
        """Return a fail-closed decision from model generation plus deterministic scoring."""

        normalized_objective = objective.strip()
        if not normalized_objective:
            raise ValueError("objective must not be empty")
        normalized_actions = tuple(
            dict.fromkeys(action.strip() for action in allowed_actions if action.strip())
        )
        if not normalized_actions:
            raise ValueError("allowed_actions must contain at least one action")

        planner_payload = {
            "objective": normalized_objective,
            "context": context or {},
            "constraints": constraints,
            "allowed_actions": normalized_actions,
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "response_schema": {
                "candidates": [
                    {
                        "candidate_id": "string",
                        "action": "one allowed action",
                        "rationale": "evidence-grounded rationale",
                        "confidence": "number 0..1",
                        "expected_utility": "number 0..1",
                        "risk": "number 0..1",
                        "payload": "object",
                        "target_id": "string or null",
                        "evidence_refs": ["evidence_id"],
                    }
                ],
                "assumptions": ["string"],
                "uncertainty": "string",
            },
        }

        try:
            planner, provider, model = await self._validated_model_call(
                model_type=ModelDecision,
                system_prompt=_PLANNER_SYSTEM,
                payload=planner_payload,
            )
        except (IntelligenceProviderError, ValidationError, ValueError) as exc:
            return self._abstention(
                objective=normalized_objective,
                explanation=f"AI planning failed closed: {exc}",
            )

        eligible = [candidate for candidate in planner.candidates if candidate.action in normalized_actions]
        if not eligible:
            return IntelligenceDecision(
                objective=normalized_objective,
                assumptions=planner.assumptions,
                uncertainty=planner.uncertainty,
                explanation="The reasoning model produced no eligible action supported by the allowed action set.",
                abstained=True,
                provider=provider,
                model=model,
            )

        evidence_by_id = {item.evidence_id: item for item in evidence}
        scored = [
            (
                self._candidate_score(
                    objective=normalized_objective,
                    candidate=candidate,
                    evidence_by_id=evidence_by_id,
                ),
                candidate,
            )
            for candidate in eligible
        ]
        scored.sort(key=lambda item: (item[0], item[1].confidence), reverse=True)
        base_score, selected = scored[0]

        review: DecisionReview | None = None
        final_score = base_score
        if self._settings.ai_enable_critic:
            critic_payload = {
                "objective": normalized_objective,
                "candidate": selected.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in evidence],
                "response_schema": {
                    "support_score": "number 0..1",
                    "risk_score": "number 0..1",
                    "should_abstain": "boolean",
                    "missing_evidence": ["string"],
                    "objections": ["string"],
                },
            }
            try:
                review, _, _ = await self._validated_model_call(
                    model_type=DecisionReview,
                    system_prompt=_CRITIC_SYSTEM,
                    payload=critic_payload,
                )
            except (IntelligenceProviderError, ValidationError, ValueError) as exc:
                return self._abstention(
                    objective=normalized_objective,
                    explanation=f"AI critic failed closed: {exc}",
                    provider=provider,
                    model=model,
                    assumptions=planner.assumptions,
                    uncertainty=planner.uncertainty,
                )
            final_score = self._reviewed_score(base_score, review)
            if review.should_abstain:
                return IntelligenceDecision(
                    objective=normalized_objective,
                    selected=selected,
                    score=final_score,
                    review=review,
                    assumptions=planner.assumptions,
                    uncertainty=planner.uncertainty,
                    explanation="Independent critique found insufficient support or unacceptable uncertainty.",
                    abstained=True,
                    provider=provider,
                    model=model,
                )

        if final_score < self._settings.ai_min_decision_score:
            return IntelligenceDecision(
                objective=normalized_objective,
                selected=selected,
                score=final_score,
                review=review,
                assumptions=planner.assumptions,
                uncertainty=planner.uncertainty,
                explanation=(
                    f"Best candidate score {final_score:.3f} is below the configured "
                    f"decision threshold {self._settings.ai_min_decision_score:.3f}."
                ),
                abstained=True,
                provider=provider,
                model=model,
            )

        return IntelligenceDecision(
            objective=normalized_objective,
            selected=selected,
            score=final_score,
            review=review,
            assumptions=planner.assumptions,
            uncertainty=planner.uncertainty,
            explanation="Candidate passed evidence, experience, risk, and critic scoring.",
            abstained=False,
            provider=provider,
            model=model,
        )

    async def plan_instagram_action(
        self,
        *,
        objective: str,
        evidence: list[EvidenceItem],
        context: dict[str, Any] | None = None,
        constraints: tuple[str, ...] = (),
    ) -> tuple[IntelligenceDecision, PlannedAction | None]:
        """Reason over the current Instagram action vocabulary and build a pending action."""

        allowed = tuple(action.value for action in ActionType)
        decision = await self.reason(
            objective=objective,
            evidence=evidence,
            allowed_actions=allowed,
            context=context,
            constraints=constraints,
        )
        if decision.abstained or decision.selected is None:
            return decision, None

        candidate = decision.selected
        action_type = ActionType(candidate.action)
        payload_json = json.dumps(
            candidate.payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        key_material = "|".join(
            [
                objective.strip(),
                candidate.candidate_id,
                action_type.value,
                candidate.target_id or "",
                payload_json,
            ]
        )
        digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:32]
        action = PlannedAction(
            action_type=action_type,
            reason=candidate.rationale[:1000],
            confidence=min(candidate.confidence, decision.score),
            payload=candidate.payload,
            target_id=candidate.target_id,
            idempotency_key=f"ai-{digest}",
            approval=ApprovalState.PENDING,
        )
        return decision, action

    def record_outcome(
        self,
        decision: IntelligenceDecision,
        *,
        reward: float,
        note: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Feed a real observed outcome back into durable decision memory."""

        if decision.selected is None:
            raise ValueError("cannot record an outcome for a decision without a selected candidate")
        self._experience.record(
            objective=decision.objective,
            action=decision.selected.action,
            reward=reward,
            note=note,
            metadata=metadata,
        )

    async def aclose(self) -> None:
        """Release model transport and durable-memory resources."""

        self._experience.close()
        closer = getattr(self._model, "aclose", None)
        if closer is not None:
            await closer()

    async def _validated_model_call(
        self,
        *,
        model_type: type[_ModelType],
        system_prompt: str,
        payload: dict[str, Any],
    ) -> tuple[_ModelType, str, str]:
        user_prompt = self._bounded_payload(payload)
        last_error: Exception | None = None
        for attempt in range(self._settings.ai_max_retries + 1):
            try:
                reply = await self._model.complete(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
                parsed = parse_json_object(reply.text)
                return model_type.model_validate(parsed), reply.provider, reply.model
            except (IntelligenceProviderError, ValidationError) as exc:
                last_error = exc
                if attempt < self._settings.ai_max_retries:
                    await asyncio.sleep(min(2**attempt, 4))
        if isinstance(last_error, ValidationError):
            raise last_error
        raise IntelligenceProviderError(f"reasoning model failed after retries: {last_error}")

    def _candidate_score(
        self,
        *,
        objective: str,
        candidate: DecisionCandidate,
        evidence_by_id: dict[str, EvidenceItem],
    ) -> float:
        referenced = [
            evidence_by_id[ref] for ref in candidate.evidence_refs if ref in evidence_by_id
        ]
        if candidate.evidence_refs:
            reference_coverage = len(referenced) / len(candidate.evidence_refs)
        else:
            reference_coverage = 0.0
        evidence_quality = (
            sum(item.confidence for item in referenced) / len(referenced) if referenced else 0.0
        )
        evidence_support = reference_coverage * evidence_quality

        history = self._experience.summarize(objective=objective, action=candidate.action)
        history_value = 0.5 + ((history.mean_reward - 0.5) * history.relevance)

        score = (
            (candidate.expected_utility * 0.30)
            + (candidate.confidence * 0.25)
            + (evidence_support * 0.20)
            + (history_value * 0.15)
            + ((1.0 - candidate.risk) * 0.10)
        )
        return self._clamp(score)

    @classmethod
    def _reviewed_score(cls, base_score: float, review: DecisionReview) -> float:
        score = (
            (base_score * 0.75)
            + (review.support_score * 0.15)
            + ((1.0 - review.risk_score) * 0.10)
        )
        return cls._clamp(score)

    def _bounded_payload(self, payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, sort_keys=True, default=str)
        if len(serialized) <= self._settings.ai_max_context_chars:
            return serialized

        reduced = dict(payload)
        raw_evidence = reduced.get("evidence")
        if isinstance(raw_evidence, list):
            evidence = [item for item in raw_evidence if isinstance(item, dict)]
            evidence.sort(
                key=lambda item: float(item.get("confidence", 0.0))
                if isinstance(item.get("confidence"), int | float)
                else 0.0,
                reverse=True,
            )
            kept: list[dict[str, Any]] = []
            for item in evidence:
                candidate = dict(reduced)
                candidate["evidence"] = [*kept, item]
                candidate_json = json.dumps(candidate, sort_keys=True, default=str)
                if len(candidate_json) > self._settings.ai_max_context_chars:
                    continue
                kept.append(item)
            reduced["evidence"] = kept
            serialized = json.dumps(reduced, sort_keys=True, default=str)
            if len(serialized) <= self._settings.ai_max_context_chars:
                return serialized

        reduced["context"] = {"omitted": "context exceeded configured AI boundary"}
        serialized = json.dumps(reduced, sort_keys=True, default=str)
        if len(serialized) <= self._settings.ai_max_context_chars:
            return serialized
        raise ValueError("AI request exceeds configured context boundary after safe reduction")

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _abstention(
        *,
        objective: str,
        explanation: str,
        provider: str | None = None,
        model: str | None = None,
        assumptions: tuple[str, ...] = (),
        uncertainty: str = "",
    ) -> IntelligenceDecision:
        return IntelligenceDecision(
            objective=objective,
            explanation=explanation,
            abstained=True,
            provider=provider,
            model=model,
            assumptions=assumptions,
            uncertainty=uncertainty,
        )


def build_intelligence_engine(settings: Settings) -> IntelligenceEngine:
    """Build the canonical intelligence runtime from process configuration."""

    return IntelligenceEngine(
        settings=settings,
        model=build_reasoning_model(settings),
        experience=ExperienceStore(settings.state_db_path),
    )
