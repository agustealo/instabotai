"""Secret-free, tamper-evident evidence bundles for supervised consumer trials."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from instabotai import __version__
from instabotai.campaigns import CampaignStore
from instabotai.intelligence import DecisionJournal
from instabotai.readiness import ConsumerTrialReadinessService
from instabotai.settings import Settings
from instabotai.state import ActionLedger
from instabotai.storage import inspect_state_database

EVIDENCE_FORMAT_VERSION: Literal[2] = 2
_REDACTED = "[redacted]"
_SENSITIVE_KEY_MARKERS = (
    "accesstoken",
    "refreshtoken",
    "token",
    "password",
    "passwd",
    "secret",
    "apikey",
    "clientsecret",
    "authorization",
    "cookie",
    "session",
    "credential",
    "challengecode",
    "replacementpassword",
    "proxyurl",
    "phonenumber",
    "phone",
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


class TrialEvidenceError(RuntimeError):
    """Raised when a requested consumer-trial evidence bundle cannot be assembled."""


class StrictEvidenceModel(BaseModel):
    """Evidence models reject fields that are not part of the accepted document."""

    model_config = ConfigDict(extra="forbid")


class TrialEvidenceReadinessCheck(StrictEvidenceModel):
    """Strict copy of one readiness check embedded in exported evidence."""

    key: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=160)
    status: Literal["pass", "warn", "fail", "skip"]
    required: bool = True
    detail: str = Field(min_length=1, max_length=2_000)
    remediation: str | None = Field(default=None, max_length=2_000)


class TrialEvidenceReadiness(StrictEvidenceModel):
    """Strict readiness projection embedded in evidence bundles."""

    version: str
    environment: str
    generated_at: datetime
    live_probes: bool
    research_required: bool
    ready: bool
    checks: tuple[TrialEvidenceReadinessCheck, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


class TrialEvidenceRuntime(StrictEvidenceModel):
    """Secret-free runtime identity and policy configuration recorded with a bundle."""

    app_version: str
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment: str
    state_schema_version: int
    state_schema_target: int
    state_integrity: str
    ai_provider: str
    ai_model: str
    instagram_provider: str
    graph_api_version: str
    write_approval_required: bool
    write_confidence_threshold: float
    daily_publish_limit: int
    daily_comment_reply_limit: int
    daily_comment_moderation_limit: int


class EvidenceIntegrity(StrictEvidenceModel):
    """Content digest for detecting changes to an exported bundle."""

    algorithm: Literal["sha256"] = "sha256"
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    signed: Literal[False] = False


class TrialEvidenceBundle(StrictEvidenceModel):
    """One reviewable evidence snapshot for a durable campaign job."""

    format_version: Literal[1, 2] = EVIDENCE_FORMAT_VERSION
    bundle_id: str = Field(default_factory=lambda: uuid4().hex, min_length=16, max_length=64)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    job_id: str
    runtime: TrialEvidenceRuntime
    readiness: TrialEvidenceReadiness
    campaign: dict[str, Any]
    job: dict[str, Any]
    decision: dict[str, Any]
    action_ledger: dict[str, Any] | None
    usage_snapshot: dict[str, Any]
    integrity: EvidenceIntegrity


class EvidenceVerification(StrictEvidenceModel):
    """Result of validating a bundle's content digest."""

    valid: bool
    algorithm: str
    expected_digest: str
    actual_digest: str
    bundle_id: str
    job_id: str


