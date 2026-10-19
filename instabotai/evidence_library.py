"""Reusable evidence records backed by the canonical SQLite state schema.

Library review is an explicit human label, never automatic source verification.
Campaigns consume copied EvidenceItem snapshots, not mutable library references.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from instabotai.intelligence import EvidenceItem
from instabotai.storage import ensure_state_schema, open_state_connection, upgrade_state_database

ReviewStatus = Literal["unverified", "reviewed", "rejected"]
EvidenceOrigin = Literal["manual", "research"]


class EvidenceNotFoundError(LookupError):
    """A requested saved evidence entry does not exist."""


class EvidenceConflictError(RuntimeError):
    """The evidence entry changed while the editor was open."""


class EvidenceLibraryCreate(BaseModel):
    """Consumer-supplied evidence, initially unverified regardless of origin."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=160)
    source: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=12_000)
    confidence: float = Field(default=0.5, ge=0, le=1)
    origin: EvidenceOrigin = "manual"
    tags: tuple[str, ...] = Field(default=(), max_length=12)
    note: str = Field(default="", max_length=2_000)

    @field_validator("title", "source", "content")
    @classmethod
    def nonempty_trimmed(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("This field cannot be blank")
        return trimmed

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(value.strip().lower() for value in values))
        if any(not item or len(item) > 40 for item in normalized):
            raise ValueError("Tags must be 1 to 40 non-whitespace characters")
        return normalized


class EvidenceLibraryUpdate(BaseModel):
    """Optimistic, partial update; a content change discards previous review state."""

    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime
    title: str | None = Field(default=None, min_length=2, max_length=160)
    source: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, min_length=1, max_length=12_000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    review_status: ReviewStatus | None = None
    tags: tuple[str, ...] | None = Field(default=None, max_length=12)
    note: str | None = Field(default=None, max_length=2_000)

    @field_validator("title", "source", "content")
    @classmethod
    def nonempty_trimmed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("This field cannot be blank")
        return trimmed

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if values is None:
            return None
        return EvidenceLibraryCreate.normalize_tags(values)


class EvidenceLibraryEntry(EvidenceLibraryCreate):
    """Persisted review state with stable ID and timestamps."""

    library_id: str = Field(min_length=32, max_length=32)
    review_status: ReviewStatus = "unverified"
    created_at: datetime
    updated_at: datetime

    def as_campaign_evidence(self) -> EvidenceItem:
        """A stable ID and immutable-by-copy payload for new campaign drafts."""

        return EvidenceItem(
            evidence_id="library-" + self.library_id,
            source=self.source,
            content=self.content,
            confidence=self.confidence,
        )


