"""Durable audit journal for every finalized AI decision."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from instabotai.intelligence.domain import IntelligenceDecision


class DecisionJournal:
    """SQLite-backed immutable audit log for AI decisions and abstentions."""

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        self._memory_connection: sqlite3.Connection | None = None
        if database_path == ":memory:":
            self._memory_connection = self._new_connection(database_path)
        else:
            Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def record(self, decision: IntelligenceDecision) -> None:
        """Persist one finalized decision exactly once."""

        selected_action = decision.selected.action if decision.selected is not None else None
        payload = decision.model_dump(mode="json")
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO ai_decisions (
                    decision_id,
                    objective,
                    selected_action,
                    score,
                    abstained,
                    provider,
                    model,
                    decision_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.objective,
                    selected_action,
                    decision.score,
                    int(decision.abstained),
                    decision.provider,
                    decision.model,
                    json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str),
                    decision.created_at.isoformat(),
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RuntimeError(
                f"AI decision {decision.decision_id!r} is already journaled"
            ) from exc
        finally:
            self._release(connection)

    def get(self, decision_id: str) -> IntelligenceDecision | None:
        """Load one previously journaled decision by stable decision ID."""

        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT decision_json FROM ai_decisions WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        finally:
            self._release(connection)
        if row is None:
            return None
        return IntelligenceDecision.model_validate_json(str(row["decision_json"]))

    def recent(self, limit: int = 50) -> tuple[IntelligenceDecision, ...]:
        """Return the newest bounded set of decisions for audit/operations surfaces."""

        bounded_limit = max(1, min(limit, 500))
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT decision_json
                FROM ai_decisions
                ORDER BY created_at DESC, decision_id DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        finally:
            self._release(connection)
        return tuple(
            IntelligenceDecision.model_validate_json(str(row["decision_json"])) for row in rows
        )

    def close(self) -> None:
        if self._memory_connection is not None:
            self._memory_connection.close()
            self._memory_connection = None

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_decisions (
                    decision_id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    selected_action TEXT,
                    score REAL NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
                    abstained INTEGER NOT NULL CHECK (abstained IN (0, 1)),
                    provider TEXT,
                    model TEXT,
                    decision_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ai_decisions_created_at
                ON ai_decisions (created_at DESC)
                """
            )
            connection.commit()
        finally:
            self._release(connection)

    def _connect(self) -> sqlite3.Connection:
        if self._database_path == ":memory:":
            if self._memory_connection is None:
                raise RuntimeError("in-memory decision journal is closed")
            return self._memory_connection
        return self._new_connection(self._database_path)

    @staticmethod
    def _new_connection(database_path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        if database_path != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _release(self, connection: sqlite3.Connection) -> None:
        if self._database_path != ":memory:":
            connection.close()
