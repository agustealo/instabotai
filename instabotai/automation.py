"""Canonical policy-governed write execution path."""

from __future__ import annotations

from typing import Any, Protocol

from instabotai.domain import ActionType, PlannedAction
from instabotai.policy import AutomationPolicy, PolicyViolation
from instabotai.state import ActionLedger, DailyLimitExceededError


class InstagramWriter(Protocol):
    async def publish_image(self, image_url: str, caption: str = "") -> str:
        """Publish a single image and return the Instagram media id."""

    async def reply_to_comment(
        self,
        comment_id: str,
        message: str,
        *,
        media_id: str | None = None,
    ) -> str:
        """Reply to a comment and return the reply id."""

    async def hide_comment(self, comment_id: str, *, hide: bool = True) -> bool:
        """Hide or unhide an owned-media comment."""


class AutomationService:
    """Only supported write path for the modern runtime."""

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
        self._policy.require_preconditions(action)
        try:
            self._ledger.reserve(
                action,
                daily_limit=self._policy.daily_limit(action.action_type),
            )
        except DailyLimitExceededError as exc:
            raise PolicyViolation(str(exc)) from exc

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
            media_id = self._optional_text(action, "media_id") or None
            return await self._provider.reply_to_comment(
                target_id,
                message,
                media_id=media_id,
            )

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
