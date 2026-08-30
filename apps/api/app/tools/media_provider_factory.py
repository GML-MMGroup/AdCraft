from __future__ import annotations


from app.core.config import Settings

from app.tools.media_provider_protocol import MediaConfigurationError, MediaProvider
from app.tools.mock_media_provider import MockMediaProvider
from app.tools.real_media_provider import RealMediaProvider


def build_media_provider(
    settings: Settings,
    *,
    required_media_types: set[str] | None = None,
) -> MediaProvider:
    mode = settings.media_mode.strip().lower()
    if mode == "mock":
        return MockMediaProvider(settings)
    if mode == "real":
        return RealMediaProvider(settings, required_media_types=required_media_types)
    raise MediaConfigurationError(
        f"MEDIA_MODE must be 'mock' or 'real', got {settings.media_mode!r}."
    )
