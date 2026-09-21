import httpx
import respx

from instabotai.providers.instagram import InstagramGraphClient
from instabotai.settings import Settings


def settings() -> Settings:
    return Settings(
        _env_file=None,
        instagram_access_token="secret-token",
        instagram_account_id="17841400000000000",
        provider_max_retries=0,
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
