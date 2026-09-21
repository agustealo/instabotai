import pytest

from instabotai.providers import PrivateInstagramProvider, build_instagram_provider
from instabotai.settings import Settings


def test_factory_builds_private_provider_without_importing_optional_dependency() -> None:
    settings = Settings(_env_file=None, instagram_provider="private")
    provider = build_instagram_provider(settings)
    assert isinstance(provider, PrivateInstagramProvider)


def test_official_provider_still_requires_official_credentials() -> None:
    settings = Settings(_env_file=None, instagram_provider="official")
    with pytest.raises(ValueError, match="ACCESS_TOKEN"):
        build_instagram_provider(settings)
