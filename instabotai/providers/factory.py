"""Instagram provider selection."""

from __future__ import annotations

from typing import Any

from instabotai.providers.instagram import InstagramGraphClient
from instabotai.providers.private import PrivateInstagramProvider
from instabotai.settings import Settings


def build_instagram_provider(settings: Settings) -> Any:
    """Build the configured Instagram transport.

    ``official`` is the production default. ``private`` is an opt-in quick-start
    compatibility backend and remains subject to the same automation policy.
    """

    if settings.instagram_provider == "official":
        return InstagramGraphClient(settings)
    if settings.instagram_provider == "private":
        return PrivateInstagramProvider(settings)
    raise ValueError(f"unsupported Instagram provider: {settings.instagram_provider}")
