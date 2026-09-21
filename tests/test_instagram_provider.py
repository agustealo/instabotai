import httpx
import pytest
import respx

from instabotai.automation import AmbiguousWriteError
from instabotai.providers.instagram import InstagramGraphClient, InstagramProviderError
from instabotai.settings import Settings


def settings(*, provider_max_retries: int = 0) -> Settings:
    return Settings(
        _env_file=None,
        instagram_access_token="secret-token",
        instagram_account_id="17841400000000000",
        provider_max_retries=provider_max_retries,
    )


@respx.mock
async def test_get_profile_uses_bearer_auth_and_v26_endpoint() -> None:
    route = respx.get(
        "https://graph.instagram.com/v26.0/17841400000000000",
        params={"fields": "id,username,account_type,media_count"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={"id": "17841400000000000", "username": "brand"},
        )
    )

    async with InstagramGraphClient(settings()) as client:
        profile = await client.get_profile()

    assert profile["username"] == "brand"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer secret-token"
    assert "access_token" not in str(request.url)


@respx.mock
async def test_publish_image_uses_two_phase_media_publish_flow() -> None:
    respx.post(
        "https://graph.instagram.com/v26.0/17841400000000000/media"
    ).mock(return_value=httpx.Response(200, json={"id": "container-1"}))
    respx.post(
        "https://graph.instagram.com/v26.0/17841400000000000/media_publish"
    ).mock(return_value=httpx.Response(200, json={"id": "media-1"}))

    async with InstagramGraphClient(settings()) as client:
        media_id = await client.publish_image(
            "https://cdn.example.com/asset.jpg",
            "Launch day",
        )

    assert media_id == "media-1"


async def test_safe_get_retries_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("transient read timeout", request=request)
        return httpx.Response(
            200,
            json={"id": "17841400000000000", "username": "brand"},
            request=request,
        )

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("instabotai.providers.instagram.asyncio.sleep", no_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = InstagramGraphClient(
            settings(provider_max_retries=2),
            client=http_client,
        )
        profile = await client.get_profile()

    assert profile["username"] == "brand"
    assert calls == 2


async def test_post_transport_failure_is_ambiguous_and_never_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("outcome unknown", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = InstagramGraphClient(
            settings(provider_max_retries=5),
            client=http_client,
        )
        with pytest.raises(AmbiguousWriteError, match="automatic replay is blocked"):
            await client.reply_to_comment("comment-1", "Thanks")

    assert calls == 1


async def test_post_server_failure_is_ambiguous_and_never_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            json={"error": {"message": "temporary upstream failure", "code": 2}},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = InstagramGraphClient(
            settings(provider_max_retries=5),
            client=http_client,
        )
        with pytest.raises(AmbiguousWriteError, match="write outcome is unknown"):
            await client.reply_to_comment("comment-1", "Thanks")

    assert calls == 1


async def test_explicit_rate_limit_post_is_retryable_at_outer_action_layer() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            json={"error": {"message": "rate limited", "code": 4}},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = InstagramGraphClient(
            settings(provider_max_retries=5),
            client=http_client,
        )
        with pytest.raises(InstagramProviderError, match="rate limited"):
            await client.reply_to_comment("comment-1", "Thanks")

    assert calls == 1
