from instabotai.domain import (
    ActionType,
    ApprovalState,
    PlannedAction,
    UsageSnapshot,
)
from instabotai.policy import AutomationPolicy
from instabotai.settings import Settings


def make_action(**overrides: object) -> PlannedAction:
    data = {
        "action_type": ActionType.PUBLISH_IMAGE,
        "reason": "Approved campaign asset",
        "confidence": 0.95,
        "payload": {"image_url": "https://cdn.example.com/image.jpg"},
        "idempotency_key": "campaign-asset-001",
        "approval": ApprovalState.APPROVED,
    }
    data.update(overrides)
    return PlannedAction.model_validate(data)


def test_policy_requires_human_approval_by_default() -> None:
    settings = Settings(_env_file=None)
    action = make_action(approval=ApprovalState.PENDING)

    decision = AutomationPolicy(settings).evaluate(action, UsageSnapshot())

    assert not decision.allowed
    assert "approval" in decision.reason


def test_policy_enforces_daily_publish_limit() -> None:
    settings = Settings(_env_file=None, daily_publish_limit=1)
    usage = UsageSnapshot(published_today=1)

    decision = AutomationPolicy(settings).evaluate(make_action(), usage)

    assert not decision.allowed
    assert "publish limit" in decision.reason


def test_policy_allows_approved_high_confidence_action_within_limit() -> None:
    settings = Settings(_env_file=None)

    decision = AutomationPolicy(settings).evaluate(make_action(), UsageSnapshot())

    assert decision.allowed
