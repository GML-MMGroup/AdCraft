"""Provider selection limited to the V2 BGM execution boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from app.core.config import Settings
from app.tools.media_provider_protocol import MediaConfigurationError
from app.tools.tianpuyue_pure_music import (
    TianpuyuePureMusicAdapter,
    validate_tianpuyue_bgm_settings,
)
from app.tools.volcengine_pure_music import (
    VOLCENGINE_BGM_HOST,
    VOLCENGINE_BGM_SUBMIT_ACTIONS,
    VolcenginePureMusicAdapter,
)


class BgmProviderAdapter(Protocol):
    def generate_bgm_audio(self, bgm_plan: dict[str, Any], workflow_id: str) -> dict[str, Any]: ...

    def retrieve_bgm_audio_task(
        self,
        remote_task_id: str,
        *,
        workflow_id: str,
        provider_payload: dict[str, Any],
        download_media: bool = True,
    ) -> dict[str, Any]: ...


def build_bgm_provider_adapter(settings: Settings, data_dir: Path) -> BgmProviderAdapter:
    provider = normalized_bgm_provider_id(settings)
    if provider == "tianpuyue":
        return TianpuyuePureMusicAdapter(settings, data_dir)
    if provider == "volcengine_ai_music":
        return VolcenginePureMusicAdapter(settings, data_dir)
    raise MediaConfigurationError(
        f"Unsupported BGM_PROVIDER: {settings.bgm_provider or '<empty>'}."
    )


def normalized_bgm_provider_id(settings: Settings) -> str:
    return str(settings.bgm_provider or "").strip().lower()


def is_supported_bgm_provider(settings: Settings) -> bool:
    return normalized_bgm_provider_id(settings) in {"tianpuyue", "volcengine_ai_music"}


def bgm_provider_configuration_error(settings: Settings) -> str | None:
    provider = normalized_bgm_provider_id(settings)
    try:
        if provider == "tianpuyue":
            validate_tianpuyue_bgm_settings(settings)
            return None
        if provider == "volcengine_ai_music":
            _validate_volcengine_bgm_settings(settings)
            return None
    except MediaConfigurationError as exc:
        return str(exc)
    return None


def _validate_volcengine_bgm_settings(settings: Settings) -> None:
    endpoint = str(settings.bgm_endpoint or "").strip()
    parsed = urlparse(endpoint)
    if not settings.bgm_access_key_id or not settings.bgm_secret_access_key:
        raise MediaConfigurationError(
            "Real BGM provider requires BGM_ACCESS_KEY_ID and BGM_SECRET_ACCESS_KEY."
        )
    if parsed.scheme != "https" or parsed.hostname != VOLCENGINE_BGM_HOST.removeprefix("https://"):
        raise MediaConfigurationError(
            "BGM_ENDPOINT must use the official https://open.volcengineapi.com host."
        )
    if settings.bgm_submit_action not in VOLCENGINE_BGM_SUBMIT_ACTIONS:
        raise MediaConfigurationError("BGM_SUBMIT_ACTION must be GenBGM or GenBGMForTime.")
    if not settings.bgm_api_version or not settings.bgm_generation_version:
        raise MediaConfigurationError(
            "BGM_API_VERSION and BGM_GENERATION_VERSION must not be empty."
        )
