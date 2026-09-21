"""Durable local action ledger for idempotency, audit, and policy usage counters."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from instabotai.domain import ActionType, PlannedAction, UsageSnapshot


class DuplicateActionError(RuntimeError):
    """Raised when an idempotency key has already been reserved."""


class ActionLedger:
    """SQLite-backed action ledger.

    SQLite is intentionally the default single-node persistence layer for the
    revival runtime. It keeps policy counters and idempotency durable without
    adding a service dependency. A server deployment can later implement the
    same repository contract on PostgreSQL.
    """

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        if database_path != ":memory:":
            Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def reserve(self, action: PlannedAction) -> None:
        payload = json.dumps(action.payload, sort_keys=True, separators=(",", ":"))
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO automation_actions (
                        idempotency_key,
                        action_type,
                        target_id,
                        status,
                        reason,
                        confidence,
                        payload_json,
                        created_at
                    ) VALUES (?, ?, ?, 'reserved', ?, ?, ?, ?)
                    """,
                    (
                        action.idempotency_key,
                        action.action_type.value,
                        action.target_id,
                        action.reason,
                        action.confidence,
                        payload,
                        action.created_at.astimezone(UTC).isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateActionError(
                f"action already exists for idempotency key {action.idempotency_key!r}"
            ) from exc

    def mark_succeeded(self, idempotency_key: str, provider_result: Any) -> None:
        self._finish(
            idempotency_key,
            status="succeeded",
            provider_result=json.dumps(provider_result, sort_keys=True, default=str),
            error=None,
        )

    def mark_failed(self, idempotency_key: str, error: str) -> None:
        self._finish(
            idempotency_key,
            status="failed",
            provider_result=None,
            error=error[:4000],
        )

    def usage_snapshot(self, now: datetime | None = None) -> UsageSnapshot:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        day_start = current.astimezone(UTC).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ).isoformat()

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT action_type, COUNT(*) AS action_count
                FROM automation_actions
                WHERE status = 'succeeded'
                  AND executed_at >= ?
                GROUP BY action_type
                """,
                (day_start,),
            ).fetchall()

        counts = {str(row["action_type"]): int(row["action_count"]) for row in rows}
        return UsageSnapshot(
            published_today=counts.get(ActionType.PUBLISH_IMAGE.value, 0),
            comment_replies_today=counts.get(ActionType.REPLY_TO_COMMENT.value, 0),
            comments_moderated_today=counts.get(ActionType.HIDE_COMMENT.value, 0),
        )

    def status(self, idempotency_key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM automation_actions WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return str(row["status"]) if row is not None else None

    def _finish(
        self,
        idempotency_key: str,
        *,
        status: str,
        provider_result: str | None,
        error: str | None,
    ) -> None:
        executed_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE automation_actions
                SET status = ?, provider_result = ?, error = ?, executed_at = ?
                WHERE idempotency_key = ?
                  AND status = 'reserved'
                """,
                (status, provider_result, error, executed_at, idempotency_key),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"cannot transition action {idempotency_key!r} from reserved to {status}"
                )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS automation_actions (
                    idempotency_key TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    target_id TEXT,
                    status TEXT NOT NULL CHECK (
                        status IN ('reserved', 'succeeded', 'failed')
                    ),
                    reason TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    executed_at TEXT,
                    provider_result TEXT,
                    error TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_automation_actions_usage
                ON automation_actions (status, executed_at, action_type)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if self._database_path != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
        return connection
