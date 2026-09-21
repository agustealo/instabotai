"""Canonical SQLite schema, migration, backup, and integrity authority."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from instabotai import __version__

STATE_SCHEMA_VERSION = 3
_SCHEMA_TABLE = "instabotai_schema"
_MANAGED_TABLES = frozenset(
    {
        _SCHEMA_TABLE,
        "automation_actions",
        "ai_decisions",
        "ai_experiences",
        "campaigns",
        "campaign_jobs",
    }
)


class StateSchemaError(RuntimeError):
    """Base error for state schema verification and migration failures."""


class StateSchemaTooNewError(StateSchemaError):
    """Raised when the database was created by a newer InstabotAI schema."""


class StateSchemaReport(BaseModel):
    """Secret-free state database inspection or migration result."""

    database_path: str
    schema_version: int
    target_version: int = STATE_SCHEMA_VERSION
    migration_required: bool
    integrity: str
    managed_tables: tuple[str, ...]
    migrated: bool = False
    backup_path: str | None = None

    @property
    def ready(self) -> bool:
        return (
            self.schema_version == self.target_version
            and not self.migration_required
            and self.integrity == "ok"
        )


def open_state_connection(database_path: str, *, timeout: float = 10.0) -> sqlite3.Connection:
    """Open one canonical SQLite connection with the runtime safety pragmas."""

    connection = sqlite3.connect(database_path, timeout=timeout)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if database_path != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
    return connection


def inspect_state_database(database_path: str) -> StateSchemaReport:
    """Inspect schema/integrity without migrating or creating a missing file."""

    if database_path == ":memory:":
        return StateSchemaReport(
            database_path=database_path,
            schema_version=0,
            migration_required=True,
            integrity="transient",
            managed_tables=(),
        )

    path = Path(database_path).expanduser()
    if not path.exists():
        return StateSchemaReport(
            database_path=str(path),
            schema_version=0,
            migration_required=True,
            integrity="not_initialized",
            managed_tables=(),
        )

    try:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise StateSchemaError(f"could not open state database for inspection: {exc}") from exc

    try:
        version = _read_schema_version(connection)
        if version > STATE_SCHEMA_VERSION:
            raise StateSchemaTooNewError(
                f"state schema v{version} is newer than supported v{STATE_SCHEMA_VERSION}"
            )
        tables = _managed_tables(connection)
        integrity = _integrity(connection)
        return StateSchemaReport(
            database_path=str(path),
            schema_version=version,
            migration_required=version != STATE_SCHEMA_VERSION,
            integrity=integrity,
            managed_tables=tables,
        )
    finally:
        connection.close()


def upgrade_state_database(database_path: str) -> StateSchemaReport:
    """Upgrade a state database to the current schema, backing up managed legacy state first."""

    if database_path != ":memory:":
        Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    connection = open_state_connection(database_path)
    try:
        return ensure_state_schema(connection, database_path)
    finally:
        connection.close()


def ensure_state_schema(
    connection: sqlite3.Connection,
    database_path: str,
) -> StateSchemaReport:
    """Idempotently migrate an already-open connection to the current state schema."""

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initial_version = _read_schema_version(connection)
    if initial_version > STATE_SCHEMA_VERSION:
        raise StateSchemaTooNewError(
            f"state schema v{initial_version} is newer than supported v{STATE_SCHEMA_VERSION}"
        )

    initial_tables = _managed_tables(connection)
    backup_path: str | None = None
    if (
        initial_version < STATE_SCHEMA_VERSION
        and database_path != ":memory:"
        and any(table != _SCHEMA_TABLE for table in initial_tables)
    ):
        backup_path = _backup_database(connection, database_path, initial_version)

    migrated = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        current_version = _read_schema_version(connection)
        if current_version > STATE_SCHEMA_VERSION:
            raise StateSchemaTooNewError(
                f"state schema v{current_version} is newer than supported v{STATE_SCHEMA_VERSION}"
            )

        _create_schema_table(connection)
        migrations = (
            (1, _migrate_v1_core_state),
            (2, _migrate_v2_campaigns_and_outcome_keys),
            (3, _migrate_v3_retry_safety_and_indexes),
        )
        for version, migration in migrations:
            if current_version < version:
                migration(connection)
                _write_schema_version(connection, version)
                current_version = version
                migrated = True

        _verify_current_schema(connection)
        integrity = _integrity(connection)
        if integrity != "ok":
            raise StateSchemaError(f"SQLite integrity check failed after migration: {integrity}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    return StateSchemaReport(
        database_path=database_path,
        schema_version=STATE_SCHEMA_VERSION,
        migration_required=False,
        integrity="ok",
        managed_tables=_managed_tables(connection),
        migrated=migrated,
        backup_path=backup_path,
    )


def _migrate_v1_core_state(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_actions (
            idempotency_key TEXT PRIMARY KEY,
            action_type TEXT NOT NULL,
            target_id TEXT,
            status TEXT NOT NULL CHECK (status IN ('reserved', 'succeeded', 'failed')),
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
        CREATE TABLE IF NOT EXISTS ai_experiences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            objective TEXT NOT NULL,
            action TEXT NOT NULL,
            reward REAL NOT NULL CHECK (reward >= 0.0 AND reward <= 1.0),
            note TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            observed_at TEXT NOT NULL
        )
        """
    )


