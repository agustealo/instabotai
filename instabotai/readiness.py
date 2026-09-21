"""Consumer-trial readiness and operator observability checks."""

from __future__ import annotations

import importlib.util
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from instabotai import __version__
from instabotai.intelligence import IntelligenceProbe, build_reasoning_model, probe_reasoning_model
from instabotai.providers import (
    PrivateInstagramProvider,
    PrivateInstagramProviderError,
    build_instagram_provider,
)
from instabotai.settings import Settings
from instabotai.storage import (
    StateSchemaError,
    StateSchemaTooNewError,
    upgrade_state_database,
)

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


def _secret_has_text(value: Any) -> bool:
    """Return whether a secret-like value contains non-whitespace text."""

    if value is None:
        return False
    getter = getattr(value, "get_secret_value", None)
    raw = getter() if callable(getter) else value
    return bool(str(raw).strip())


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
        if database_path == ":memory:":
            return ReadinessCheck(
                key="state",
                label="Durable state",
                status="fail",
                detail="SQLite :memory: state is transient and cannot preserve trial evidence.",
                remediation=(
                    "Set INSTABOTAI_STATE_DB_PATH to a persistent filesystem-backed SQLite file."
                ),
            )

        try:
            report = upgrade_state_database(database_path)
        except StateSchemaTooNewError:
            return ReadinessCheck(
                key="state",
                label="Durable state",
                status="fail",
                detail="SQLite state was created by a newer unsupported schema version.",
                remediation=(
                    "Install a compatible newer InstabotAI build or restore a backup created "
                    "before the newer schema was installed. Do not downgrade this database "
                    "in place."
                ),
            )
        except (StateSchemaError, OSError, sqlite3.Error) as exc:
            return ReadinessCheck(
                key="state",
                label="Durable state",
                status="fail",
                detail=(
                    "SQLite state could not be initialized or upgraded safely "
                    f"({type(exc).__name__})."
                ),
                remediation=(
                    "Run `instabotai state-check`, verify filesystem permissions, and restore the "
                    "latest verified pre-migration backup if integrity is not ok."
                ),
            )

        if not report.ready:
            return ReadinessCheck(
                key="state",
                label="Durable state",
                status="fail",
                detail=(
                    f"SQLite schema v{report.schema_version} is not ready for required "
                    f"v{report.target_version}; integrity={report.integrity}."
                ),
                remediation="Run `instabotai state-upgrade` before the consumer trial.",
            )

        try:
            with sqlite3.connect(database_path, timeout=5.0) as connection:
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
                detail=f"SQLite state is not transactionally writable ({type(exc).__name__}).",
                remediation="Verify INSTABOTAI_STATE_DB_PATH and filesystem permissions.",
            )

        migration_note = (
            " A verified pre-migration backup was created before this readiness check upgraded "
            "existing state."
            if report.backup_path is not None
            else ""
        )
        return ReadinessCheck(
            key="state",
            label="Durable state",
            status="pass",
            detail=(
                f"SQLite schema v{report.schema_version} is current, integrity is ok, and the "
                f"transactional write probe passed.{migration_note}"
            ),
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
            if not (self.settings.instagram_account_id or "").strip():
                missing.append("INSTABOTAI_INSTAGRAM_ACCOUNT_ID")
            if not _secret_has_text(self.settings.instagram_access_token):
                missing.append("INSTABOTAI_INSTAGRAM_ACCESS_TOKEN")
            if missing:
                return ReadinessCheck(
                    key="instagram_configuration",
                    label="Instagram provider configuration",
                    status="fail",
                    detail="Official provider credentials are incomplete.",
                    remediation=f"Configure {', '.join(missing)} with non-empty values.",
                )
            return ReadinessCheck(
                key="instagram_configuration",
                label="Instagram provider configuration",
                status="pass",
                detail="Official Instagram API account ID and access token are configured.",
            )

        package_installed = importlib.util.find_spec("instagrapi") is not None
        private_provider = PrivateInstagramProvider(self.settings)
        try:
            bundle = private_provider._credential_bundle()
            username = str(
                self.settings.private_instagram_username or bundle.get("username") or ""
            ).strip()
            password = private_provider._secret_or_bundle(
                self.settings.private_instagram_password,
                bundle,
                "password",
            )
        except PrivateInstagramProviderError:
            return ReadinessCheck(
                key="instagram_configuration",
                label="Instagram provider configuration",
                status="fail",
                detail="Private provider credential source could not be validated.",
                remediation=(
                    "Use direct username/password settings or a valid authorized research "
                    "credential bundle with private research mode enabled."
                ),
            )

        private_missing: list[str] = []
        if not username:
            private_missing.append("private username")
        if not (password or "").strip():
            private_missing.append("private password")
        if not package_installed:
            private_missing.append("the [private] package extra")
        if private_missing:
            return ReadinessCheck(
                key="instagram_configuration",
                label="Instagram provider configuration",
                status="fail",
                detail="Private provider setup is incomplete.",
                remediation=f"Configure/install {', '.join(private_missing)}.",
            )
        return ReadinessCheck(
            key="instagram_configuration",
            label="Instagram provider configuration",
            status="pass",
            detail=(
                "Private provider login credentials and package extra are configured through "
                "a supported credential source."
            ),
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