class EvidenceLibraryStore:
    """One evidence authority; all schema changes remain in storage.py."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self._memory: sqlite3.Connection | None = None
        if database_path == ":memory:":
            self._memory = open_state_connection(database_path)
            ensure_state_schema(self._memory, database_path)
        else:
            upgrade_state_database(database_path)

    def _connection(self) -> sqlite3.Connection:
        if self._memory is not None:
            return self._memory
        return open_state_connection(self.database_path)

    def _release(self, connection: sqlite3.Connection) -> None:
        if self._memory is None:
            connection.close()

    @staticmethod
    def _row(row: sqlite3.Row) -> EvidenceLibraryEntry:
        return EvidenceLibraryEntry(
            library_id=row["library_id"],
            title=row["title"],
            source=row["source"],
            content=row["content"],
            confidence=row["confidence"],
            origin=row["origin"],
            review_status=row["review_status"],
            tags=tuple(json.loads(row["tags_json"])),
            note=row["note"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def create(self, payload: EvidenceLibraryCreate) -> EvidenceLibraryEntry:
        now = datetime.now(UTC)
        entry = EvidenceLibraryEntry(
            **payload.model_dump(),
            library_id=uuid4().hex,
            review_status="unverified",
            created_at=now,
            updated_at=now,
        )
        connection = self._connection()
        try:
            connection.execute(
                """
                INSERT INTO evidence_library (
                    library_id, title, source, content, confidence, origin,
                    review_status, tags_json, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.library_id, entry.title, entry.source, entry.content, entry.confidence,
                    entry.origin, entry.review_status, json.dumps(entry.tags),
                    entry.note, now.isoformat(), now.isoformat(),
                ),
            )
            connection.commit()
            return entry
        finally:
            self._release(connection)

    def get(self, library_id: str) -> EvidenceLibraryEntry:
        connection = self._connection()
        try:
            row = connection.execute(
                "SELECT * FROM evidence_library WHERE library_id = ?", (library_id,)
            ).fetchone()
            if row is None:
                raise EvidenceNotFoundError("Saved evidence was not found")
            return self._row(row)
        finally:
            self._release(connection)

    def list(
        self, *, limit: int = 100, offset: int = 0, query: str = "",
    ) -> tuple[EvidenceLibraryEntry, ...]:
        if not 1 <= limit <= 200 or not 0 <= offset <= 100_000:
            raise ValueError("Invalid evidence library pagination")
        connection = self._connection()
        try:
            if query.strip():
                escaped = (
                    query.strip().lower().replace("\\", "\\\\")
                    .replace("%", "\\%").replace("_", "\\_")
                )
                rows = connection.execute(
                    """
                    SELECT * FROM evidence_library
                    WHERE lower(title) LIKE ? ESCAPE '\\'
                       OR lower(source) LIKE ? ESCAPE '\\'
                    ORDER BY updated_at DESC, library_id DESC LIMIT ? OFFSET ?
                    """,
                    (f"%{escaped}%", f"%{escaped}%", limit, offset),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM evidence_library
                    ORDER BY updated_at DESC, library_id DESC LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
            return tuple(self._row(row) for row in rows)
        finally:
            self._release(connection)

    def update(self, library_id: str, patch: EvidenceLibraryUpdate) -> EvidenceLibraryEntry:
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM evidence_library WHERE library_id = ?", (library_id,)
            ).fetchone()
            if row is None:
                raise EvidenceNotFoundError("Saved evidence was not found")
            current = self._row(row)
            if current.updated_at != patch.expected_updated_at:
                raise EvidenceConflictError("Saved evidence changed; reload before saving")

            changed = {
                key: value for key, value in patch.model_dump(exclude_unset=True).items()
                if key != "expected_updated_at" and value is not None
            }
            if any(
                key in changed and changed[key] != getattr(current, key)
                for key in ("source", "content", "confidence")
            ):
                changed["review_status"] = "unverified"
            updated = EvidenceLibraryEntry.model_validate(
                {
                    **current.model_dump(mode="python"),
                    **changed,
                    "updated_at": datetime.now(UTC),
                }
            )
            connection.execute(
                """
                UPDATE evidence_library SET
                    title = ?, source = ?, content = ?, confidence = ?, review_status = ?,
                    tags_json = ?, note = ?, updated_at = ?
                WHERE library_id = ?
                """,
                (
                    updated.title, updated.source, updated.content, updated.confidence,
                    updated.review_status, json.dumps(updated.tags), updated.note,
                    updated.updated_at.isoformat(), library_id,
                ),
            )
            connection.commit()
            return updated
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)

    def delete(self, library_id: str, *, expected_updated_at: datetime) -> None:
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT updated_at FROM evidence_library WHERE library_id = ?", (library_id,)
            ).fetchone()
            if row is None:
                raise EvidenceNotFoundError("Saved evidence was not found")
            if datetime.fromisoformat(row["updated_at"]) != expected_updated_at:
                raise EvidenceConflictError("Saved evidence changed; reload before deleting")
            connection.execute(
                "DELETE FROM evidence_library WHERE library_id = ?", (library_id,)
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)

    def close(self) -> None:
        if self._memory is not None:
            self._memory.close()
            self._memory = None
