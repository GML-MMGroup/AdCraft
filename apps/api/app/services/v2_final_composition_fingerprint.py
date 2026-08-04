from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.workflow_v2 import (
    V2FinalCompositionFingerprint,
    WorkflowV2Timeline,
    WorkflowV2TimelineRenderSettings,
)
from app.schemas.workflow_v2_composition import V2SimpleCompositionPlan
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_media_toolchain_capabilities import (
    PROFILE_ID,
    V2MediaToolchainCapabilityService,
)

FINGERPRINT_CONTRACT_VERSION = "v2-final-composition-fingerprint-v1"

_TOP_LEVEL_FIELDS = (
    "workflow_id",
    "slot_id",
    "render_mode",
    "visual_sources",
    "audio_sources",
    "audio_mode",
    "audio_mix",
    "output",
    "renderer",
)
_VISUAL_SOURCE_FIELDS = (
    "asset_id",
    "version_id",
    "content_sha256",
    "timeline_order",
    "track_order",
    "clip_type",
    "start_time_seconds",
    "duration_seconds",
    "trim_in_seconds",
    "trim_out_seconds",
    "transform",
    "audio",
    "color",
    "text",
    "subtitle_style",
    "transition",
    "filter",
    "enabled",
)
_AUDIO_SOURCE_FIELDS = (
    "asset_id",
    "version_id",
    "content_sha256",
    "timeline_order",
    "track_order",
    "start_time_seconds",
    "duration_seconds",
    "trim_in_seconds",
    "trim_out_seconds",
    "volume",
    "muted",
    "fade_in_seconds",
    "fade_out_seconds",
    "enabled",
)


class V2FinalCompositionFingerprintError(ValueError):
    """Raised when an effective Final Composition specification is incomplete."""


