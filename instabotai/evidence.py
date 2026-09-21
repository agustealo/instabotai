"""Secret-free, tamper-evident evidence bundles for supervised consumer trials."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, SecretStr

from instabotai import __version__
from instabotai.campaigns import CampaignStore
from instabotai.intelligence import DecisionJournal
from instabotai.readiness import ConsumerTrialReadiness, ConsumerTrialReadinessService
from instabotai.settings import Settings
from instabotai.state import ActionLedger
from instabotai.storage import inspect_state_database

EVIDENCE_FORMAT_VERSION = 1
_REDACTED = "[redacted]"
_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:access[_-]?token|token|password|passwd|secret|api[_-]?key|"
    r"authorization|cookie|session|credential|challenge[_-]?code|replacement[_-]?password|"
    r"proxy[_-]?url|phone(?:[_-]?number)?)(?:$|[_-])",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


class TrialEvidenceError(RuntimeError):
    """Raised when a requested consumer-trial evidence bundle cannot be assembled."""


class TrialEvidenceRuntime(BaseModel):
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


class EvidenceIntegrity(BaseModel):
    """Content digest for detecting changes to an exported bundle."""

    algorithm: str = "sha256"
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    signed: bool = False


class TrialEvidenceBundle(BaseModel):
    """One reviewable evidence snapshot for a durable campaign job."""

    format_version: int = EVIDENCE_FORMAT_VERSION
    bundle_id: str = Field(default_factory=lambda: uuid4().hex, min_length=16, max_length=64)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    job_id: str
    runtime: TrialEvidenceRuntime
    readiness: ConsumerTrialReadiness
    campaign: dict[str, Any]
    job: dict[str, Any]
    decision: dict[str, Any]
    action_ledger: dict[str, Any] | None
    usage_snapshot: dict[str, Any]
    integrity: EvidenceIntegrity


class EvidenceVerification(BaseModel):
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

        schema = inspect_state_database(self.settings.state_db_path)
        if not schema.ready:
            raise TrialEvidenceError(
                "durable state is not current and healthy; run `instabotai state-check` "
                "and `instabotai state-upgrade` before exporting trial evidence"
            )

        store = CampaignStore(self.settings.state_db_path)
        journal = DecisionJournal(self.settings.state_db_path)
        ledger = ActionLedger(self.settings.state_db_path)
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

        readiness = await ConsumerTrialReadinessService(self.settings).evaluate(
            live=live,
            require_research=require_research,
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
        digest = _content_digest(content)
        return TrialEvidenceBundle(
            **content,
            integrity=EvidenceIntegrity(digest=digest),
        )

    def _sanitize(self, value: Any, *, key: str | None = None) -> Any:
        if key is not None and _SENSITIVE_KEY.search(key):
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
    """Recompute a bundle digest; this detects changes but is not a signature."""

    payload = bundle.model_dump(mode="json", exclude={"integrity"})
    actual = _content_digest(payload)
    return EvidenceVerification(
        valid=(bundle.integrity.algorithm == "sha256" and actual == bundle.integrity.digest),
        algorithm=bundle.integrity.algorithm,
        expected_digest=bundle.integrity.digest,
        actual_digest=actual,
        bundle_id=bundle.bundle_id,
        job_id=bundle.job_id,
    )


def load_evidence_bundle(path: Path) -> TrialEvidenceBundle:
    """Load and validate the typed structure of an evidence JSON file."""

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
