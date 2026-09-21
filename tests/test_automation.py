from pathlib import Path

import pytest

from instabotai.automation import AutomationService
from instabotai.domain import ActionType, ApprovalState, PlannedAction
from instabotai.policy import AutomationPolicy
from instabotai.settings import Settings
from instabotai.state import ActionLedger, DuplicateActionError


class FakeProvider:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish_image(self, image_url: str, caption: str = "") -> str:
        self.published.append((image_url, caption))
        return "media-123"

    async def reply_to_comment(self, comment_id: str, message: str) -> str:
        return f"reply-{comment_id}-{message}"

    async def hide_comment(self, comment_id: str, *, hide: bool = True) -> bool:
        return bool(comment_id and hide)


def action(key: str = "campaign-post-001") -> PlannedAction:
    return PlannedAction(
        action_type=ActionType.PUBLISH_IMAGE,
        reason="Approved campaign asset",
        confidence=0.96,
        payload={
            "image_url": "https://cdn.example.com/launch.jpg",
            "caption": "Launch day",
        },
        idempotency_key=key,
        approval=ApprovalState.APPROVED,
    )


async def test_executor_records_success_and_updates_usage(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    ledger = ActionLedger(str(tmp_path / "state.sqlite3"))
    provider = FakeProvider()
    service = AutomationService(AutomationPolicy(settings), ledger, provider)

    result = await service.execute(action())

    assert result == "media-123"
    assert ledger.status("campaign-post-001") == "succeeded"
    assert ledger.usage_snapshot().published_today == 1
    assert provider.published == [
        ("https://cdn.example.com/launch.jpg", "Launch day")
    ]


async def test_executor_is_idempotent(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    ledger = ActionLedger(str(tmp_path / "state.sqlite3"))
    service = AutomationService(AutomationPolicy(settings), ledger, FakeProvider())
    planned = action()

    await service.execute(planned)

    with pytest.raises(DuplicateActionError):
        await service.execute(planned)


async def test_executor_fails_before_provider_when_approval_missing(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    ledger = ActionLedger(str(tmp_path / "state.sqlite3"))
    provider = FakeProvider()
    service = AutomationService(AutomationPolicy(settings), ledger, provider)
    planned = action().model_copy(update={"approval": ApprovalState.PENDING})

    with pytest.raises(RuntimeError, match="approval"):
        await service.execute(planned)

    assert provider.published == []
    assert ledger.status(planned.idempotency_key) is None
