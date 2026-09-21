"""Optional unofficial Instagram provider backed by instagrapi.

The adapter supports an explicit research mode for authorized testing. Research
mode can load local operator-owned credentials and client settings, override
common device/request attributes, and record sanitized request metadata. It does
not automate defeating Instagram security, challenge, or anti-abuse controls.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from instabotai.settings import Settings


class PrivateInstagramProviderError(RuntimeError):
    """Raised when the optional private provider cannot complete an operation."""


class PrivateInstagramProvider:
    """Policy-compatible adapter around the maintained ``instagrapi`` client."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client
        self._login_lock = asyncio.Lock()
        self._logged_in = client is not None

    async def get_profile(self) -> dict[str, Any]:
        client = await self._ready_client()
        account = await asyncio.to_thread(client.account_info)
        if hasattr(account, "model_dump"):
            return dict(account.model_dump(mode="json"))
        if hasattr(account, "dict"):
            return dict(account.dict())
        return {
            "username": str(getattr(account, "username", "")),
            "pk": str(getattr(account, "pk", "")),
        }

    async def publish_image(self, image_url: str, caption: str = "") -> str:
        client = await self._ready_client()
        path = await self._download_image(image_url)
        try:
            media = await asyncio.to_thread(client.photo_upload, path, caption)
        finally:
            path.unlink(missing_ok=True)
        media_id = str(getattr(media, "id", "") or getattr(media, "pk", "")).strip()
        if not media_id:
            raise PrivateInstagramProviderError("private provider returned no media id")
        return media_id

    async def reply_to_comment(
        self,
        comment_id: str,
        message: str,
        *,
        media_id: str | None = None,
    ) -> str:
        if not media_id:
            raise PrivateInstagramProviderError(
                "private comment replies require payload.media_id in addition to target_id"
            )
        client = await self._ready_client()
        try:
            replied_to = int(comment_id)
        except ValueError as exc:
            raise PrivateInstagramProviderError("private comment id must be numeric") from exc
        comment = await asyncio.to_thread(
            client.media_comment,
            media_id,
            message,
            replied_to_comment_id=replied_to,
        )
        reply_id = str(getattr(comment, "pk", "")).strip()
        if not reply_id:
            raise PrivateInstagramProviderError("private provider returned no reply id")
        return reply_id

    async def hide_comment(self, comment_id: str, *, hide: bool = True) -> bool:
        raise PrivateInstagramProviderError(
            "comment hide/unhide is not exposed by the selected private provider; "
            "use the official provider"
        )

    async def _ready_client(self) -> Any:
        if self._logged_in and self._client is not None:
            return self._client
        async with self._login_lock:
            if self._logged_in and self._client is not None:
                return self._client
            self._client = await asyncio.to_thread(self._login_sync)
            self._logged_in = True
            return self._client

    def _login_sync(self) -> Any:
        try:
            from instagrapi import Client
        except ImportError as exc:
            raise PrivateInstagramProviderError(
                "private provider is not installed; install instabotai[private]"
            ) from exc

        bundle = self._credential_bundle()
        username = str(
            self._settings.private_instagram_username or bundle.get("username") or ""
        ).strip()
        password = self._secret_or_bundle(
            self._settings.private_instagram_password,
            bundle,
            "password",
        )
        if not username or not password:
            raise PrivateInstagramProviderError(
                "private provider requires username/password via environment or the "
                "authorized research credential bundle"
            )

        session_path = Path(
            str(bundle.get("session_path") or self._settings.private_session_path)
        ).expanduser()
        session_path.parent.mkdir(parents=True, exist_ok=True)
        client = Client()

        if session_path.exists():
            client.load_settings(session_path)

        proxy = self._secret_or_bundle(
            self._settings.private_proxy_url,
            bundle,
            "proxy_url",
        )
        if proxy:
            client.set_proxy(proxy)

        if self._settings.private_research_mode:
            self._configure_research_client(client, bundle)

        try:
            ok = client.login(username, password)
        except Exception as exc:
            raise PrivateInstagramProviderError(
                "private login failed; preserve the same session/device context and complete "
                f"any Instagram verification flow normally: {exc}"
            ) from exc
        if not ok:
            raise PrivateInstagramProviderError("private login was not accepted")

        client.dump_settings(session_path)
        self._restrict_file(session_path)
        return client

    def _configure_research_client(self, client: Any, bundle: dict[str, Any]) -> None:
        device_file = self._settings.private_device_profile_file or self._bundle_text(
            bundle,
            "device_profile_file",
        )
        if device_file:
            device = self._load_json_object(Path(device_file).expanduser(), "device profile")
            client.set_device(device)

        user_agent = self._settings.private_user_agent or self._bundle_text(
            bundle,
            "user_agent",
        )
        if user_agent:
            client.set_user_agent(user_agent)

        headers_file = self._settings.private_headers_file or self._bundle_text(
            bundle,
            "headers_file",
        )
        if headers_file:
            headers = self._load_json_object(Path(headers_file).expanduser(), "headers")
            client.private.headers.update({str(k): str(v) for k, v in headers.items()})

        phone_number = self._settings.private_phone_number or self._bundle_text(
            bundle,
            "phone_number",
        )
        if phone_number:
            client.phone_number = phone_number

        challenge_code = self._secret_or_bundle(
            self._settings.private_challenge_code,
            bundle,
            "challenge_code",
        )
        if challenge_code:
            client.challenge_code_handler = lambda _username, _choice: challenge_code

        replacement_password = self._secret_or_bundle(
            self._settings.private_replacement_password,
            bundle,
            "replacement_password",
        )
        if replacement_password:
            client.change_password_handler = lambda _username: replacement_password

        trace_path = self._settings.private_request_trace_path or self._bundle_text(
            bundle,
            "request_trace_path",
        )
        if trace_path:
            self._attach_request_trace(client, Path(trace_path).expanduser())

    def _credential_bundle(self) -> dict[str, Any]:
        path_value = self._settings.private_credentials_file
        if not path_value:
            return {}
        if not self._settings.private_research_mode:
            raise PrivateInstagramProviderError(
                "private credential files require INSTABOTAI_PRIVATE_RESEARCH_MODE=true"
            )
        return self._load_json_object(Path(path_value).expanduser(), "credential bundle")

    @staticmethod
    def _load_json_object(path: Path, label: str) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PrivateInstagramProviderError(f"could not load {label} from {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise PrivateInstagramProviderError(f"{label} must contain a JSON object")
        return raw

    @staticmethod
    def _bundle_text(bundle: dict[str, Any], key: str) -> str | None:
        value = bundle.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise PrivateInstagramProviderError(f"credential bundle field {key!r} must be text")
        return value.strip() or None

    def _secret_or_bundle(
        self,
        secret: Any,
        bundle: dict[str, Any],
        key: str,
    ) -> str | None:
        if secret is not None:
            return str(secret.get_secret_value())
        return self._bundle_text(bundle, key)

    def _attach_request_trace(self, client: Any, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        original = client.request_log

        def traced(response: Any) -> None:
            original(response)
            request = getattr(response, "request", None)
            record = {
                "at": datetime.now(UTC).isoformat(),
                "method": str(getattr(request, "method", "")),
                "url": self._sanitize_url(str(getattr(response, "url", ""))),
                "status": int(getattr(response, "status_code", 0) or 0),
            }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            self._restrict_file(path)

        client.request_log = traced

    @staticmethod
    def _sanitize_url(value: str) -> str:
        parsed = urlparse(value)
        sensitive = {
            "access_token",
            "token",
            "password",
            "sessionid",
            "csrftoken",
            "authorization",
        }
        query = [
            (key, "[redacted]" if key.lower() in sensitive else val)
            for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        ]
        return urlunparse(parsed._replace(query=urlencode(query)))

    @staticmethod
    def _restrict_file(path: Path) -> None:
        try:
            path.chmod(0o600)
        except OSError:
            pass

    async def _download_image(self, image_url: str) -> Path:
        await self._assert_public_http_url(image_url)
        limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
        async with httpx.AsyncClient(
            timeout=self._settings.request_timeout_seconds,
            follow_redirects=True,
            limits=limits,
        ) as client:
            async with client.stream("GET", image_url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in {"image/jpeg", "image/jpg"}:
                    raise PrivateInstagramProviderError(
                        f"private photo publishing requires JPEG; "
                        f"received {content_type or 'unknown'}"
                    )
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as handle:
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._settings.private_image_max_bytes:
                            raise PrivateInstagramProviderError(
                                "image exceeds configured download size limit"
                            )
                        handle.write(chunk)
                    return Path(handle.name)

    @staticmethod
    async def _assert_public_http_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise PrivateInstagramProviderError("image_url must be an absolute http(s) URL")
        host = parsed.hostname.lower()
        if host == "localhost" or host.endswith(".localhost"):
            raise PrivateInstagramProviderError("local image hosts are not allowed")

        def resolve() -> list[str]:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            return list(
                {
                    item[4][0]
                    for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                }
            )

        try:
            addresses = await asyncio.to_thread(resolve)
        except OSError as exc:
            raise PrivateInstagramProviderError(f"could not resolve image host: {host}") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                raise PrivateInstagramProviderError("image_url resolved to a non-public address")
