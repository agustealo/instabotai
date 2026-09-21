"""Durable experience memory for outcome-aware decision scoring."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from instabotai.intelligence.domain import ExperienceSummary
from instabotai.storage import ensure_state_schema, open_state_connection

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]{1,}", re.IGNORECASE)


class ExperienceStore:
    """SQLite-backed outcome memory with lightweight relevance weighting."""

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        self._memory_connection: sqlite3.Connection | None = None
        if database_path == ":memory:":
            self._memory_connection = self._new_connection(database_path)
        else:
            Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def record(
        self,
        *,
        objective: str,
        action: str,
        reward: float,
        note: str = "",
        metadata: dict[str, Any] | None = None,
        source_key: str | None = None,
    ) -> None:
        """Persist one observed result; source_key makes external outcome writes idempotent."""

        bounded_reward = max(0.0, min(1.0, reward))
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT OR IGNORE INTO ai_experiences (
                    objective, action, reward, note, metadata_json, source_key, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    objective.strip(),
                    action.strip(),
                    bounded_reward,
                    note[:4000],
                    json.dumps(metadata or {}, sort_keys=True, default=str),
                    source_key,
                    datetime.now(UTC).isoformat(),
                ),
            )
            connection.commit()
        finally:
            self._release(connection)

    def summarize(self, *, objective: str, action: str, limit: int = 100) -> ExperienceSummary:
        """Return a relevance-weighted reward prior from recent comparable outcomes."""

        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT objective, reward
                FROM ai_experiences
                WHERE action = ?
                ORDER BY observed_at DESC
                LIMIT ?
                """,
                (action.strip(), max(1, min(limit, 500))),
            ).fetchall()
        finally:
            self._release(connection)

        if not rows:
            return ExperienceSummary()

        objective_tokens = self._tokens(objective)
        weighted_reward = 0.0
        total_weight = 0.0
        total_similarity = 0.0
        for row in rows:
            similarity = self._similarity(objective_tokens, self._tokens(str(row["objective"])))
            weight = 0.25 + (similarity * 0.75)
            weighted_reward += float(row["reward"]) * weight
            total_weight += weight
            total_similarity += similarity

        return ExperienceSummary(
            samples=len(rows),
            mean_reward=weighted_reward / total_weight if total_weight else 0.5,
            relevance=total_similarity / len(rows),
        )

    def close(self) -> None:
        if self._memory_connection is not None:
            self._memory_connection.close()
            self._memory_connection = None

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            ensure_state_schema(connection, self._database_path)
        finally:
            self._release(connection)

    def _connect(self) -> sqlite3.Connection:
        if self._database_path == ":memory:":
            if self._memory_connection is None:
                raise RuntimeError("in-memory experience store is closed")
            return self._memory_connection
        return self._new_connection(self._database_path)

    @staticmethod
    def _new_connection(database_path: str) -> sqlite3.Connection:
        return open_state_connection(database_path)

    def _release(self, connection: sqlite3.Connection) -> None:
        if self._database_path != ":memory:":
            connection.close()

    @staticmethod
    def _tokens(value: str) -> frozenset[str]:
        return frozenset(token.lower() for token in _TOKEN_RE.findall(value))

    @staticmethod
    def _similarity(left: frozenset[str], right: frozenset[str]) -> float:
        if not left or not right:
            return 0.0
        union = left | right
        return len(left & right) / len(union) if union else 0.0