def _migrate_v2_campaigns_and_outcome_keys(connection: sqlite3.Connection) -> None:
    if not _column_exists(connection, "ai_experiences", "source_key"):
        connection.execute("ALTER TABLE ai_experiences ADD COLUMN source_key TEXT")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS campaigns (
            campaign_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            objective TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('draft', 'active', 'paused', 'completed', 'archived')
            ),
            mode TEXT NOT NULL CHECK (mode IN ('supervised', 'policy_managed')),
            cadence_minutes INTEGER NOT NULL,
            action_delay_minutes INTEGER NOT NULL,
            evidence_json TEXT NOT NULL,
            context_json TEXT NOT NULL,
            research_seed_urls_json TEXT NOT NULL,
            research_before_plan INTEGER NOT NULL CHECK (research_before_plan IN (0, 1)),
            next_run_at TEXT,
            last_run_at TEXT,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            plan_claim_token TEXT,
            plan_claim_expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS campaign_jobs (
            job_id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
            decision_id TEXT NOT NULL,
            action_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN (
                    'pending_approval', 'scheduled', 'leased', 'retry_wait',
                    'succeeded', 'failed', 'rejected', 'cancelled'
                )
            ),
            scheduled_for TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL,
            lease_token TEXT,
            lease_expires_at TEXT,
            last_error TEXT,
            provider_result_json TEXT,
            outcome_reward REAL,
            outcome_note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        )
        """
    )


def _migrate_v3_retry_safety_and_indexes(connection: sqlite3.Connection) -> None:
    if not _column_exists(connection, "automation_actions", "retryable"):
        connection.execute(
            "ALTER TABLE automation_actions ADD COLUMN retryable INTEGER NOT NULL DEFAULT 1"
        )

    connection.execute("DROP INDEX IF EXISTS idx_automation_actions_usage")
    connection.execute(
        """
        CREATE INDEX idx_automation_actions_usage
        ON automation_actions (status, retryable, created_at, action_type)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ai_decisions_created_at
        ON ai_decisions (created_at DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ai_experiences_action_time
        ON ai_experiences (action, observed_at DESC)
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_experiences_source_key
        ON ai_experiences (source_key)
        WHERE source_key IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_campaigns_due
        ON campaigns (status, next_run_at, plan_claim_expires_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_campaign_jobs_due
        ON campaign_jobs (status, scheduled_for, lease_expires_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_campaign_jobs_campaign
        ON campaign_jobs (campaign_id, created_at DESC)
        """
    )


def _create_schema_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS instabotai_schema (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            version INTEGER NOT NULL CHECK (version >= 0),
            app_version TEXT NOT NULL,
            upgraded_at TEXT NOT NULL
        )
        """
    )


def _read_schema_version(connection: sqlite3.Connection) -> int:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (_SCHEMA_TABLE,),
    ).fetchone()
    if table is None:
        return 0
    row = connection.execute(
        "SELECT version FROM instabotai_schema WHERE singleton_id = 1"
    ).fetchone()
    return int(row["version"] if isinstance(row, sqlite3.Row) else row[0]) if row else 0


def _write_schema_version(connection: sqlite3.Connection, version: int) -> None:
    connection.execute(
        """
        INSERT INTO instabotai_schema (singleton_id, version, app_version, upgraded_at)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(singleton_id) DO UPDATE SET
            version = excluded.version,
            app_version = excluded.app_version,
            upgraded_at = excluded.upgraded_at
        """,
        (version, __version__, datetime.now(UTC).isoformat()),
    )


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    return any(
        str(row["name"] if isinstance(row, sqlite3.Row) else row[1]) == column
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    )


def _managed_tables(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    names = {
        str(row["name"] if isinstance(row, sqlite3.Row) else row[0])
        for row in rows
    }
    return tuple(sorted(names & _MANAGED_TABLES))


def _integrity(connection: sqlite3.Connection) -> str:
    row = connection.execute("PRAGMA quick_check").fetchone()
    if row is None:
        return "no_result"
    return str(row[0]).lower()


def _verify_current_schema(connection: sqlite3.Connection) -> None:
    required_columns = {
        "automation_actions": {
            "idempotency_key",
            "action_type",
            "target_id",
            "status",
            "retryable",
            "reason",
            "confidence",
            "payload_json",
            "created_at",
            "executed_at",
            "provider_result",
            "error",
        },
        "ai_decisions": {
            "decision_id",
            "objective",
            "selected_action",
            "score",
            "abstained",
            "provider",
            "model",
            "decision_json",
            "created_at",
        },
        "ai_experiences": {
            "id",
            "objective",
            "action",
            "reward",
            "note",
            "metadata_json",
            "source_key",
            "observed_at",
        },
        "campaigns": {
            "campaign_id",
            "name",
            "objective",
            "status",
            "mode",
            "cadence_minutes",
            "action_delay_minutes",
            "evidence_json",
            "context_json",
            "research_seed_urls_json",
            "research_before_plan",
            "next_run_at",
            "last_run_at",
            "consecutive_failures",
            "plan_claim_token",
            "plan_claim_expires_at",
            "created_at",
            "updated_at",
        },
        "campaign_jobs": {
            "job_id",
            "campaign_id",
            "decision_id",
            "action_json",
            "status",
            "scheduled_for",
            "attempt_count",
            "max_attempts",
            "lease_token",
            "lease_expires_at",
            "last_error",
            "provider_result_json",
            "outcome_reward",
            "outcome_note",
            "created_at",
            "updated_at",
            "completed_at",
        },
    }
    for table, expected in required_columns.items():
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        actual = {
            str(row["name"] if isinstance(row, sqlite3.Row) else row[1]) for row in rows
        }
        missing = expected - actual
        if missing:
            joined = ", ".join(sorted(missing))
            raise StateSchemaError(f"state table {table!r} is missing columns: {joined}")


def _backup_database(
    connection: sqlite3.Connection,
    database_path: str,
    source_version: int,
) -> str:
    source = Path(database_path).expanduser()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = source.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / (
        f"{source.stem}.schema-v{source_version}-to-v{STATE_SCHEMA_VERSION}.{timestamp}.sqlite3"
    )
    destination = sqlite3.connect(backup)
    try:
        connection.backup(destination)
        row = destination.execute("PRAGMA quick_check").fetchone()
        if row is None or str(row[0]).lower() != "ok":
            raise StateSchemaError("pre-migration backup failed SQLite integrity verification")
    finally:
        destination.close()
    try:
        backup.chmod(0o600)
    except OSError:
        pass
    return str(backup)
