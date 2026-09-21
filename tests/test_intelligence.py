import json

from instabotai.domain import ApprovalState
from instabotai.intelligence import (
    DecisionJournal,
    EvidenceItem,
    ExperienceStore,
    IntelligenceEngine,
    ModelReply,
)
from instabotai.settings import Settings


class ScriptedReasoningModel:
    provider_name = "scripted-test-provider"
    model_name = "scripted-test-model"

    def __init__(self, replies: list[dict[str, object] | str]) -> None:
        self._replies = list(replies)

    async def complete(self, *, system_prompt: str, user_prompt: str) -> ModelReply:
        assert system_prompt
        assert user_prompt
        if not self._replies:
            raise RuntimeError("test reasoning script exhausted")
        value = self._replies.pop(0)
        text = value if isinstance(value, str) else json.dumps(value)
        return ModelReply(
            text=text,
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=1,
        )


def planner_candidate(
    *,
    action: str = "publish_image",
    candidate_id: str = "candidate-1",
) -> dict[str, object]:
    return {
        "candidates": [
            {
                "candidate_id": candidate_id,
                "action": action,
                "rationale": "Evidence supports this bounded action.",
                "confidence": 0.9,
                "expected_utility": 0.9,
                "risk": 0.1,
                "payload": {
                    "image_url": "https://cdn.example.com/product.jpg",
                    "caption": "Product update",
                },
                "target_id": None,
                "evidence_refs": ["evidence-1"],
            }
        ],
        "assumptions": [],
        "uncertainty": "",
    }


def supportive_review(*, abstain: bool = False) -> dict[str, object]:
    return {
        "support_score": 0.9,
        "risk_score": 0.1,
        "should_abstain": abstain,
        "missing_evidence": [],
        "objections": [],
    }


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "ai_max_retries": 0,
        "ai_min_decision_score": 0.5,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def evidence() -> list[EvidenceItem]:
    return [
        EvidenceItem(
            evidence_id="evidence-1",
            source="campaign analytics",
            content="The product announcement is approved and ready for publication.",
            confidence=1.0,
        )
    ]


async def test_ai_planner_builds_pending_policy_governed_action() -> None:
    engine = IntelligenceEngine(
        settings=settings(),
        model=ScriptedReasoningModel([planner_candidate(), supportive_review()]),
        experience=ExperienceStore(":memory:"),
    )

    decision, action = await engine.plan_instagram_action(
        objective="Publish the approved product announcement.",
        evidence=evidence(),
    )

    assert decision.abstained is False
    assert decision.score >= 0.5
    assert action is not None
    assert action.approval is ApprovalState.PENDING
    assert action.idempotency_key.startswith("ai-")
    assert action.payload["caption"] == "Product update"


async def test_ai_decision_is_journaled_with_stable_identity() -> None:
    journal = DecisionJournal(":memory:")
    engine = IntelligenceEngine(
        settings=settings(),
        model=ScriptedReasoningModel([planner_candidate(), supportive_review()]),
        experience=ExperienceStore(":memory:"),
        journal=journal,
    )

    decision = await engine.reason(
        objective="Publish only from reviewed evidence.",
        evidence=evidence(),
        allowed_actions=("publish_image",),
    )

    stored = journal.get(decision.decision_id)
    assert stored is not None
    assert stored.decision_id == decision.decision_id
    assert stored.model_dump(mode="json") == decision.model_dump(mode="json")
    assert journal.recent(1)[0].decision_id == decision.decision_id


async def test_ai_cannot_escape_caller_allowed_action_vocabulary() -> None:
    engine = IntelligenceEngine(
        settings=settings(),
        model=ScriptedReasoningModel([planner_candidate(action="delete_account")]),
        experience=ExperienceStore(":memory:"),
    )

    decision = await engine.reason(
        objective="Choose a safe action.",
        evidence=evidence(),
        allowed_actions=("publish_image",),
    )

    assert decision.abstained is True
    assert decision.selected is None


async def test_independent_critic_can_force_abstention() -> None:
    engine = IntelligenceEngine(
        settings=settings(),
        model=ScriptedReasoningModel([planner_candidate(), supportive_review(abstain=True)]),
        experience=ExperienceStore(":memory:"),
    )

    decision, action = await engine.plan_instagram_action(
        objective="Publish only if evidence is adequate.",
        evidence=evidence(),
    )

    assert decision.abstained is True
    assert decision.selected is not None
    assert action is None


async def test_real_outcomes_change_future_decision_score() -> None:
    store = ExperienceStore(":memory:")
    engine = IntelligenceEngine(
        settings=settings(ai_enable_critic=False, ai_min_decision_score=0.0),
        model=ScriptedReasoningModel(
            [
                planner_candidate(candidate_id="candidate-before"),
                planner_candidate(candidate_id="candidate-after"),
            ]
        ),
        experience=store,
    )
    objective = "Publish the approved product announcement."

    before = await engine.reason(
        objective=objective,
        evidence=evidence(),
        allowed_actions=("publish_image",),
    )
    engine.record_outcome(before, reward=1.0, note="Observed campaign objective achieved.")
    after = await engine.reason(
        objective=objective,
        evidence=evidence(),
        allowed_actions=("publish_image",),
    )

    assert before.abstained is False
    assert after.abstained is False
    assert after.score > before.score


async def test_malformed_model_output_fails_closed() -> None:
    engine = IntelligenceEngine(
        settings=settings(),
        model=ScriptedReasoningModel(["this is not JSON"]),
        experience=ExperienceStore(":memory:"),
    )

    decision = await engine.reason(
        objective="Do not act without a valid model decision.",
        evidence=evidence(),
        allowed_actions=("publish_image",),
    )

    assert decision.abstained is True
    assert decision.selected is None
    assert "failed closed" in decision.explanation
