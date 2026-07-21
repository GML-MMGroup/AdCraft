from dataclasses import replace

from app.core.config import Settings
from app.tools.media import build_media_provider as _build_media_provider


def build_media_provider(settings: Settings):
    return _build_media_provider(settings)


def build_media_provider_for_provider(settings: Settings, provider: str):
    media_provider_settings = settings
    if provider.startswith("mock_"):
        media_provider_settings = replace(settings, media_mode="mock")
    elif provider.startswith("volcengine_"):
        media_provider_settings = replace(settings, media_mode="real")
    return build_media_provider(media_provider_settings)
