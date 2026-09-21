from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from instabotai.storage import (
    STATE_SCHEMA_VERSION,
    StateSchemaTooNewError,
    inspect_state_database,
    open_state_connection,
    upgrade_state_database,
)


def _legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE automation_actions (
                idempotency_key TEXT PRIMARY KEY,
                action_type TEXT NOT NULL,
                target_id TEXT,
                status TEXT NOT NULL,
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
            INSERT INTO automation_actions (
                idempotency_key, action_type, target_id, status, reason,
                confidence, payload_json, created_at
            ) VALUES ('legacy-action', 'reply_to_comment', 'comment-1', 'succeeded',
                      'legacy row', 0.91, '{}', '2026-09-21T12:00:00+00:00')
            """
        )
        connection.execute(
            """
            CREATE TABLE ai_decisions (
                decision_id TEXT PRIMARY KEY,
                objective TEXT NOT NULL,
                selected_action TEXT,
                score REAL NOT NULL,
                abstained INTEGER NOT NULL,
                provider TEXT,
                model TEXT,
                decision_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE ai_experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                objective TEXT NOT NULL,
                action TEXT NOT NULL,
                reward REAL NOT NULL,
                note TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                observed_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO ai_experiences (
                objective, action, reward, note, metadata_json, observed_at
            ) VALUES ('legacy objective', 'reply_to_comment', 0.8, 'kept', '{}',
                      '2026-09-21T12:01:00+00:00')
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_upgrade_preserves_legacy_state_and_creates_verified_backup(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    _legacy_database(database)

    report = upgrade_state_database(str(database))

    assert report.schema_version == STATE_SCHEMA_VERSION
    assert report.migrated is True
    assert report.integrity == "ok"
    assert report.backup_path is not None
    backup = Path(report.backup_path)
    assert backup.is_file()

    connection = open_state_connection(str(database))
    try:
        action = connection.execute(
            "SELECT idempotency_key, retryable FROM automation_actions"
        ).fetchone()
        experience = connection.execute(
            "SELECT objective, source_key FROM ai_experiences"
        ).fetchone()
        version = connection.execute(
            "SELECT version FROM instabotai_schema WHERE singleton_id = 1"
        ).fetchone()
        campaign_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        connection.close()

    assert action is not None
    assert action["idempotency_key"] == "legacy-action"
    assert action["retryable"] == 1
    assert experience is not None
    assert experience["objective"] == "legacy objective"
    assert experience["source_key"] is None
    assert version is not None and version["version"] == STATE_SCHEMA_VERSION
    assert {"campaigns", "campaign_jobs"}.issubset(campaign_tables)

    backup_connection = sqlite3.connect(backup)
    try:
        backup_columns = {
            str(row[1])
            for row in backup_connection.execute("PRAGMA table_info(automation_actions)")
        }
        legacy_row = backup_connection.execute(
            "SELECT idempotency_key FROM automation_actions"
        ).fetchone()
    finally:
        backup_connection.close()
    assert "retryable" not in backup_columns
    assert legacy_row is not None and legacy_row[0] == "legacy-action"


def test_upgrade_is_idempotent_and_does_not_create_second_backup(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    _legacy_database(database)

    first = upgrade_state_database(str(database))
    second = upgrade_state_database(str(database))

    assert first.migrated is True
    assert first.backup_path is not None
    assert second.migrated is False
    assert second.backup_path is None
    assert second.schema_version == STATE_SCHEMA_VERSION


def test_inspection_is_non_mutating_for_missing_database(tmp_path: Path) -> None:
    database = tmp_path / "missing.sqlite3"

    report = inspect_state_database(str(database))

    assert report.schema_version == 0
    assert report.migration_required is True
    assert report.integrity == "not_initialized"
    assert not database.exists()


def test_inspection_rejects_current_version_with_missing_columns(tmp_path: Path) -> None:
    database = tmp_path / "broken-current.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE instabotai_schema (
                singleton_id INTEGER PRIMARY KEY,
                version INTEGER NOT NULL,
                app_version TEXT NOT NULL,
                upgraded_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO instabotai_schema VALUES (1, ?, 'current', 'current')",
            (STATE_SCHEMA_VERSION,),
        )
        connection.execute(
            "CREATE TABLE automation_actions (idempotency_key TEXT PRIMARY KEY)"
        )
        connection.commit()
    finally:
        connection.close()

    report = inspect_state_database(str(database))

    assert report.schema_version == STATE_SCHEMA_VERSION
    assert report.migration_required is False
    assert report.integrity == "schema_invalid"
    assert report.ready is False


def test_upgrade_rejects_database_from_newer_schema(tmp_path: Path) -> None:
    database = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE instabotai_schema (
                singleton_id INTEGER PRIMARY KEY,
                version INTEGER NOT NULL,
                app_version TEXT NOT NULL,
                upgraded_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO instabotai_schema VALUES (1, ?, 'future', 'future')",
            (STATE_SCHEMA_VERSION + 1,),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(StateSchemaTooNewError):
        upgrade_state_database(str(database))


def test_fresh_upgrade_creates_current_schema_without_backup(tmp_path: Path) -> None:
    database = tmp_path / "fresh.sqlite3"

    report = upgrade_state_database(str(database))

    assert report.schema_version == STATE_SCHEMA_VERSION
    assert report.migrated is True
    assert report.backup_path is None
    assert report.ready is True
    assert set(report.managed_tables) == {
        "ai_decisions",
        "ai_experiences",
        "automation_actions",
        "campaign_jobs",
        "campaigns",
        "instabotai_schema",
    }
