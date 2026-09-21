"""SQLite persistence for campaigns and the durable action queue."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from instabotai.campaigns.domain import (
    Campaign,
    CampaignJob,
    CampaignMode,
    CampaignStatus,
    JobStatus,
)
from instabotai.domain import ApprovalState, PlannedAction
from instabotai.settings import Settings


class CampaignNotFoundError(LookupError):
    pass


class CampaignStateError(RuntimeError):
    pass


class CampaignStore:
    OPEN_JOB_STATUSES = (
        JobStatus.PENDING_APPROVAL.value,
        JobStatus.SCHEDULED.value,
        JobStatus.LEASED.value,
        JobStatus.RETRY_WAIT.value,
    )

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        self._memory_connection: sqlite3.Connection | None = None
        if database_path == ":memory:":
            self._memory_connection = self._new_connection(database_path)
        else:
            Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create_campaign(self, campaign: Campaign) -> Campaign:
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO campaigns (
                    campaign_id, name, objective, status, mode, cadence_minutes,
                    action_delay_minutes, evidence_json, context_json,
                    research_seed_urls_json, research_before_plan, next_run_at,
                    last_run_at, consecutive_failures, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign.campaign_id,
                    campaign.name,
                    campaign.objective,
                    campaign.status.value,
                    campaign.mode.value,
                    campaign.cadence_minutes,
                    campaign.action_delay_minutes,
                    json.dumps(
                        [item.model_dump(mode="json") for item in campaign.evidence],
                        sort_keys=True,
                        default=str,
                    ),
                    json.dumps(campaign.context, sort_keys=True, default=str),
                    json.dumps(campaign.research_seed_urls),
                    int(campaign.research_before_plan),
                    self._iso(campaign.next_run_at),
                    self._iso(campaign.last_run_at),
                    campaign.consecutive_failures,
                    campaign.created_at.isoformat(),
                    campaign.updated_at.isoformat(),
                ),
            )
            connection.commit()
        finally:
            self._release(connection)
        return campaign

    def get_campaign(self, campaign_id: str) -> Campaign:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        finally:
            self._release(connection)
        if row is None:
            raise CampaignNotFoundError(f"campaign {campaign_id!r} was not found")
        return self._campaign_from_row(row)

    def list_campaigns(self, limit: int = 100) -> tuple[Campaign, ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM campaigns ORDER BY updated_at DESC, created_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        finally:
            self._release(connection)
        return tuple(self._campaign_from_row(row) for row in rows)

    def set_campaign_status(
        self,
        campaign_id: str,
        status: CampaignStatus,
        *,
        now: datetime | None = None,
    ) -> Campaign:
        current = self.get_campaign(campaign_id)
        if current.status is CampaignStatus.ARCHIVED:
            raise CampaignStateError("archived campaigns cannot change status")
        if status is CampaignStatus.DRAFT and current.status is not CampaignStatus.DRAFT:
            raise CampaignStateError("campaigns cannot return to draft")
        if status is CampaignStatus.ARCHIVED and self.count_open_jobs(campaign_id) > 0:
            raise CampaignStateError("cannot archive a campaign with open jobs")

        moment = self._utc(now)
        next_run = current.next_run_at
        if status is CampaignStatus.ACTIVE and (
            next_run is None or self._utc(next_run) < moment
        ):
            next_run = moment

        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE campaigns
                SET status = ?, next_run_at = ?,
                    plan_claim_token = CASE WHEN ? = 'active' THEN plan_claim_token ELSE NULL END,
                    plan_claim_expires_at = CASE
                        WHEN ? = 'active' THEN plan_claim_expires_at ELSE NULL END,
                    updated_at = ?
                WHERE campaign_id = ?
                """,
                (
                    status.value,
                    self._iso(next_run),
                    status.value,
                    status.value,
                    moment.isoformat(),
                    campaign_id,
                ),
            )
            if cursor.rowcount != 1:
                raise CampaignNotFoundError(f"campaign {campaign_id!r} was not found")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)
        return self.get_campaign(campaign_id)

    def count_open_jobs(self, campaign_id: str) -> int:
        placeholders = ",".join("?" for _ in self.OPEN_JOB_STATUSES)
        connection = self._connect()
        try:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS item_count
                FROM campaign_jobs
                WHERE campaign_id = ? AND status IN ({placeholders})
                """,
                (campaign_id, *self.OPEN_JOB_STATUSES),
            ).fetchone()
        finally:
            self._release(connection)
        return int(row["item_count"]) if row is not None else 0

    def claim_due_campaign(
        self,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> tuple[Campaign, str] | None:
        return self._claim_campaign(
            campaign_id=None,
            require_due=True,
            lease_seconds=lease_seconds,
            now=self._utc(now),
        )

    def claim_campaign(
        self,
        campaign_id: str,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> tuple[Campaign, str]:
        claimed = self._claim_campaign(
            campaign_id=campaign_id,
            require_due=False,
            lease_seconds=lease_seconds,
            now=self._utc(now),
        )
        if claimed is None:
            campaign = self.get_campaign(campaign_id)
            if campaign.status is CampaignStatus.ARCHIVED:
                raise CampaignStateError("archived campaigns cannot be planned")
            if self.count_open_jobs(campaign_id) > 0:
                raise CampaignStateError("campaign already has an open action")
            raise CampaignStateError("campaign is already being planned")
        return claimed

    def complete_campaign_cycle(
        self,
        campaign_id: str,
        claim_token: str,
        *,
        next_run_at: datetime,
        now: datetime | None = None,
    ) -> Campaign:
        moment = self._utc(now)
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE campaigns
                SET next_run_at = ?, last_run_at = ?, consecutive_failures = 0,
                    plan_claim_token = NULL, plan_claim_expires_at = NULL, updated_at = ?
                WHERE campaign_id = ? AND plan_claim_token = ?
                """,
                (
                    self._utc(next_run_at).isoformat(),
                    moment.isoformat(),
                    moment.isoformat(),
                    campaign_id,
                    claim_token,
                ),
            )
            if cursor.rowcount != 1:
                raise CampaignStateError("campaign planning lease is no longer owned")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)
        return self.get_campaign(campaign_id)

    def fail_campaign_cycle(
        self,
        campaign_id: str,
        claim_token: str,
        *,
        retry_at: datetime,
        now: datetime | None = None,
    ) -> Campaign:
        moment = self._utc(now)
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE campaigns
                SET next_run_at = ?, last_run_at = ?,
                    consecutive_failures = consecutive_failures + 1,
                    plan_claim_token = NULL, plan_claim_expires_at = NULL, updated_at = ?
                WHERE campaign_id = ? AND plan_claim_token = ?
                """,
                (
                    self._utc(retry_at).isoformat(),
                    moment.isoformat(),
                    moment.isoformat(),
                    campaign_id,
                    claim_token,
                ),
            )
            if cursor.rowcount != 1:
                raise CampaignStateError("campaign planning lease is no longer owned")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)
        return self.get_campaign(campaign_id)

    def enqueue_job(
        self,
        *,
        campaign: Campaign,
        decision_id: str,
        action: PlannedAction,
        settings: Settings,
        scheduled_for: datetime,
    ) -> CampaignJob:
        approval_needed = (
            campaign.mode is CampaignMode.SUPERVISED or settings.require_write_approval
        )
        status = JobStatus.PENDING_APPROVAL if approval_needed else JobStatus.SCHEDULED
        job = CampaignJob(
            campaign_id=campaign.campaign_id,
            decision_id=decision_id,
            action=action,
            status=status,
            scheduled_for=self._utc(scheduled_for),
            max_attempts=settings.campaign_action_max_attempts,
        )
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO campaign_jobs (
                    job_id, campaign_id, decision_id, action_json, status,
                    scheduled_for, attempt_count, max_attempts, lease_token,
                    lease_expires_at, last_error, provider_result_json,
                    outcome_reward, outcome_note, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, '', ?, ?, NULL)
                """,
                (
                    job.job_id,
                    job.campaign_id,
                    job.decision_id,
                    job.action.model_dump_json(),
                    job.status.value,
                    job.scheduled_for.isoformat(),
                    job.attempt_count,
                    job.max_attempts,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )
            connection.commit()
        finally:
            self._release(connection)
        return job

    def get_job(self, job_id: str) -> CampaignJob:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM campaign_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        finally:
            self._release(connection)
        if row is None:
            raise CampaignStateError(f"campaign job {job_id!r} was not found")
        return self._job_from_row(row)

    def list_jobs(
        self,
        *,
        campaign_id: str | None = None,
        limit: int = 100,
    ) -> tuple[CampaignJob, ...]:
        bounded = max(1, min(limit, 500))
        connection = self._connect()
        try:
            if campaign_id is None:
                rows = connection.execute(
                    "SELECT * FROM campaign_jobs ORDER BY created_at DESC LIMIT ?",
                    (bounded,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM campaign_jobs
                    WHERE campaign_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (campaign_id, bounded),
                ).fetchall()
        finally:
            self._release(connection)
        return tuple(self._job_from_row(row) for row in rows)

    def approve_job(self, job_id: str, *, now: datetime | None = None) -> CampaignJob:
        moment = self._utc(now)
        job = self.get_job(job_id)
        if job.status is not JobStatus.PENDING_APPROVAL:
            raise CampaignStateError("only pending-approval jobs can be approved")
        action = job.action.model_copy(update={"approval": ApprovalState.APPROVED})
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE campaign_jobs
                SET action_json = ?, status = 'scheduled', updated_at = ?
                WHERE job_id = ? AND status = 'pending_approval'
                """,
                (action.model_dump_json(), moment.isoformat(), job_id),
            )
            if cursor.rowcount != 1:
                raise CampaignStateError("job approval state changed concurrently")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)
        return self.get_job(job_id)

    def reject_job(self, job_id: str, *, now: datetime | None = None) -> CampaignJob:
        moment = self._utc(now)
        job = self.get_job(job_id)
        if job.status is not JobStatus.PENDING_APPROVAL:
            raise CampaignStateError("only pending-approval jobs can be rejected")
        action = job.action.model_copy(update={"approval": ApprovalState.REJECTED})
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE campaign_jobs
                SET action_json = ?, status = 'rejected', completed_at = ?, updated_at = ?
                WHERE job_id = ? AND status = 'pending_approval'
                """,
                (
                    action.model_dump_json(),
                    moment.isoformat(),
                    moment.isoformat(),
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise CampaignStateError("job approval state changed concurrently")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)
        return self.get_job(job_id)

    def cancel_job(self, job_id: str, *, now: datetime | None = None) -> CampaignJob:
        moment = self._utc(now)
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE campaign_jobs
                SET status = 'cancelled', lease_token = NULL, lease_expires_at = NULL,
                    completed_at = ?, updated_at = ?
                WHERE job_id = ?
                  AND status IN ('pending_approval', 'scheduled', 'retry_wait')
                """,
                (moment.isoformat(), moment.isoformat(), job_id),
            )
            if cursor.rowcount != 1:
                raise CampaignStateError("only open, unleased jobs can be cancelled")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)
        return self.get_job(job_id)

    def claim_next_job(
        self,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> tuple[CampaignJob, str] | None:
        return self._claim_job(
            job_id=None,
            lease_seconds=lease_seconds,
            now=self._utc(now),
        )

    def claim_job(
        self,
        job_id: str,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> tuple[CampaignJob, str]:
        claimed = self._claim_job(
            job_id=job_id,
            lease_seconds=lease_seconds,
            now=self._utc(now),
        )
        if claimed is None:
            job = self.get_job(job_id)
            raise CampaignStateError(
                f"job {job_id!r} is not executable from status {job.status.value!r}"
            )
        return claimed

    def mark_job_succeeded(
        self,
        job_id: str,
        lease_token: str,
        provider_result: object,
        *,
        now: datetime | None = None,
    ) -> CampaignJob:
        moment = self._utc(now)
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE campaign_jobs
                SET status = 'succeeded', provider_result_json = ?, last_error = NULL,
                    lease_token = NULL, lease_expires_at = NULL,
                    completed_at = ?, updated_at = ?
                WHERE job_id = ? AND status = 'leased' AND lease_token = ?
                """,
                (
                    json.dumps(provider_result, sort_keys=True, default=str),
                    moment.isoformat(),
                    moment.isoformat(),
                    job_id,
                    lease_token,
                ),
            )
            if cursor.rowcount != 1:
                raise CampaignStateError("job execution lease is no longer owned")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)
        return self.get_job(job_id)

    def mark_job_execution_failed(
        self,
        job_id: str,
        lease_token: str,
        error: str,
        *,
        retry_base_seconds: int,
        retry_cap_seconds: int,
        now: datetime | None = None,
    ) -> CampaignJob:
        moment = self._utc(now)
        job = self.get_job(job_id)
        if job.status is not JobStatus.LEASED or job.lease_token != lease_token:
            raise CampaignStateError("job execution lease is no longer owned")

        terminal = job.attempt_count >= job.max_attempts
        next_status = JobStatus.FAILED if terminal else JobStatus.RETRY_WAIT
        delay = min(
            retry_cap_seconds,
            retry_base_seconds * (2 ** max(0, job.attempt_count - 1)),
        )
        scheduled_for = moment if terminal else moment + timedelta(seconds=delay)
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE campaign_jobs
                SET status = ?, scheduled_for = ?, last_error = ?,
                    lease_token = NULL, lease_expires_at = NULL,
                    completed_at = ?, updated_at = ?
                WHERE job_id = ? AND status = 'leased' AND lease_token = ?
                """,
                (
                    next_status.value,
                    scheduled_for.isoformat(),
                    error[:4000],
                    moment.isoformat() if terminal else None,
                    moment.isoformat(),
                    job_id,
                    lease_token,
                ),
            )
            if cursor.rowcount != 1:
                raise CampaignStateError("job execution lease is no longer owned")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)
        return self.get_job(job_id)

    def record_outcome(
        self,
        job_id: str,
        *,
        reward: float,
        note: str,
        now: datetime | None = None,
    ) -> CampaignJob:
        moment = self._utc(now)
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE campaign_jobs
                SET outcome_reward = ?, outcome_note = ?, updated_at = ?
                WHERE job_id = ?
                  AND status = 'succeeded'
                  AND outcome_reward IS NULL
                """,
                (
                    max(0.0, min(1.0, reward)),
                    note[:4000],
                    moment.isoformat(),
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise CampaignStateError(
                    "outcome can be recorded once, only after successful execution"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)
        return self.get_job(job_id)

    def close(self) -> None:
        if self._memory_connection is not None:
            self._memory_connection.close()
            self._memory_connection = None

    def _claim_campaign(
        self,
        *,
        campaign_id: str | None,
        require_due: bool,
        lease_seconds: int,
        now: datetime,
    ) -> tuple[Campaign, str] | None:
        token = uuid4().hex
        expires = now + timedelta(seconds=lease_seconds)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            open_placeholders = ",".join("?" for _ in self.OPEN_JOB_STATUSES)
            filters = [
                "status != 'archived'",
                "(plan_claim_token IS NULL OR plan_claim_expires_at <= ?)",
                f"""
                NOT EXISTS (
                    SELECT 1 FROM campaign_jobs
                    WHERE campaign_jobs.campaign_id = campaigns.campaign_id
                      AND campaign_jobs.status IN ({open_placeholders})
                )
                """,
            ]
            params: list[object] = [now.isoformat(), *self.OPEN_JOB_STATUSES]
            if require_due:
                filters.extend(
                    ["status = 'active'", "next_run_at IS NOT NULL", "next_run_at <= ?"]
                )
                params.append(now.isoformat())
            if campaign_id is not None:
                filters.append("campaign_id = ?")
                params.append(campaign_id)

            row = connection.execute(
                f"""
                SELECT * FROM campaigns
                WHERE {" AND ".join(filters)}
                ORDER BY COALESCE(next_run_at, created_at), created_at
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None

            selected_id = str(row["campaign_id"])
            cursor = connection.execute(
                """
                UPDATE campaigns
                SET plan_claim_token = ?, plan_claim_expires_at = ?, updated_at = ?
                WHERE campaign_id = ?
                  AND (plan_claim_token IS NULL OR plan_claim_expires_at <= ?)
                """,
                (
                    token,
                    expires.isoformat(),
                    now.isoformat(),
                    selected_id,
                    now.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)
        return self.get_campaign(selected_id), token

    def _claim_job(
        self,
        *,
        job_id: str | None,
        lease_seconds: int,
        now: datetime,
    ) -> tuple[CampaignJob, str] | None:
        token = uuid4().hex
        expires = now + timedelta(seconds=lease_seconds)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            filters = [
                "campaigns.status = 'active'",
                "campaign_jobs.scheduled_for <= ?",
                """
                (
                    campaign_jobs.status IN ('scheduled', 'retry_wait')
                    OR (
                        campaign_jobs.status = 'leased'
                        AND campaign_jobs.lease_expires_at IS NOT NULL
                        AND campaign_jobs.lease_expires_at <= ?
                    )
                )
                """,
            ]
            params: list[object] = [now.isoformat(), now.isoformat()]
            if job_id is not None:
                filters.append("campaign_jobs.job_id = ?")
                params.append(job_id)

            row = connection.execute(
                f"""
                SELECT campaign_jobs.*
                FROM campaign_jobs
                JOIN campaigns USING (campaign_id)
                WHERE {" AND ".join(filters)}
                ORDER BY campaign_jobs.scheduled_for, campaign_jobs.created_at
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None

            selected_id = str(row["job_id"])
            cursor = connection.execute(
                """
                UPDATE campaign_jobs
                SET status = 'leased', attempt_count = attempt_count + 1,
                    lease_token = ?, lease_expires_at = ?, updated_at = ?
                WHERE job_id = ?
                  AND (
                    status IN ('scheduled', 'retry_wait')
                    OR (
                        status = 'leased'
                        AND lease_expires_at IS NOT NULL
                        AND lease_expires_at <= ?
                    )
                  )
                """,
                (
                    token,
                    expires.isoformat(),
                    now.isoformat(),
                    selected_id,
                    now.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)
        return self.get_job(selected_id), token

    def _initialize(self) -> None:
        connection = self._connect()
        try:
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
            connection.commit()
        finally:
            self._release(connection)

    @staticmethod
    def _campaign_from_row(row: sqlite3.Row) -> Campaign:
        return Campaign.model_validate(
            {
                "campaign_id": row["campaign_id"],
                "name": row["name"],
                "objective": row["objective"],
                "status": row["status"],
                "mode": row["mode"],
                "cadence_minutes": row["cadence_minutes"],
                "action_delay_minutes": row["action_delay_minutes"],
                "evidence": json.loads(str(row["evidence_json"])),
                "context": json.loads(str(row["context_json"])),
                "research_seed_urls": json.loads(str(row["research_seed_urls_json"])),
                "research_before_plan": bool(row["research_before_plan"]),
                "next_run_at": row["next_run_at"],
                "last_run_at": row["last_run_at"],
                "consecutive_failures": row["consecutive_failures"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> CampaignJob:
        provider_result = (
            json.loads(str(row["provider_result_json"]))
            if row["provider_result_json"] is not None
            else None
        )
        return CampaignJob.model_validate(
            {
                "job_id": row["job_id"],
                "campaign_id": row["campaign_id"],
                "decision_id": row["decision_id"],
                "action": json.loads(str(row["action_json"])),
                "status": row["status"],
                "scheduled_for": row["scheduled_for"],
                "attempt_count": row["attempt_count"],
                "max_attempts": row["max_attempts"],
                "lease_token": row["lease_token"],
                "lease_expires_at": row["lease_expires_at"],
                "last_error": row["last_error"],
                "provider_result": provider_result,
                "outcome_reward": row["outcome_reward"],
                "outcome_note": row["outcome_note"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "completed_at": row["completed_at"],
            }
        )

    def _connect(self) -> sqlite3.Connection:
        if self._database_path == ":memory:":
            if self._memory_connection is None:
                raise RuntimeError("in-memory campaign store is closed")
            return self._memory_connection
        return self._new_connection(self._database_path)

    @staticmethod
    def _new_connection(database_path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if database_path != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _release(self, connection: sqlite3.Connection) -> None:
        if self._database_path != ":memory:":
            connection.close()

    @staticmethod
    def _utc(value: datetime | None = None) -> datetime:
        moment = value or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.astimezone(UTC)

    @classmethod
    def _iso(cls, value: datetime | None) -> str | None:
        return cls._utc(value).isoformat() if value is not None else None
