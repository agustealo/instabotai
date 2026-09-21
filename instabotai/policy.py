"""Fail-closed write policy for Instagram automation."""

from __future__ import annotations

from dataclasses import dataclass

from instabotai.domain import ActionType, ApprovalState, PlannedAction, UsageSnapshot
from instabotai.settings import Settings


class PolicyViolation(RuntimeError):
    """Raised when a write action violates runtime policy."""


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str


class AutomationPolicy:
    """Enforce supported actions, approvals, confidence, and daily limits."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, action: PlannedAction, usage: UsageSnapshot) -> PolicyDecision:
        if action.confidence < self._settings.write_confidence_threshold:
            return PolicyDecision(
                False,
                f"confidence {action.confidence:.2f} is below "
                f"{self._settings.write_confidence_threshold:.2f}",
            )

        if self._settings.require_write_approval and action.approval is not ApprovalState.APPROVED:
            return PolicyDecision(False, "human approval is required")

        limit_decision = self._check_limit(action.action_type, usage)
        if not limit_decision.allowed:
            return limit_decision

        return PolicyDecision(True, "allowed")

    def require_allowed(self, action: PlannedAction, usage: UsageSnapshot) -> None:
        decision = self.evaluate(action, usage)
        if not decision.allowed:
            raise PolicyViolation(decision.reason)

    def _check_limit(self, action_type: ActionType, usage: UsageSnapshot) -> PolicyDecision:
        if action_type is ActionType.PUBLISH_IMAGE:
            allowed = usage.published_today < self._settings.daily_publish_limit
            return PolicyDecision(allowed, "daily publish limit reached" if not allowed else "allowed")

        if action_type is ActionType.REPLY_TO_COMMENT:
            allowed = usage.comment_replies_today < self._settings.daily_comment_reply_limit
            return PolicyDecision(
                allowed,
                "daily comment reply limit reached" if not allowed else "allowed",
            )

        if action_type is ActionType.HIDE_COMMENT:
            allowed = usage.comments_moderated_today < self._settings.daily_comment_moderation_limit
            return PolicyDecision(
                allowed,
                "daily comment moderation limit reached" if not allowed else "allowed",
            )

        return PolicyDecision(False, f"unsupported action: {action_type}")
