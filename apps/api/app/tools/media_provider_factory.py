from __future__ import annotations


from app.core.config import Settings

from app.tools.media_provider_protocol import MediaConfigurationError, MediaProvider
from app.tools.mock_media_provider import MockMediaProvider
from app.tools.real_media_provider import RealMediaProvider


def build_media_provider(settings: Settings) -> MediaProvider:
    mode = settings.media_mode.strip().lower()
    if mode == "mock":
        return MockMediaProvider(settings)
    if mode == "real":
        return RealMediaProvider(settings)
    raise MediaConfigurationError(
        f"MEDIA_MODE must be 'mock' or 'real', got {settings.media_mode!r}."
    )