class V2FinalCompositionFingerprintService:
    """Produces the sole canonical identity for a deterministic final render."""

    def __init__(
        self,
        data_dir: Path | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._settings = settings
        self._asset_store = V2AssetStoreService(data_dir) if data_dir is not None else None

    def build(self, **inputs: Any) -> V2FinalCompositionFingerprint:
        payload = self.canonical_payload(inputs)
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return V2FinalCompositionFingerprint(
            contract_version=FINGERPRINT_CONTRACT_VERSION,
            fingerprint=f"sha256:{sha256(serialized.encode('utf-8')).hexdigest()}",
            canonical_payload=payload,
        )

    def canonical_payload(self, inputs: dict[str, Any]) -> dict[str, Any]:
        missing = [
            field
            for field in ("workflow_id", "slot_id", "render_mode", "output", "renderer")
            if inputs.get(field) in (None, "")
        ]
        if missing:
            raise V2FinalCompositionFingerprintError(
                f"Final composition fingerprint is missing: {', '.join(missing)}"
            )
        payload = {
            "contract": FINGERPRINT_CONTRACT_VERSION,
            **{
                field: inputs.get(field)
                for field in _TOP_LEVEL_FIELDS
                if field not in {"visual_sources", "audio_sources"}
            },
            "visual_sources": [
                self._allowlisted_source(source, _VISUAL_SOURCE_FIELDS)
                for source in inputs.get("visual_sources", [])
                if isinstance(source, dict) and source.get("enabled", True)
            ],
            "audio_sources": [
                self._allowlisted_source(source, _AUDIO_SOURCE_FIELDS)
                for source in inputs.get("audio_sources", [])
                if isinstance(source, dict) and source.get("enabled", True)
            ],
        }
        for source in [*payload["visual_sources"], *payload["audio_sources"]]:
            missing_identity = [
                key for key in ("asset_id", "version_id", "content_sha256") if not source.get(key)
            ]
            if missing_identity:
                raise V2FinalCompositionFingerprintError(
                    "Final composition source is missing exact identity fields: "
                    + ", ".join(missing_identity)
                )
        return _normalize_json_value(payload)

    def build_for_composition(
        self,
        *,
        workflow_id: str,
        slot_id: str,
        timeline: WorkflowV2Timeline,
        render_settings: WorkflowV2TimelineRenderSettings,
        render_mode: str,
        audio_mode: str,
        simple_plan: V2SimpleCompositionPlan | None = None,
    ) -> V2FinalCompositionFingerprint:
        if self._asset_store is None or self._settings is None:
            raise V2FinalCompositionFingerprintError(
                "Final composition fingerprint dependencies are not configured."
            )
        visual_sources: list[dict[str, Any]]
        audio_sources: list[dict[str, Any]]
        if render_mode == "simple_sequence":
            if simple_plan is None:
                raise V2FinalCompositionFingerprintError(
                    "Simple composition fingerprint requires an immutable plan."
                )
            visual_sources = [
                {
                    "asset_id": source.asset_id,
                    "version_id": source.version_id,
                    "content_sha256": self._asset_store.asset_content_sha256(
                        source.asset_id,
                        source.version_id,
                    ),
                    "timeline_order": order,
                    "enabled": True,
                }
                for order, source in enumerate(
                    sorted(simple_plan.videos, key=lambda item: item.shot_index)
                )
            ]
            audio_sources = (
                [
                    {
                        "asset_id": simple_plan.bgm.asset_id,
                        "version_id": simple_plan.bgm.version_id,
                        "content_sha256": self._asset_store.asset_content_sha256(
                            simple_plan.bgm.asset_id,
                            simple_plan.bgm.version_id,
                        ),
                        "timeline_order": 0,
                        "enabled": True,
                    }
                ]
                if simple_plan.bgm is not None
                else []
            )
        else:
            track_order = {track.track_id: track.order for track in timeline.tracks}
            ordered_clips = sorted(
                timeline.clips,
                key=lambda clip: (
                    track_order[clip.track_id],
                    clip.start_time,
                    clip.clip_id,
                ),
            )
            visual_sources = []
            audio_sources = []
            for timeline_order, clip in enumerate(ordered_clips):
                if not clip.enabled or clip.clip_type == "subtitle":
                    continue
                if not clip.source_asset_id or not clip.source_version_id:
                    continue
                common = {
                    "asset_id": clip.source_asset_id,
                    "version_id": clip.source_version_id,
                    "content_sha256": self._asset_store.asset_content_sha256(
                        clip.source_asset_id,
                        clip.source_version_id,
                    ),
                    "timeline_order": timeline_order,
                    "track_order": track_order[clip.track_id],
                    "start_time_seconds": clip.start_time,
                    "duration_seconds": clip.duration,
                    "trim_in_seconds": clip.trim_in,
                    "trim_out_seconds": clip.trim_out,
                    "enabled": True,
                }
                if clip.clip_type in {"video", "image"}:
                    visual_sources.append(
                        {
                            **common,
                            "clip_type": clip.clip_type,
                            "transform": clip.transform.model_dump(mode="json"),
                            "audio": clip.audio.model_dump(mode="json"),
                            "color": clip.color.model_dump(mode="json"),
                        }
                    )
                elif clip.clip_type == "audio":
                    audio_sources.append(
                        {
                            **common,
                            "volume": clip.audio.volume,
                            "muted": clip.audio.muted,
                            "fade_in_seconds": clip.audio.fade_in_seconds,
                            "fade_out_seconds": clip.audio.fade_out_seconds,
                        }
                    )
        toolchain = self._toolchain_identity()
        output = {
            "width": timeline.resolution["width"],
            "height": timeline.resolution["height"],
            "fps": timeline.fps,
            "video_codec": (
                render_settings.video_codec
                or toolchain.get("selected_video_encoder")
                or self._settings.ffmpeg_video_codec
                or "libx264"
            ),
            "audio_codec": render_settings.audio_codec,
            "video_bitrate": render_settings.video_bitrate,
            "audio_bitrate": render_settings.audio_bitrate,
        }
        return self.build(
            workflow_id=workflow_id,
            slot_id=slot_id,
            render_mode=render_mode,
            visual_sources=visual_sources,
            audio_sources=audio_sources,
            audio_mode=audio_mode,
            audio_mix=_audio_mix_payload(visual_sources, audio_sources),
            output=output,
            renderer={
                "contract_version": "final-composition-renderer-v1",
                "toolchain_profile": "v2-final-composition",
                "toolchain_fingerprint": toolchain["fingerprint"],
            },
        )

    def _toolchain_identity(self) -> dict[str, Any]:
        assert self._settings is not None
        if self._settings.media_mode.strip().lower() == "mock":
            payload = {
                "profile_id": PROFILE_ID,
                "mode": "mock",
                "selected_video_encoder": self._settings.ffmpeg_video_codec or "mock-video",
                "audio_encoder": "aac",
            }
        else:
            capabilities = V2MediaToolchainCapabilityService(self._settings).require_profile(
                PROFILE_ID
            )
            payload = capabilities.model_dump(mode="json")
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return {
            **payload,
            "fingerprint": f"sha256:{sha256(serialized.encode('utf-8')).hexdigest()}",
        }

    @staticmethod
    def _allowlisted_source(
        source: dict[str, Any],
        fields: tuple[str, ...],
    ) -> dict[str, Any]:
        return {field: source[field] for field in fields if field in source}


def _normalize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise V2FinalCompositionFingerprintError(
                "Final composition fingerprint contains a non-finite number."
            )
        if value == 0:
            return 0
        if value.is_integer():
            return int(value)
        return float(format(value, ".12g"))
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise V2FinalCompositionFingerprintError(
        f"Final composition fingerprint contains unsupported value: {type(value).__name__}"
    )


def _audio_mix_payload(
    visual_sources: list[dict[str, Any]],
    audio_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    source_audio_enabled = any(
        not bool(source.get("audio", {}).get("muted", False))
        for source in visual_sources
        if isinstance(source.get("audio"), dict)
    )
    return {
        "strategy": "preserve_source_audio",
        "source_audio_enabled": source_audio_enabled,
        "bgm_enabled": bool(audio_sources),
        "limiter": True,
    }