class TrialEvidenceService:
    """Build review-only evidence from the existing durable authorities."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._secret_values = _configured_secret_values(settings)

    async def build(
        self,
        job_id: str,
        *,
        live: bool = False,
        require_research: bool = False,
    ) -> TrialEvidenceBundle:
        """Build one sanitized evidence bundle without approving or executing work."""

        source_schema = inspect_state_database(self.settings.state_db_path)
        if not source_schema.ready:
            raise TrialEvidenceError(
                "durable state is not current and healthy; run `instabotai state-check` "
                "and `instabotai state-upgrade` before exporting trial evidence"
            )

        with _state_snapshot(self.settings.state_db_path) as snapshot_path:
            schema = inspect_state_database(snapshot_path)
            if not schema.ready:
                raise TrialEvidenceError(
                    "durable state snapshot failed schema/integrity validation"
                )

            store = CampaignStore(snapshot_path)
            journal = DecisionJournal(snapshot_path)
            ledger = ActionLedger(snapshot_path)
            try:
                try:
                    job = store.get_job(job_id)
                    campaign = store.get_campaign(job.campaign_id)
                except (LookupError, RuntimeError) as exc:
                    raise TrialEvidenceError(f"campaign job {job_id!r} was not found") from exc

                decision = journal.get(job.decision_id)
                if decision is None:
                    raise TrialEvidenceError(
                        f"AI decision {job.decision_id!r} referenced by job {job_id!r} is missing"
                    )
                action_record = ledger.get_record(job.action.idempotency_key)
                usage = ledger.usage_snapshot()
            finally:
                ledger.close()
                journal.close()
                store.close()

        readiness_report = await ConsumerTrialReadinessService(self.settings).evaluate(
            live=live,
            require_research=require_research,
        )
        readiness = TrialEvidenceReadiness.model_validate(
            readiness_report.model_dump(mode="json")
        )
        runtime = TrialEvidenceRuntime(
            app_version=__version__,
            package_sha256=package_fingerprint(),
            environment=self.settings.environment,
            state_schema_version=schema.schema_version,
            state_schema_target=schema.target_version,
            state_integrity=schema.integrity,
            ai_provider=self.settings.ai_provider,
            ai_model=self.settings.ai_model,
            instagram_provider=self.settings.instagram_provider,
            graph_api_version=self.settings.meta_graph_api_version,
            write_approval_required=self.settings.require_write_approval,
            write_confidence_threshold=self.settings.write_confidence_threshold,
            daily_publish_limit=self.settings.daily_publish_limit,
            daily_comment_reply_limit=self.settings.daily_comment_reply_limit,
            daily_comment_moderation_limit=self.settings.daily_comment_moderation_limit,
        )

        content = {
            "format_version": EVIDENCE_FORMAT_VERSION,
            "bundle_id": uuid4().hex,
            "generated_at": datetime.now(UTC),
            "job_id": job_id,
            "runtime": runtime,
            "readiness": readiness,
            "campaign": self._sanitize(campaign.model_dump(mode="json")),
            "job": self._sanitize(job.model_dump(mode="json")),
            "decision": self._sanitize(decision.model_dump(mode="json")),
            "action_ledger": (
                self._sanitize(action_record.model_dump(mode="json"))
                if action_record is not None
                else None
            ),
            "usage_snapshot": self._sanitize(usage.model_dump(mode="json")),
        }
        integrity_metadata = {"algorithm": "sha256", "signed": False}
        digest = _content_digest({**content, "integrity": integrity_metadata})
        return TrialEvidenceBundle(
            **content,
            integrity=EvidenceIntegrity(digest=digest),
        )

    def _sanitize(self, value: Any, *, key: str | None = None) -> Any:
        if key is not None and _is_sensitive_key(key):
            return _REDACTED
        if isinstance(value, SecretStr):
            return _REDACTED
        if isinstance(value, dict):
            return {
                str(item_key): self._sanitize(item_value, key=str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, (list, tuple, set, frozenset)):
            return [self._sanitize(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, str):
            result = _BEARER.sub(f"Bearer {_REDACTED}", value)
            for secret in self._secret_values:
                if secret and secret in result:
                    result = result.replace(secret, _REDACTED)
            return result
        return value


def package_fingerprint() -> str:
    """Return a deterministic digest of the installed InstabotAI package payload."""

    package_root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    files = sorted(
        path
        for path in package_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    for path in files:
        relative = path.relative_to(package_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def verify_evidence_bundle(bundle: TrialEvidenceBundle) -> EvidenceVerification:
    """Recompute the digest according to the bundle's declared format version."""

    payload = bundle.model_dump(mode="json")
    integrity = dict(payload["integrity"])
    expected = str(integrity.pop("digest"))
    if bundle.format_version == 1:
        payload.pop("integrity")
    else:
        payload["integrity"] = integrity
    actual = _content_digest(payload)
    return EvidenceVerification(
        valid=(
            bundle.integrity.algorithm == "sha256"
            and bundle.integrity.signed is False
            and actual == expected
        ),
        algorithm=bundle.integrity.algorithm,
        expected_digest=expected,
        actual_digest=actual,
        bundle_id=bundle.bundle_id,
        job_id=bundle.job_id,
    )


def load_evidence_bundle(path: Path) -> TrialEvidenceBundle:
    """Load and strictly validate the typed structure of an evidence JSON file."""

    try:
        return TrialEvidenceBundle.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TrialEvidenceError(f"could not load trial evidence from {path}: {exc}") from exc


def write_evidence_bundle(bundle: TrialEvidenceBundle, path: Path) -> Path:
    """Atomically write a bundle and restrict its permissions where supported."""

    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = bundle.model_dump_json(indent=2)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        with suppress(OSError):
            temporary.chmod(0o600)
        os.replace(temporary, destination)
        with suppress(OSError):
            destination.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


@contextmanager
def _state_snapshot(database_path: str) -> Iterator[str]:
    """Create one SQLite backup snapshot for all durable evidence projections."""

    if database_path == ":memory:":
        raise TrialEvidenceError("consumer-trial evidence requires filesystem-backed durable state")

    source_path = Path(database_path).expanduser().resolve()
    if not source_path.is_file():
        raise TrialEvidenceError(f"durable state database does not exist: {source_path}")

    with tempfile.TemporaryDirectory(prefix="instabotai-evidence-") as directory:
        snapshot_path = Path(directory) / "state.sqlite3"
        source: sqlite3.Connection | None = None
        destination: sqlite3.Connection | None = None
        try:
            source = sqlite3.connect(str(source_path), timeout=5.0)
            destination = sqlite3.connect(str(snapshot_path), timeout=5.0)
            source.backup(destination)
            destination.commit()
        except (OSError, sqlite3.Error) as exc:
            raise TrialEvidenceError(
                f"could not create a consistent durable-state snapshot ({type(exc).__name__})"
            ) from exc
        finally:
            if destination is not None:
                destination.close()
            if source is not None:
                source.close()

        with suppress(OSError):
            snapshot_path.chmod(0o600)
        yield str(snapshot_path)


def _configured_secret_values(settings: Settings) -> tuple[str, ...]:
    values: list[str] = []
    for value in (
        settings.ai_api_key,
        settings.instagram_access_token,
        settings.private_instagram_password,
        settings.private_proxy_url,
        settings.private_challenge_code,
        settings.private_replacement_password,
    ):
        if value is None:
            continue
        raw = value.get_secret_value().strip()
        if raw:
            values.append(raw)
    return tuple(dict.fromkeys(values))


def _is_sensitive_key(key: str) -> bool:
    """Match credential-like keys across snake, kebab, camel, and Pascal casing."""

    normalized = re.sub(r"[^a-z0-9]+", "", key.casefold())
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def _content_digest(value: Any) -> str:
    canonical = json.dumps(
        _json_ready(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_ready(value.model_dump(mode="json"))
    if isinstance(value, datetime):
        encoded = value.isoformat()
        return f"{encoded[:-6]}Z" if encoded.endswith("+00:00") else encoded
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_ready(item) for item in value]
    return value
