"""Optional unofficial Instagram provider backed by instagrapi.

This adapter exists for users who want a quick-start path without Meta app
registration. It remains isolated behind the canonical automation policy and
action ledger. It does not attempt to bypass challenges, throttles, or account
safety responses.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
        return {"username": str(getattr(account, "username", "")), "pk": str(getattr(account, "pk", ""))}

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
            "comment hide/unhide is not exposed by the selected private provider; use the official provider"
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
        username = (self._settings.private_instagram_username or "").strip()
        password_secret = self._settings.private_instagram_password
        if not username or password_secret is None:
            raise PrivateInstagramProviderError(
                "private provider requires INSTABOTAI_PRIVATE_INSTAGRAM_USERNAME and "
                "INSTABOTAI_PRIVATE_INSTAGRAM_PASSWORD"
            )

        try:
            from instagrapi import Client
        except ImportError as exc:
            raise PrivateInstagramProviderError(
                "private provider is not installed; install instabotai[private]"
            ) from exc

        session_path = Path(self._settings.private_session_path).expanduser()
        session_path.parent.mkdir(parents=True, exist_ok=True)
        client = Client()
        proxy = self._settings.private_proxy_url
        if proxy is not None:
            client.set_proxy(proxy.get_secret_value())
        if session_path.exists():
            client.load_settings(session_path)

        try:
            ok = client.login(username, password_secret.get_secret_value())
        except Exception as exc:
            raise PrivateInstagramProviderError(
                f"private login failed; resolve Instagram verification/challenge normally: {exc}"
            ) from exc
        if not ok:
            raise PrivateInstagramProviderError("private login was not accepted")

        client.dump_settings(session_path)
        try:
            session_path.chmod(0o600)
        except OSError:
            pass
        return client

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
                        f"private photo publishing requires JPEG; received {content_type or 'unknown'}"
                    )
                suffix = ".jpg"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._settings.private_image_max_bytes:
                            raise PrivateInstagramProviderError("image exceeds configured download size limit")
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
            return list({item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)})

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
