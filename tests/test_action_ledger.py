from datetime import UTC, datetime, timedelta

import pytest

from instabotai.domain import ActionType, ApprovalState, PlannedAction
from instabotai.state import ActionLedger, DailyLimitExceededError


def planned(key: str, *, created_at: datetime | None = None) -> PlannedAction:
    return PlannedAction(
        action_type=ActionType.PUBLISH_IMAGE,
        reason="Quota test",
        confidence=0.95,
        payload={"image_url": "https://cdn.example.com/test.jpg"},
        idempotency_key=key,
        approval=ApprovalState.APPROVED,
        created_at=created_at or datetime.now(UTC),
    )


def test_in_memory_ledger_persists_across_operations() -> None:
    ledger = ActionLedger(":memory:")
    ledger.reserve(planned("memory-key-001"), daily_limit=2)
    assert ledger.status("memory-key-001") == "reserved"
    assert ledger.usage_snapshot().published_today == 1
    ledger.close()


def test_reservation_enforces_daily_limit_transactionally() -> None:
    ledger = ActionLedger(":memory:")
    ledger.reserve(planned("quota-key-001"), daily_limit=1)

    with pytest.raises(DailyLimitExceededError, match="limit reached"):
        ledger.reserve(planned("quota-key-002"), daily_limit=1)

    assert ledger.status("quota-key-002") is None
    ledger.close()


def test_client_cannot_backdate_action_to_bypass_daily_limit() -> None:
    ledger = ActionLedger(":memory:")
    old_timestamp = datetime.now(UTC) - timedelta(days=30)
    ledger.reserve(
        planned("backdated-key-001", created_at=old_timestamp),
        daily_limit=1,
    )

    assert ledger.usage_snapshot().published_today == 1
    with pytest.raises(DailyLimitExceededError, match="limit reached"):
        ledger.reserve(planned("backdated-key-002"), daily_limit=1)
    ledger.close()
