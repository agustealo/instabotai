"""Reasoning-model adapters for the InstabotAI intelligence subsystem."""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

import httpx

from instabotai.intelligence.domain import IntelligenceProbe, ModelReply
from instabotai.settings import Settings


class IntelligenceProviderError(RuntimeError):
    """Raised when a configured reasoning model cannot return a valid response."""


class JSONReasoningModel(Protocol):
    """Minimal provider contract used by the intelligence engine."""

    @property
    def provider_name(self) -> str:
        """Stable provider identifier."""

    @property
    def model_name(self) -> str:
        """Configured model identifier."""

    async def complete(self, *, system_prompt: str, user_prompt: str) -> ModelReply:
        """Return one model response expected to contain a JSON object."""


class OllamaReasoningModel:
    """Local reasoning adapter for an Ollama server."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=settings.ai_timeout_seconds)

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._settings.ai_model

    async def complete(self, *, system_prompt: str, user_prompt: str) -> ModelReply:
        started = time.monotonic()
        response = await self._client.post(
            self._url("api/chat"),
            json={
                "model": self.model_name,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "options": {"temperature": self._settings.ai_temperature},
            },
        )
        response.raise_for_status()
        payload = _response_object(response)
        message = payload.get("message")
        if not isinstance(message, dict):
            raise IntelligenceProviderError("Ollama response did not include a message object")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise IntelligenceProviderError("Ollama response did not include message content")
        return ModelReply(
            text=content,
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _url(self, path: str) -> str:
        return f"{self._settings.ai_base_url.rstrip('/')}/{path.lstrip('/')}"


class OpenAICompatibleReasoningModel:
    """Reasoning adapter for OpenAI-compatible chat-completions endpoints."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = client is None
        headers = {"Content-Type": "application/json"}
        if settings.ai_api_key is not None:
            headers["Authorization"] = f"Bearer {settings.ai_api_key.get_secret_value()}"
        self._client = client or httpx.AsyncClient(
            timeout=settings.ai_timeout_seconds,
            headers=headers,
        )

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    @property
    def model_name(self) -> str:
        return self._settings.ai_model

    async def complete(self, *, system_prompt: str, user_prompt: str) -> ModelReply:
        started = time.monotonic()
        response = await self._client.post(
            self._url("v1/chat/completions"),
            json={
                "model": self.model_name,
                "temperature": self._settings.ai_temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        response.raise_for_status()
        payload = _response_object(response)
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise IntelligenceProviderError("model response did not include choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise IntelligenceProviderError("model response choice was not an object")
        message = first.get("message")
        if not isinstance(message, dict):
            raise IntelligenceProviderError("model response choice did not include a message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise IntelligenceProviderError("model response did not include message content")
        return ModelReply(
            text=content,
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _url(self, path: str) -> str:
        return f"{self._settings.ai_base_url.rstrip('/')}/{path.lstrip('/')}"


def build_reasoning_model(settings: Settings) -> JSONReasoningModel:
    """Build the configured genuine model adapter."""

    if settings.ai_provider == "ollama":
        return OllamaReasoningModel(settings)
    if settings.ai_provider == "openai_compatible":
        return OpenAICompatibleReasoningModel(settings)
    raise IntelligenceProviderError(f"unsupported AI provider: {settings.ai_provider}")


async def probe_reasoning_model(model: JSONReasoningModel) -> IntelligenceProbe:
    """Perform a genuine structured inference round trip against the configured model."""

    reply = await model.complete(
        system_prompt=(
            "You are a runtime capability probe. Return exactly one JSON object and no prose. "
            "Do not use tools or external data."
        ),
        user_prompt=(
            'Return exactly {"ok":true,"capability":"reasoning"}. '
            "This is a connectivity and structured-output check."
        ),
    )
    payload = parse_json_object(reply.text)
    if payload.get("ok") is not True:
        raise IntelligenceProviderError("reasoning model probe did not confirm ok=true")
    capability = payload.get("capability")
    if not isinstance(capability, str) or not capability.strip():
        raise IntelligenceProviderError("reasoning model probe omitted capability")
    return IntelligenceProbe(
        ok=True,
        capability=capability.strip(),
        provider=reply.provider,
        model=reply.model,
        latency_ms=reply.latency_ms,
    )


def parse_json_object(value: str) -> dict[str, Any]:
    """Extract exactly one JSON object from a model response."""

    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
            if text.lower().startswith("json\n"):
                text = text[5:].strip()
    start = text.find("{")
    if start < 0:
        raise IntelligenceProviderError("model response did not contain a JSON object")
    try:
        parsed, end = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise IntelligenceProviderError(f"model returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise IntelligenceProviderError("model response JSON was not an object")
    trailing = text[start + end :].strip()
    if trailing and not trailing.startswith("```"):
        raise IntelligenceProviderError("model response contained unexpected content after JSON")
    return parsed


def _response_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise IntelligenceProviderError(
            "reasoning provider returned non-JSON HTTP response"
        ) from exc
    if not isinstance(payload, dict):
        raise IntelligenceProviderError("reasoning provider response was not a JSON object")
    return payload
