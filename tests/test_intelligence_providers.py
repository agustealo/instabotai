import json

import httpx

from instabotai.intelligence import (
    OllamaReasoningModel,
    OpenAICompatibleReasoningModel,
    probe_reasoning_model,
)
from instabotai.settings import Settings


async def test_ollama_adapter_uses_real_chat_contract_and_structured_probe() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://ollama.test/api/chat"
        payload = json.loads(request.content)
        assert payload["model"] == "reasoning-model"
        assert payload["stream"] is False
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][1]["role"] == "user"
        return httpx.Response(
            200,
            json={"message": {"content": '{"ok":true,"capability":"reasoning"}'}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OllamaReasoningModel(
        Settings(
            _env_file=None,
            ai_provider="ollama",
            ai_model="reasoning-model",
            ai_base_url="http://ollama.test",
        ),
        client=client,
    )
    try:
        probe = await probe_reasoning_model(model)
    finally:
        await client.aclose()

    assert probe.ok is True
    assert probe.provider == "ollama"
    assert probe.model == "reasoning-model"
    assert probe.capability == "reasoning"


async def test_openai_compatible_adapter_sends_auth_and_chat_completion_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://model.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer model-secret"
        payload = json.loads(request.content)
        assert payload["model"] == "hosted-reasoner"
        assert payload["messages"][0] == {"role": "system", "content": "system"}
        assert payload["messages"][1] == {"role": "user", "content": "user"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"answer":"grounded"}'}}
                ]
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer model-secret"},
    )
    model = OpenAICompatibleReasoningModel(
        Settings(
            _env_file=None,
            ai_provider="openai_compatible",
            ai_model="hosted-reasoner",
            ai_base_url="https://model.test",
            ai_api_key="model-secret",
        ),
        client=client,
    )
    try:
        reply = await model.complete(system_prompt="system", user_prompt="user")
    finally:
        await client.aclose()

    assert reply.provider == "openai_compatible"
    assert reply.model == "hosted-reasoner"
    assert json.loads(reply.text) == {"answer": "grounded"}


async def test_model_adapter_propagates_http_failure_instead_of_mock_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "model unavailable"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OllamaReasoningModel(
        Settings(
            _env_file=None,
            ai_provider="ollama",
            ai_model="reasoning-model",
            ai_base_url="http://ollama.test",
        ),
        client=client,
    )
    try:
        try:
            await model.complete(system_prompt="system", user_prompt="user")
        except httpx.HTTPStatusError as exc:
            assert exc.response.status_code == 503
        else:
            raise AssertionError("provider must not fabricate an AI response after HTTP failure")
    finally:
        await client.aclose()
