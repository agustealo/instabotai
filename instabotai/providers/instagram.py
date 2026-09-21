"""Official Instagram Graph API provider.

This provider intentionally supports the Instagram API with Instagram Login
instead of emulating the private Android API used by the legacy runtime.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from instabotai.settings import Settings


class InstagramProviderError(RuntimeError):
    """Raised when Instagram rejects or cannot complete a provider request."""


class InstagramGraphClient:
    """Async client for supported Instagram professional-account operations."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if settings.instagram_access_token is None:
            raise ValueError("INSTABOTAI_INSTAGRAM_ACCESS_TOKEN is required")
        if not settings.instagram_account_id:
            raise ValueError("INSTABOTAI_INSTAGRAM_ACCOUNT_ID is required")

        self._settings = settings
        self._token = settings.instagram_access_token.get_secret_value()
        self._account_id = settings.instagram_account_id
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            headers={
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "InstabotAI/2.0",
            },
        )

    async def __aenter__(self) -> InstagramGraphClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_profile(self) -> dict[str, Any]:
        """Return the connected professional account's basic profile metadata."""

        return await self._request(
            "GET",
            self._account_id,
            params={"fields": "id,username,account_type,media_count"},
        )

    async def publish_image(self, image_url: str, caption: str = "") -> str:
        """Create and publish a single-image feed post."""

        container = await self._request(
            "POST",
            f"{self._account_id}/media",
            data={"image_url": image_url, "caption": caption},
        )
        creation_id = str(container.get("id", "")).strip()
        if not creation_id:
            raise InstagramProviderError("Instagram did not return a media container id")

        published = await self._request(
            "POST",
            f"{self._account_id}/media_publish",
            data={"creation_id": creation_id},
        )
        media_id = str(published.get("id", "")).strip()
        if not media_id:
            raise InstagramProviderError("Instagram did not return a published media id")
        return media_id

    async def reply_to_comment(self, comment_id: str, message: str) -> str:
        """Reply to a comment on media owned by the connected account."""

        result = await self._request(
            "POST",
            f"{comment_id}/replies",
            data={"message": message},
        )
        reply_id = str(result.get("id", "")).strip()
        if not reply_id:
            raise InstagramProviderError("Instagram did not return a comment reply id")
        return reply_id

    async def hide_comment(self, comment_id: str, *, hide: bool = True) -> bool:
        """Hide or unhide a comment on media owned by the connected account."""

        result = await self._request(
            "POST",
            comment_id,
            data={"hide": "true" if hide else "false"},
        )
        return bool(result.get("success", False))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = self._url(path)
        last_error: Exception | None = None

        for attempt in range(self._settings.provider_max_retries + 1):
            try:
                response = await self._client.request(
                    method,
                    url,
                    params=params,
                    data=data,
                )
                payload = self._decode_payload(response)

                if 200 <= response.status_code < 300:
                    return payload

                message = self._error_message(payload, response.status_code)
                if response.status_code not in {429, 500, 502, 503, 504}:
                    raise InstagramProviderError(message)
                last_error = InstagramProviderError(message)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc

            if attempt < self._settings.provider_max_retries:
                await asyncio.sleep(min(2**attempt, 8))

        raise InstagramProviderError(
            f"Instagram request failed after retries: {last_error}"
        ) from last_error

    def _url(self, path: str) -> str:
        base = self._settings.meta_graph_base_url.rstrip("/")
        version = self._settings.meta_graph_api_version.strip("/")
        return f"{base}/{version}/{path.lstrip('/')}"

    @staticmethod
    def _decode_payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise InstagramProviderError(
                f"Instagram returned non-JSON HTTP {response.status_code}"
            ) from exc
        if not isinstance(payload, dict):
            raise InstagramProviderError("Instagram returned an unexpected response shape")
        return payload

    @staticmethod
    def _error_message(payload: dict[str, Any], status_code: int) -> str:
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("error_user_msg") or "").strip()
            code = error.get("code")
            if message:
                return f"Instagram HTTP {status_code} code={code}: {message}"
        return f"Instagram HTTP {status_code}"
