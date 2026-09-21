"""Canonical policy-governed write execution path."""

from __future__ import annotations

from typing import Any, Protocol

from instabotai.domain import ActionType, PlannedAction
from instabotai.policy import AutomationPolicy
from instabotai.state import ActionLedger


class InstagramWriter(Protocol):
    async def publish_image(self, image_url: str, caption: str = "") -> str:
        """Publish a single image and return the Instagram media id."""

    async def reply_to_comment(self, comment_id: str, message: str) -> str:
        """Reply to a comment and return the reply id."""

    async def hide_comment(self, comment_id: str, *, hide: bool = True) -> bool:
        """Hide or unhide an owned-media comment."""


class AutomationService:
    """Only supported write path for the modern runtime.

    Every action is checked against policy, reserved durably by idempotency
    key, executed through the official provider, and recorded as succeeded
    or failed.
    """

    def __init__(
        self,
        policy: AutomationPolicy,
        ledger: ActionLedger,
        provider: InstagramWriter,
    ) -> None:
        self._policy = policy
        self._ledger = ledger
        self._provider = provider

    async def execute(self, action: PlannedAction) -> Any:
        usage = self._ledger.usage_snapshot()
        self._policy.require_allowed(action, usage)
        self._ledger.reserve(action)

        try:
            result = await self._dispatch(action)
        except Exception as exc:
            self._ledger.mark_failed(action.idempotency_key, str(exc))
            raise

        self._ledger.mark_succeeded(action.idempotency_key, result)
        return result

    async def _dispatch(self, action: PlannedAction) -> Any:
        if action.action_type is ActionType.PUBLISH_IMAGE:
            image_url = self._required_text(action, "image_url")
            caption = self._optional_text(action, "caption")
            return await self._provider.publish_image(image_url, caption)

        if action.action_type is ActionType.REPLY_TO_COMMENT:
            target_id = self._required_target(action)
            message = self._required_text(action, "message")
            return await self._provider.reply_to_comment(target_id, message)

        if action.action_type is ActionType.HIDE_COMMENT:
            target_id = self._required_target(action)
            hide = action.payload.get("hide", True)
            if not isinstance(hide, bool):
                raise ValueError("payload.hide must be a boolean")
            return await self._provider.hide_comment(target_id, hide=hide)

        raise ValueError(f"unsupported action: {action.action_type}")

    @staticmethod
    def _required_target(action: PlannedAction) -> str:
        target = (action.target_id or "").strip()
        if not target:
            raise ValueError(f"{action.action_type.value} requires target_id")
        return target

    @staticmethod
    def _required_text(action: PlannedAction, key: str) -> str:
        value = action.payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"payload.{key} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _optional_text(action: PlannedAction, key: str) -> str:
        value = action.payload.get(key, "")
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError(f"payload.{key} must be a string")
        return value.strip()
