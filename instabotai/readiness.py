"""Consumer-trial readiness and operator observability checks."""

from __future__ import annotations

import importlib.util
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from instabotai import __version__
from instabotai.intelligence import IntelligenceProbe, build_reasoning_model, probe_reasoning_model
from instabotai.providers import build_instagram_provider
from instabotai.settings import Settings

ReadinessStatus = Literal["pass", "warn", "fail", "skip"]
AIProbe = Callable[[], Awaitable[IntelligenceProbe]]
ProfileProbe = Callable[[], Awaitable[dict[str, Any]]]


class ReadinessCheck(BaseModel):
    """One secret-free readiness assertion."""

    key: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=160)
    status: ReadinessStatus
    required: bool = True
    detail: str = Field(min_length=1, max_length=2_000)
    remediation: str | None = Field(default=None, max_length=2_000)


class ConsumerTrialReadiness(BaseModel):
    """Canonical readiness report shared by operator surfaces."""

    version: str
    environment: str
    generated_at: datetime
    live_probes: bool
    research_required: bool
    ready: bool
    checks: tuple[ReadinessCheck, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


async def _close_resource(resource: Any) -> None:
    closer = getattr(resource, "aclose", None)
    if closer is not None:
        await closer()


class ConsumerTrialReadinessService:
    """Evaluate whether the current install is ready for controlled consumer trials."""

    def __init__(
        self,
        settings: Settings,
        *,
        ai_probe: AIProbe | None = None,
        profile_probe: ProfileProbe | None = None,
    ) -> None:
        self.settings = settings
        self._ai_probe = ai_probe or self._probe_ai
        self._profile_probe = profile_probe or self._probe_profile

    async def evaluate(
        self,
        *,
        live: bool = False,
        require_research: bool = False,
    ) -> ConsumerTrialReadiness:
        checks = [
            self._runtime_check(),
            self._state_check(),
            self._ai_configuration_check(),
            self._instagram_configuration_check(),
            self._research_check(required=require_research),
            self._write_approval_check(),
            self._write_capacity_check(),
        ]

        if live:
            checks.append(await self._live_ai_check())
            checks.append(await self._live_instagram_check())
        else:
            checks.extend(
                (
                    ReadinessCheck(
                        key="ai_live",
                        label="Live AI probe",
                        status="skip",
                        required=False,
                        detail=(
                            "Not requested. Run trial-readiness --live for a real model "
                            "round trip."
                        ),
                    ),
                    ReadinessCheck(
                        key="instagram_live",
                        label="Live Instagram read",
                        status="skip",
                        required=False,
                        detail=(
                            "Not requested. Run trial-readiness --live for a read-only "
                            "profile probe."
                        ),
                    ),
                )
            )

        blockers = tuple(
            check.label
            for check in checks
            if check.required and check.status == "fail"
        )
        warnings = tuple(check.label for check in checks if check.status == "warn")
        return ConsumerTrialReadiness(
            version=__version__,
            environment=self.settings.environment,
            generated_at=datetime.now(UTC),
            live_probes=live,
            research_required=require_research,
            ready=not blockers,
            checks=tuple(checks),
            blockers=blockers,
            warnings=warnings,
        )

    def _runtime_check(self) -> ReadinessCheck:
        return ReadinessCheck(
            key="runtime",
            label="Installed runtime",
            status="pass",
            detail=f"InstabotAI {__version__} on the canonical Python package entrypoint.",
        )

    def _state_check(self) -> ReadinessCheck:
        database_path = self.settings.state_db_path
        try:
            if database_path != ":memory:":
                path = Path(database_path).expanduser()
                path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(database_path, timeout=5.0) as connection:
                row = connection.execute("PRAGMA quick_check").fetchone()
                if row is None or str(row[0]).lower() != "ok":
                    return ReadinessCheck(
                        key="state",
                        label="Durable state",
                        status="fail",
                        detail="SQLite integrity check did not return ok.",
                        remediation=(
                            "Repair or replace the configured state database before a trial."
                        ),
                    )
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "CREATE TEMP TABLE instabotai_readiness_probe (value INTEGER NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO instabotai_readiness_probe(value) VALUES (1)"
                )
                connection.rollback()
        except (OSError, sqlite3.Error) as exc:
            return ReadinessCheck(
                key="state",
                label="Durable state",
                status="fail",
                detail=f"SQLite state is not healthy and writable ({type(exc).__name__}).",
                remediation="Verify INSTABOTAI_STATE_DB_PATH and filesystem permissions.",
            )
        return ReadinessCheck(
            key="state",
            label="Durable state",
            status="pass",
            detail=f"SQLite integrity and transactional write probe passed at {database_path}.",
        )

    def _ai_configuration_check(self) -> ReadinessCheck:
        provider = self.settings.ai_provider
        detail = f"{provider} / {self.settings.ai_model} at {self.settings.ai_base_url}."
        return ReadinessCheck(
            key="ai_configuration",
            label="AI configuration",
            status="pass",
            detail=detail,
        )

    def _instagram_configuration_check(self) -> ReadinessCheck:
        if self.settings.instagram_provider == "official":
            missing: list[str] = []
            if not self.settings.instagram_account_id:
                missing.append("INSTABOTAI_INSTAGRAM_ACCOUNT_ID")
            if self.settings.instagram_access_token is None:
                missing.append("INSTABOTAI_INSTAGRAM_ACCESS_TOKEN")
            if missing:
                return ReadinessCheck(
                    key="instagram_configuration",
                    label="Instagram provider configuration",
                    status="fail",
                    detail="Official provider credentials are incomplete.",
                    remediation=f"Configure {', '.join(missing)}.",
                )
            return ReadinessCheck(
                key="instagram_configuration",
                label="Instagram provider configuration",
                status="pass",
                detail="Official Instagram API account ID and access token are configured.",
            )

        missing = []
        if not self.settings.private_instagram_username:
            missing.append("INSTABOTAI_PRIVATE_INSTAGRAM_USERNAME")
        if self.settings.private_instagram_password is None:
            missing.append("INSTABOTAI_PRIVATE_INSTAGRAM_PASSWORD")
        if importlib.util.find_spec("instagrapi") is None:
            missing.append("the [private] package extra")
        if missing:
            return ReadinessCheck(
                key="instagram_configuration",
                label="Instagram provider configuration",
                status="fail",
                detail="Private provider setup is incomplete.",
                remediation=f"Configure/install {', '.join(missing)}.",
            )
        return ReadinessCheck(
            key="instagram_configuration",
            label="Instagram provider configuration",
            status="pass",
            detail="Private provider credentials and package extra are configured.",
        )

    @staticmethod
    def _research_check(*, required: bool) -> ReadinessCheck:
        installed = importlib.util.find_spec("crawl4ai") is not None
        if installed:
            return ReadinessCheck(
                key="research",
                label="Research capability",
                status="pass",
                required=required,
                detail="Crawl4AI research package is installed.",
            )
        return ReadinessCheck(
            key="research",
            label="Research capability",
            status="fail" if required else "warn",
            required=required,
            detail="Crawl4AI research package is not installed.",
            remediation="Install InstabotAI with the [research] extra before research trials.",
        )

    def _write_approval_check(self) -> ReadinessCheck:
        if self.settings.require_write_approval:
            return ReadinessCheck(
                key="write_approval",
                label="Write approval guardrail",
                status="pass",
                detail="Human approval is globally required before consumer-trial writes.",
            )
        return ReadinessCheck(
            key="write_approval",
            label="Write approval guardrail",
            status="fail",
            detail="Global write approval is disabled.",
            remediation=(
                "Set INSTABOTAI_REQUIRE_WRITE_APPROVAL=true for supervised consumer trials."
            ),
        )

    def _write_capacity_check(self) -> ReadinessCheck:
        limits = (
            self.settings.daily_publish_limit,
            self.settings.daily_comment_reply_limit,
            self.settings.daily_comment_moderation_limit,
        )
        if not any(limit > 0 for limit in limits):
            return ReadinessCheck(
                key="write_capacity",
                label="Controlled write capacity",
                status="fail",
                detail="All configured daily write limits are zero.",
                remediation="Enable only the action limits required for the planned trial.",
            )
        return ReadinessCheck(
            key="write_capacity",
            label="Controlled write capacity",
            status="pass",
            detail=(
                "Daily limits are enabled: "
                f"publish={limits[0]}, replies={limits[1]}, moderation={limits[2]}."
            ),
        )

    async def _live_ai_check(self) -> ReadinessCheck:
        try:
            probe = await self._ai_probe()
        except Exception as exc:
            return ReadinessCheck(
                key="ai_live",
                label="Live AI probe",
                status="fail",
                detail=f"Live model probe failed ({type(exc).__name__}).",
                remediation="Verify the configured model server, model ID, and network access.",
            )
        if not probe.ok:
            return ReadinessCheck(
                key="ai_live",
                label="Live AI probe",
                status="fail",
                detail=f"{probe.provider} / {probe.model} returned a failed probe.",
                remediation="Verify the configured reasoning model before a trial.",
            )
        return ReadinessCheck(
            key="ai_live",
            label="Live AI probe",
            status="pass",
            detail=(
                f"{probe.provider} / {probe.model} completed a genuine reasoning probe "
                f"in {probe.latency_ms} ms."
            ),
        )

    async def _live_instagram_check(self) -> ReadinessCheck:
        configured = self._instagram_configuration_check()
        if configured.status == "fail":
            return ReadinessCheck(
                key="instagram_live",
                label="Live Instagram read",
                status="skip",
                required=True,
                detail="Live provider read was not attempted because provider setup is incomplete.",
                remediation=configured.remediation,
            )
        try:
            profile = await self._profile_probe()
        except Exception as exc:
            return ReadinessCheck(
                key="instagram_live",
                label="Live Instagram read",
                status="fail",
                detail=f"Read-only profile probe failed ({type(exc).__name__}).",
                remediation="Verify provider credentials, account access, and platform status.",
            )
        identity = profile.get("username") or profile.get("id")
        if not identity:
            return ReadinessCheck(
                key="instagram_live",
                label="Live Instagram read",
                status="fail",
                detail="Provider returned a profile without an account identity.",
                remediation="Verify that the configured account can be read by the provider.",
            )
        return ReadinessCheck(
            key="instagram_live",
            label="Live Instagram read",
            status="pass",
            detail="Configured provider completed a real read-only account profile request.",
        )

    async def _probe_ai(self) -> IntelligenceProbe:
        model = build_reasoning_model(self.settings)
        try:
            return await probe_reasoning_model(model)
        finally:
            await _close_resource(model)

    async def _probe_profile(self) -> dict[str, Any]:
        provider = build_instagram_provider(self.settings)
        try:
            result: Any = await provider.get_profile()
            if not isinstance(result, dict):
                raise RuntimeError("Instagram provider returned a non-object profile")
            return {str(key): value for key, value in result.items()}
        finally:
            await _close_resource(provider)
