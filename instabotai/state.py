"""Durable local action ledger for idempotency, audit, and policy usage counters."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from instabotai.domain import ActionType, PlannedAction, UsageSnapshot
from instabotai.storage import ensure_state_schema, open_state_connection


class DuplicateActionError(RuntimeError):
    """Raised when an idempotency key has already been reserved or cannot be replayed."""


class DailyLimitExceededError(RuntimeError):
    """Raised when a transactional daily reservation limit is exhausted."""


class ActionLedgerRecord(BaseModel):
    """Typed read-only projection of one durable action ledger entry."""

    idempotency_key: str
    action_type: ActionType
    target_id: str | None = None
    status: str
    retryable: bool
    reason: str
    confidence: float
    payload: dict[str, Any]
    created_at: datetime
    executed_at: datetime | None = None
    provider_result: Any | None = None
    error: str | None = None


class ActionLedger:
    """SQLite-backed action ledger with transactional quota reservation."""

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        self._memory_connection: sqlite3.Connection | None = None
        if database_path != ":memory:":
            Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        else:
            self._memory_connection = self._new_connection(database_path)
        self._initialize()

    def reserve(self, action: PlannedAction, *, daily_limit: int) -> None:
        """Reserve an action atomically.

        A previously failed reservation may be retried only when the stored immutable action
        identity still matches exactly and the prior failure was explicitly retryable.
        Reserved, succeeded, and ambiguous non-retryable rows remain non-replayable.
        """

        payload = json.dumps(action.payload, sort_keys=True, separators=(",", ":"))
        reserved_at = datetime.now(UTC)
        day_start = self._day_start(reserved_at).isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT action_type, target_id, status, payload_json, retryable
                FROM automation_actions
                WHERE idempotency_key = ?
                """,
                (action.idempotency_key,),
            ).fetchone()

            if existing is not None:
                status = str(existing["status"])
                retryable = bool(existing["retryable"])
                if status != "failed" or not retryable:
                    raise DuplicateActionError(
                        f"action cannot be replayed for idempotency key "
                        f"{action.idempotency_key!r}"
                    )

            count_row = connection.execute(
                """
                SELECT COUNT(*) AS action_count
                FROM automation_actions
                WHERE action_type = ?
                  AND (
                      status IN ('reserved', 'succeeded')
                      OR (status = 'failed' AND retryable = 0)
                  )
                  AND created_at >= ?
                """,
                (action.action_type.value, day_start),
            ).fetchone()
            action_count = int(count_row["action_count"]) if count_row is not None else 0
            if action_count >= daily_limit:
                raise DailyLimitExceededError(
                    f"daily {action.action_type.value} limit reached ({daily_limit})"
                )

            if existing is not None:
                if (
                    str(existing["action_type"]) != action.action_type.value
                    or existing["target_id"] != action.target_id
                    or str(existing["payload_json"]) != payload
                ):
                    raise DuplicateActionError(
                        "failed idempotency key cannot be reused for a different action"
                    )
                connection.execute(
                    """
                    UPDATE automation_actions
                    SET status = 'reserved',
                        retryable = 1,
                        reason = ?,
                        confidence = ?,
                        created_at = ?,
                        executed_at = NULL,
                        provider_result = NULL,
                        error = NULL
                    WHERE idempotency_key = ? AND status = 'failed' AND retryable = 1
                    """,
                    (
                        action.reason,
                        action.confidence,
                        reserved_at.isoformat(),
                        action.idempotency_key,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO automation_actions (
                        idempotency_key,
                        action_type,
                        target_id,
                        status,
                        retryable,
                        reason,
                        confidence,
                        payload_json,
                        created_at
                    ) VALUES (?, ?, ?, 'reserved', 1, ?, ?, ?, ?)
                    """,
                    (
                        action.idempotency_key,
                        action.action_type.value,
                        action.target_id,
                        action.reason,
                        action.confidence,
                        payload,
                        reserved_at.isoformat(),
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)

    def mark_succeeded(self, idempotency_key: str, provider_result: Any) -> None:
        self._finish(
            idempotency_key,
            status="succeeded",
            provider_result=json.dumps(provider_result, sort_keys=True, default=str),
            error=None,
            retryable=False,
        )

    def mark_failed(
        self,
        idempotency_key: str,
        error: str,
        *,
        retryable: bool = True,
    ) -> None:
        self._finish(
            idempotency_key,
            status="failed",
            provider_result=None,
            error=error[:4000],
            retryable=retryable,
        )

    def usage_snapshot(self, now: datetime | None = None) -> UsageSnapshot:
        """Return committed, in-flight, and outcome-ambiguous usage for the UTC day."""

        day_start = self._day_start(now).isoformat()
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT action_type, COUNT(*) AS action_count
                FROM automation_actions
                WHERE (
                    status IN ('reserved', 'succeeded')
                    OR (status = 'failed' AND retryable = 0)
                )
                  AND created_at >= ?
                GROUP BY action_type
                """,
                (day_start,),
            ).fetchall()
        finally:
            self._release(connection)

        counts = {str(row["action_type"]): int(row["action_count"]) for row in rows}
        return UsageSnapshot(
            published_today=counts.get(ActionType.PUBLISH_IMAGE.value, 0),
            comment_replies_today=counts.get(ActionType.REPLY_TO_COMMENT.value, 0),
            comments_moderated_today=counts.get(ActionType.HIDE_COMMENT.value, 0),
        )

    def get_record(self, idempotency_key: str) -> ActionLedgerRecord | None:
        """Return the complete audit projection for one idempotency key."""

        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT idempotency_key, action_type, target_id, status, retryable,
                       reason, confidence, payload_json, created_at, executed_at,
                       provider_result, error
                FROM automation_actions
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
        finally:
            self._release(connection)
        if row is None:
            return None

        provider_result: Any | None = None
        raw_provider_result = row["provider_result"]
        if raw_provider_result is not None:
            try:
                provider_result = json.loads(str(raw_provider_result))
            except json.JSONDecodeError:
                provider_result = str(raw_provider_result)

        raw_payload = json.loads(str(row["payload_json"]))
        if not isinstance(raw_payload, dict):
            raise RuntimeError("action ledger payload is not a JSON object")

        return ActionLedgerRecord(
            idempotency_key=str(row["idempotency_key"]),
            action_type=ActionType(str(row["action_type"])),
            target_id=str(row["target_id"]) if row["target_id"] is not None else None,
            status=str(row["status"]),
            retryable=bool(row["retryable"]),
            reason=str(row["reason"]),
            confidence=float(row["confidence"]),
            payload={str(key): value for key, value in raw_payload.items()},
            created_at=datetime.fromisoformat(str(row["created_at"])),
            executed_at=(
                datetime.fromisoformat(str(row["executed_at"]))
                if row["executed_at"] is not None
                else None
            ),
            provider_result=provider_result,
            error=str(row["error"]) if row["error"] is not None else None,
        )

    def status(self, idempotency_key: str) -> str | None:
        record = self.get_record(idempotency_key)
        return record.status if record is not None else None

    def close(self) -> None:
        if self._memory_connection is not None:
            self._memory_connection.close()
            self._memory_connection = None

    def _finish(
        self,
        idempotency_key: str,
        *,
        status: str,
        provider_result: str | None,
        error: str | None,
        retryable: bool,
    ) -> None:
        executed_at = datetime.now(UTC).isoformat()
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE automation_actions
                SET status = ?, retryable = ?, provider_result = ?, error = ?, executed_at = ?
                WHERE idempotency_key = ?
                  AND status = 'reserved'
                """,
                (
                    status,
                    1 if retryable else 0,
                    provider_result,
                    error,
                    executed_at,
                    idempotency_key,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"cannot transition action {idempotency_key!r} from reserved to {status}"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            ensure_state_schema(connection, self._database_path)
        finally:
            self._release(connection)

    def _connect(self) -> sqlite3.Connection:
        if self._database_path == ":memory:":
            if self._memory_connection is None:
                raise RuntimeError("in-memory action ledger is closed")
            return self._memory_connection
        return self._new_connection(self._database_path)

    @staticmethod
    def _new_connection(database_path: str) -> sqlite3.Connection:
        return open_state_connection(database_path)

    def _release(self, connection: sqlite3.Connection) -> None:
        if self._database_path != ":memory:":
            connection.close()

    @staticmethod
    def _day_start(now: datetime | None = None) -> datetime:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return current.astimezone(UTC).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
