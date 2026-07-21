from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import shutil
from urllib.parse import urlparse
from uuid import uuid4

from app.core.config import Settings
from app.schemas.workflow_v2_production_acceptance import V2ProductionAcceptanceBlocker
from app.services.provider_strategy import ProviderCapabilityRegistry
from app.services.v2_data_boundary import V2DataBoundaryError, validate_v2_data_path
from app.services.v2_production_acceptance_fixtures import (
    V2ProductionAcceptanceFixtureBundle,
)


class V2ProductionAcceptancePreflight:
    def __init__(
        self,
        *,
        settings: Settings,
        executable_checker: Callable[[str], bool] | None = None,
        capability_registry: ProviderCapabilityRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._executable_checker = executable_checker or _executable_exists
        self._capabilities = capability_registry or ProviderCapabilityRegistry()

    def check(
        self,
        bundle: V2ProductionAcceptanceFixtureBundle,
    ) -> list[V2ProductionAcceptanceBlocker]:
        blockers: list[V2ProductionAcceptanceBlocker] = []
        blockers.extend(self._provider_blockers())
        if not self._executable_checker(self._settings.ffmpeg_path):
            blockers.append(
                _blocker("acceptance_ffmpeg_missing", "FFmpeg is not executable.", "ffmpeg")
            )
        ffprobe = _ffprobe_command(self._settings.ffmpeg_path)
        if not self._executable_checker(ffprobe):
            blockers.append(
                _blocker("acceptance_ffprobe_missing", "FFprobe is not executable.", "ffprobe")
            )
        blockers.extend(self._fixture_blockers(bundle))
        blockers.extend(self._storage_blockers())
        return blockers

    def capability_snapshot(self) -> dict[str, object]:
        return {
            "agent_configured": self._agent_configured(),
            "image_configured": self._image_configured(),
            "video_configured": self._video_configured(),
            "audio_configured": self._audio_configured(),
            "ffmpeg_path": self._settings.ffmpeg_path,
            "ffprobe_command": _ffprobe_command(self._settings.ffmpeg_path),
        }

    def _provider_blockers(self) -> list[V2ProductionAcceptanceBlocker]:
        checks = [
            ("agent:script", self._agent_configured()),
            ("image", self._image_configured()),
            ("video", self._video_configured()),
            ("audio", self._audio_configured()),
        ]
        return [
            _blocker(
                "acceptance_provider_capability_missing",
                f"Required production capability is not configured: {capability}.",
                capability,
            )
            for capability, configured in checks
            if not configured
        ]

    def _agent_configured(self) -> bool:
        return bool(
            not self._settings.agno_mock_mode
            and self._settings.llm_api_key
            and self._settings.llm_base_url
            and self._settings.llm_script_model
        )

    def _image_configured(self) -> bool:
        supported = self._capabilities.candidates(
            media_type="image",
            node_type="product-generation",
            provider="volcengine_image",
            allow_provider_fallback=False,
        )
        return bool(
            supported
            and self._settings.media_mode == "real"
            and self._settings.image_generation_api_key
            and self._settings.image_generation_endpoint
            and self._settings.image_generation_model
        )

    def _video_configured(self) -> bool:
        supported = self._capabilities.candidates(
            media_type="video",
            node_type="storyboard-video-generation",
            provider="volcengine_video",
            allow_provider_fallback=False,
        )
        return bool(
            supported
            and self._settings.media_mode == "real"
            and self._settings.video_generation_api_key
            and self._settings.video_generation_endpoint
            and self._settings.video_generation_model
        )

    def _audio_configured(self) -> bool:
        supported = self._capabilities.candidates(
            media_type="audio",
            node_type="bgm",
            provider="volcengine_audio",
            allow_provider_fallback=False,
        )
        return bool(
            supported
            and self._settings.media_mode == "real"
            and self._settings.bgm_access_key_id
            and self._settings.bgm_secret_access_key
            and _official_bgm_endpoint(self._settings.bgm_endpoint)
            and self._settings.bgm_submit_action in {"GenBGM", "GenBGMForTime"}
        )

    def _fixture_blockers(
        self,
        bundle: V2ProductionAcceptanceFixtureBundle,
    ) -> list[V2ProductionAcceptanceBlocker]:
        blockers: list[V2ProductionAcceptanceBlocker] = []
        declarations = {asset.relative_path: asset for asset in bundle.fixture.input_assets}
        for relative_path, path in bundle.asset_paths.items():
            if not path.is_file() or not os.access(path, os.R_OK):
                blockers.append(
                    _blocker(
                        "acceptance_fixture_asset_missing",
                        f"Fixture asset is missing or unreadable: {relative_path}.",
                        "fixture_asset",
                    )
                )
                continue
            declaration = declarations[relative_path]
            if not _media_header_matches(path, declaration.content_type):
                blockers.append(
                    _blocker(
                        "acceptance_fixture_asset_invalid",
                        f"Fixture asset content is invalid: {relative_path}.",
                        "fixture_asset",
                    )
                )
        return blockers

    def _storage_blockers(self) -> list[V2ProductionAcceptanceBlocker]:
        for relative in (Path("assets"), Path("v2")):
            try:
                directory = validate_v2_data_path(
                    self._settings.media_data_dir,
                    self._settings.media_data_dir / relative,
                    operation="v2-production-acceptance-preflight",
                )
                directory.mkdir(parents=True, exist_ok=True)
                probe = directory / f".acceptance-write-probe-{uuid4().hex}"
                with probe.open("wb") as output:
                    output.write(b"ok")
                    output.flush()
                    os.fsync(output.fileno())
                probe.unlink()
            except (OSError, V2DataBoundaryError):
                return [
                    _blocker(
                        "acceptance_data_dir_unwritable",
                        "V2 production acceptance storage is not writable.",
                        "storage",
                    )
                ]
        return []


def _official_bgm_endpoint(endpoint: str | None) -> bool:
    parsed = urlparse(str(endpoint or ""))
    return parsed.scheme == "https" and parsed.hostname == "open.volcengineapi.com"


def _blocker(code: str, message: str, capability: str) -> V2ProductionAcceptanceBlocker:
    return V2ProductionAcceptanceBlocker(
        code=code,
        stage="preflight",
        message=message,
        capability=capability,
    )


def _executable_exists(command: str) -> bool:
    path = Path(command)
    if path.parent != Path("."):
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(command) is not None


def _ffprobe_command(ffmpeg_path: str) -> str:
    ffmpeg = Path(ffmpeg_path)
    if ffmpeg.parent == Path("."):
        return "ffprobe"
    return str(ffmpeg.with_name("ffprobe"))


def _media_header_matches(path: Path, content_type: str) -> bool:
    header = path.read_bytes()[:16]
    normalized = content_type.lower()
    if normalized == "image/png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if normalized in {"image/jpeg", "image/jpg"}:
        return header.startswith(b"\xff\xd8")
    if normalized == "image/webp":
        return header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    return bool(header)
