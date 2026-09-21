from dataclasses import dataclass

import pytest

from instabotai.providers.private import PrivateInstagramProvider, PrivateInstagramProviderError
from instabotai.settings import Settings


@dataclass
class FakeComment:
    pk: int


class FakePrivateClient:
    def account_info(self):
        return type("Account", (), {"username": "owner", "pk": "42"})()

    def media_comment(self, media_id: str, message: str, replied_to_comment_id: int):
        assert media_id == "123_42"
        assert message == "Thanks!"
        assert replied_to_comment_id == 999
        return FakeComment(pk=1001)


async def test_private_provider_reads_profile_without_credentials_when_client_injected() -> None:
    provider = PrivateInstagramProvider(Settings(_env_file=None), client=FakePrivateClient())
    profile = await provider.get_profile()
    assert profile["username"] == "owner"


async def test_private_comment_reply_requires_media_id() -> None:
    provider = PrivateInstagramProvider(Settings(_env_file=None), client=FakePrivateClient())
    with pytest.raises(PrivateInstagramProviderError, match="media_id"):
        await provider.reply_to_comment("999", "Thanks!")


async def test_private_comment_reply_uses_parent_comment_id() -> None:
    provider = PrivateInstagramProvider(Settings(_env_file=None), client=FakePrivateClient())
    reply_id = await provider.reply_to_comment("999", "Thanks!", media_id="123_42")
    assert reply_id == "1001"
