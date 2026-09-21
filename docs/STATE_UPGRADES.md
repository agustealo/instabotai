# Durable State Upgrades

InstabotAI stores campaign state, AI decisions, observed outcomes, action idempotency, quota usage, and execution audit data in one configured SQLite database. That state is part of the product contract, so upgrades are versioned, backup-first, and fail closed rather than relying on individual stores to mutate tables independently.

The canonical schema authority is `instabotai.storage`. Production modules must not own parallel `ALTER TABLE` migration paths. CI enforces that rule.

## Operator commands

Inspect state without creating or migrating it:

```bash
instabotai state-check
```

`state-check` verifies the recorded schema version, SQLite integrity, and the complete required table/column contract. It exits with code `0` only when the configured state is already usable by the current InstabotAI build. A missing database, an older schema, a structurally incomplete current schema, or a newer unsupported schema is not reported as ready.

Upgrade or initialize durable state explicitly:

```bash
instabotai state-upgrade
```

For an existing managed database that needs migration, InstabotAI creates a verified SQLite backup before applying any migration. A fresh empty database does not need a pre-migration backup.

After an upgrade:

```bash
instabotai state-check
instabotai doctor
```

`doctor` reports the active schema version and target without exposing account credentials.

## Automatic migration boundaries

Canonical application startup and `trial-readiness` use the same schema authority. When a filesystem-backed state database is missing or on an older supported schema, it is initialized/upgraded before runtime services use it.

This does not make `state-check` mutating. Use `state-check` when you need a read-only preflight before allowing an upgrade.

`INSTABOTAI_STATE_DB_PATH=:memory:` remains valid for isolated tests but is rejected for consumer trials because it cannot preserve audit or recovery state.

## Backup behavior

Pre-migration backups are written to a sibling `backups/` directory next to the configured database. A backup name records the source schema, target schema, and UTC timestamp, for example:

```text
backups/instabotai.schema-v0-to-v3.20260921T213454291465Z.sqlite3
```

Backups are created through SQLite's backup API, then validated with `PRAGMA quick_check` before migration proceeds. InstabotAI attempts to restrict the backup file to mode `0600` on platforms that support POSIX permissions.

A failed backup verification aborts the migration. Existing state is not intentionally modified before a valid backup exists.

## Restore procedure

Stop the InstabotAI worker and consumer console before restoring durable state. Keep the failed/current database for forensic inspection rather than overwriting the only copy.

1. Locate the newest known-good backup in the configured state's `backups/` directory.
2. Copy the current database and any adjacent SQLite `-wal`/`-shm` files to a separate incident location if they exist.
3. Replace the configured state database with the verified backup while InstabotAI is stopped.
4. Ensure the runtime user can read and write the database **and its parent directory**. SQLite needs directory write permission to manage WAL/journal files and to create future migration backups.
5. Run `instabotai state-check`.
6. If the backup is on an older supported schema, run `instabotai state-upgrade` and then `instabotai state-check` again.
7. Run `instabotai trial-readiness` before resuming a consumer trial or worker.

Do not merge rows manually between state databases unless you have independently validated referential, idempotency, and audit invariants.

## Newer-schema / downgrade protection

A database whose recorded schema version is newer than the current binary supports is rejected. Do not downgrade that database in place.

Use a compatible newer InstabotAI build or restore a backup created before the newer schema was installed. This prevents an older binary from silently operating against state whose invariants it does not understand.

A database that claims the current schema version but is missing a required table or column is also rejected by `state-check`. Version metadata alone is not considered proof that state is usable.

## Docker and bind-mounted state

The production image intentionally runs as the non-root `instabotai` user. When mounting a host directory for durable state, the mounted directory and database must be writable by that container user. Do not solve a permission problem by running the application container as root.

For an operator-managed bind mount, determine the image UID/GID without invoking the InstabotAI CLI entrypoint:

```bash
uid=$(docker run --rm --entrypoint id instabotai:YOUR_TAG -u)
gid=$(docker run --rm --entrypoint id instabotai:YOUR_TAG -g)
```

Then provision the host state directory with ownership/permissions appropriate to that UID/GID according to your host security policy. The directory itself must be writable so SQLite can create WAL/journal files and InstabotAI can create `backups/` during migrations.

A named Docker volume can also be used, provided its ownership is initialized for the same non-root runtime user.

## Schema history represented by the current migrator

The migration chain models real state changes from the revived 2.x repository:

- **v1**: action ledger, AI decision journal, and outcome-memory core tables;
- **v2**: campaign/job persistence and idempotent outcome `source_key` support;
- **v3**: ambiguous-write retry safety through `automation_actions.retryable` plus current runtime indexes.

Future schema changes must add a new ordered migration in `instabotai.storage`, preserve existing records, and add upgrade regression proof. Store-local schema mutations are not an accepted migration mechanism.

## Release proof

The Quality Gate exercises upgrades in more than a fresh editable checkout:

1. unit/regression tests upgrade representative legacy state and verify preserved rows plus backup contents;
2. a built wheel is installed into a clean virtual environment and upgrades legacy SQLite state;
3. the production non-root Docker image upgrades a legacy database from a writable mounted state directory;
4. post-upgrade `state-check` and static `trial-readiness` must succeed;
5. the consumer console must still boot and answer `/healthz`.

This proves the release path against persisted state, not merely against a brand-new database.