from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2 import (
    V2ProviderResult,
    WorkflowAssetVersionV2,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
    WorkflowV2Timeline,
    WorkflowV2TimelineRenderSettings,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_data_boundary import validate_v2_data_path, validate_v2_relative_path
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_final_composition import FINAL_COMPOSITION_PROVIDER
from app.services.v2_final_composition_filters import (
    build_ffmpeg_render_command,
    V2CompositionCanvas,
    V2FilterGraph,
    V2ResolvedTimelineClip,
    build_audio_filter_graph,
    build_visual_filter_graph,
)
from app.services.v2_media_toolchain_capabilities import (
    PROFILE_ID,
    V2MediaToolchainCapabilityError,
    V2MediaToolchainCapabilityService,
)


FFmpegRunner = Callable[..., subprocess.CompletedProcess[str]]
MediaProbe = Callable[[Path, str], "V2MediaProbeResult | dict[str, Any]"]
FINAL_VIDEO_CODEC_FALLBACKS = ("libx264", "libopenh264", "h264", "mpeg4")


@dataclass(frozen=True)
class V2MediaProbeResult:
    path: Path
    media_type: str
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    has_audio: bool = False
    error: str | None = None

    @classmethod
    def from_payload(
        cls,
        payload: "V2MediaProbeResult | dict[str, Any]",
        *,
        path: Path,
        media_type: str,
    ) -> "V2MediaProbeResult":
        if isinstance(payload, V2MediaProbeResult):
            return payload
        return cls(
            path=path,
            media_type=media_type,
            width=_int_or_none(payload.get("width")),
            height=_int_or_none(payload.get("height")),
            duration_seconds=_float_or_none(payload.get("duration_seconds")),
            fps=_float_or_none(payload.get("fps")),
            video_codec=_string(payload.get("video_codec")),
            audio_codec=_string(payload.get("audio_codec")),
            has_audio=bool(payload.get("has_audio")),
            error=_string(payload.get("error")),
        )


class V2MediaProbe:
    def __init__(self, *, ffprobe_path: str = "ffprobe") -> None:
        self._ffprobe_path = ffprobe_path

    def __call__(self, path: Path, media_type: str) -> V2MediaProbeResult:
        args = [
            self._ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            path.as_posix(),
        ]
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            return V2MediaProbeResult(
                path=path,
                media_type=media_type,
                error=f"ffprobe executable not found: {exc}",
            )
        if completed.returncode != 0:
            return V2MediaProbeResult(
                path=path,
                media_type=media_type,
                error=_truncate(completed.stderr or completed.stdout),
            )
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            return V2MediaProbeResult(
                path=path,
                media_type=media_type,
                error=f"ffprobe returned invalid json: {exc}",
            )
        streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
        video_stream = next(
            (stream for stream in streams if stream.get("codec_type") == "video"),
            {},
        )
        audio_stream = next(
            (stream for stream in streams if stream.get("codec_type") == "audio"),
            {},
        )
        return V2MediaProbeResult(
            path=path,
            media_type=media_type,
            width=_int_or_none(video_stream.get("width")),
            height=_int_or_none(video_stream.get("height")),
            duration_seconds=_probe_duration(payload, video_stream, audio_stream),
            fps=_frame_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")),
            video_codec=_string(video_stream.get("codec_name")),
            audio_codec=_string(audio_stream.get("codec_name")),
            has_audio=bool(audio_stream),
        )


class V2FinalCompositionRenderer:
    def __init__(
        self,
        *,
        data_dir: Path,
        settings: Settings | None = None,
        asset_store: V2AssetStoreService | None = None,
        runner: FFmpegRunner | None = None,
        probe: MediaProbe | None = None,
        toolchain: V2MediaToolchainCapabilityService | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._data_dir = data_dir
        self._asset_store = asset_store or V2AssetStoreService(data_dir)
        self._runner = runner or subprocess.run
        self._probe = probe or V2MediaProbe(ffprobe_path=self._settings.ffprobe_path)
        self._toolchain = toolchain or V2MediaToolchainCapabilityService(self._settings)

    def render(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        provider_payload: dict[str, Any],
    ) -> V2ProviderResult:
        payload = sanitize_context_for_llm_text(provider_payload)
        if isinstance(payload.get("canonical_timeline"), dict):
            if self._settings.media_mode.strip().lower() == "mock":
                return self._render_legacy(workflow, item, slot, payload)
            return self._render_canonical_timeline(workflow, item, slot, payload)
        return self._render_legacy(workflow, item, slot, payload)

    def _render_canonical_timeline(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        payload: dict[str, Any],
    ) -> V2ProviderResult:
        timeline_data = payload.get("canonical_timeline")
        assert isinstance(timeline_data, dict)
        try:
            timeline = WorkflowV2Timeline.model_validate(timeline_data)
        except ValueError as exc:
            return self._failure(
                payload,
                [],
                code="v2_timeline_invalid_clip",
                message="Canonical final-composition timeline is invalid.",
                metadata={"validation_error": str(exc)},
            )
        if slot.slot_type != "final_video":
            return self._failure(
                payload,
                [],
                code="final_composition_not_llm_generation",
                message=f"Final composition renderer only supports final_video, got {slot.slot_type}.",
            )
        if not any(clip.enabled and clip.clip_type == "video" for clip in timeline.clips):
            return self._failure(
                payload,
                [],
                code="composition_input_missing",
                message="Final composition requires at least one enabled video clip.",
            )
        try:
            capabilities = self._toolchain.require_profile(
                profile_id=PROFILE_ID,
                requires_subtitles=any(
                    clip.enabled and clip.clip_type == "subtitle" for clip in timeline.clips
                ),
            )
        except V2MediaToolchainCapabilityError as exc:
            return self._failure(
                payload,
                [],
                code=exc.code,
                message=str(exc),
            )
        if not capabilities.selected_video_encoder:
            return self._failure(
                payload,
                [],
                code="v2_media_toolchain_unsupported",
                message="Final composition requires an allowlisted H.264-capable video encoder.",
            )
        render_settings = _canonical_render_settings(payload)
        requested_video_codec = render_settings.video_codec
        if requested_video_codec and requested_video_codec != capabilities.selected_video_encoder:
            return self._failure(
                payload,
                [],
                code="v2_media_toolchain_unsupported",
                message="Requested video codec is not available in the active media toolchain profile.",
            )

        resolution = timeline.resolution
        width = int(resolution.get("width", 1280))
        height = int(resolution.get("height", 720))
        canvas = V2CompositionCanvas(
            width=width,
            height=height,
            fps=timeline.fps,
            duration_seconds=timeline.duration_seconds,
            subtitle_font_path=self._settings.final_composition_subtitle_font_path,
        )
        track_orders = {track.track_id: track.order for track in timeline.tracks if track.enabled}
        resolved_clips: list[V2ResolvedTimelineClip] = []
        source_paths: list[Path] = []
        source_asset_ids: list[str] = []
        source_version_ids: list[str] = []
        for clip in sorted(
            timeline.clips,
            key=lambda candidate: (
                track_orders.get(candidate.track_id, 0),
                candidate.start_time,
                candidate.clip_id,
            ),
        ):
            if not clip.enabled or clip.clip_type == "subtitle":
                continue
            asset_id = clip.source_asset_id
            version_id = clip.source_version_id
            if not asset_id or not version_id:
                return self._failure(
                    payload,
                    source_asset_ids,
                    code="v2_timeline_source_version_missing",
                    message="Canonical media clips must pin source asset and version ids.",
                )
            resolved = self._resolve_asset(asset_id, version_id)
            if resolved is None:
                return self._failure(
                    payload,
                    source_asset_ids,
                    code="v2_timeline_source_version_missing",
                    message=f"Pinned timeline source is unavailable: {asset_id}:{version_id}.",
                )
            record, path = resolved
            if record.media_type != clip.clip_type:
                return self._failure(
                    payload,
                    source_asset_ids,
                    code="v2_timeline_unsupported_source_media",
                    message="Pinned timeline source media type does not match its clip type.",
                )
            probe = self._probe_result(path, clip.clip_type)
            if probe.error:
                return self._failure(
                    payload,
                    source_asset_ids,
                    code="asset_file_missing",
                    message="Timeline source media could not be probed.",
                )
            input_index = len(source_paths)
            source_paths.append(path)
            source_asset_ids.append(record.asset_id)
            source_version_ids.append(record.version_id)
            resolved_clips.append(
                V2ResolvedTimelineClip(
                    input_index=input_index,
                    clip=clip,
                    track_order=track_orders.get(clip.track_id, 0),
                    source_has_audio=probe.has_audio,
                    source_duration_seconds=probe.duration_seconds,
                )
            )
        try:
            visual_graph = build_visual_filter_graph(resolved_clips, canvas)
            audio_graph = build_audio_filter_graph(
                resolved_clips,
                timeline_duration_seconds=timeline.duration_seconds,
                audio_mode=workflow.audio_mode,
            )
        except ValueError as exc:
            return self._failure(
                payload,
                source_asset_ids,
                code="v2_media_toolchain_subtitle_font_missing",
                message=str(exc),
            )
        render_id = _safe_render_id(payload.get("render_id")) or f"render_{uuid4().hex[:12]}"
        output_rel = (
            Path("v2")
            / "runs"
            / workflow.workflow_id
            / "composition"
            / render_id
            / "final-ad-video.mp4"
        )
        output_path = self._data_dir / output_rel
        validate_v2_data_path(self._data_dir, output_path, operation="v2-final-composition-render")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = build_ffmpeg_render_command(
            ffmpeg_path=self._settings.ffmpeg_path,
            source_paths=[path.as_posix() for path in source_paths],
            resolved_clips=resolved_clips,
            filter_graph=V2FilterGraph(
                filter_complex=";".join(
                    part
                    for part in (visual_graph.filter_complex, audio_graph.filter_complex)
                    if part
                ),
                video_label=visual_graph.video_label,
                audio_label=audio_graph.audio_label,
                loop_input_indices=audio_graph.loop_input_indices,
            ),
            canvas=canvas,
            video_encoder=capabilities.selected_video_encoder,
            audio_encoder=capabilities.audio_encoder or "aac",
            video_bitrate=render_settings.video_bitrate,
            audio_bitrate=render_settings.audio_bitrate,
            output_path=output_path.as_posix(),
        )
        args = [*command.input_args, *command.output_args]
        try:
            completed = self._runner(args, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            return self._failure(
                payload,
                source_asset_ids,
                code="composition_ffmpeg_missing",
                message="Configured FFmpeg executable was not found.",
                metadata={"exception": str(exc)},
            )
        if completed.returncode != 0:
            return self._failure(
                payload,
                source_asset_ids,
                code="composition_failed",
                message="FFmpeg final composition failed.",
                metadata={
                    "stderr": _truncate(completed.stderr),
                    "stdout": _truncate(completed.stdout),
                },
            )
        output_probe = self._probe_result(output_path, "video")
        expected_audio = audio_graph.audio_label is not None
        if not self._valid_editor_output(
            output_path=output_path,
            probe=output_probe,
            canvas=canvas,
            expected_audio=expected_audio,
        ):
            return self._failure(
                payload,
                source_asset_ids,
                code="composition_output_invalid",
                message="FFmpeg final composition did not produce the requested playable output.",
                metadata={
                    "width": output_probe.width,
                    "height": output_probe.height,
                    "duration_seconds": output_probe.duration_seconds,
                    "has_audio": output_probe.has_audio,
                },
            )
        filter_fingerprint = hashlib.sha256(
            f"{visual_graph.filter_complex};{audio_graph.filter_complex}".encode("utf-8")
        ).hexdigest()
        metadata = {
            "provider": FINAL_COMPOSITION_PROVIDER,
            "composition_provider": FINAL_COMPOSITION_PROVIDER,
            "composition_tool": FINAL_COMPOSITION_PROVIDER,
            "timeline_id": timeline.timeline_id,
            "timeline_version": timeline.version,
            "timeline_duration_seconds": timeline.duration_seconds,
            "source_clip_ids": [clip.clip_id for clip in timeline.clips],
            "source_asset_ids": list(dict.fromkeys(source_asset_ids)),
            "source_version_ids": list(dict.fromkeys(source_version_ids)),
            "has_audio": expected_audio,
            "audio_mode": workflow.audio_mode,
            "output_width": output_probe.width,
            "output_height": output_probe.height,
            "output_fps": output_probe.fps,
            "actual_video_codec": output_probe.video_codec,
            "actual_audio_codec": output_probe.audio_codec if expected_audio else None,
            "render_mode": "timeline_editor",
            "toolchain_profile": capabilities.profile_id,
            "selected_video_encoder": capabilities.selected_video_encoder,
            "audio_encoder": capabilities.audio_encoder,
            "degraded_fallbacks": capabilities.degraded_fallbacks,
            "requested_video_codec": requested_video_codec,
            "video_bitrate": render_settings.video_bitrate,
            "audio_bitrate": render_settings.audio_bitrate,
            "filter_graph_fingerprint": f"sha256:{filter_fingerprint}",
            "output_probe": {
                "width": output_probe.width,
                "height": output_probe.height,
                "duration_seconds": output_probe.duration_seconds,
                "fps": output_probe.fps,
                "video_codec": output_probe.video_codec,
                "audio_codec": output_probe.audio_codec,
                "has_audio": output_probe.has_audio,
            },
        }
        return V2ProviderResult(
            status="completed",
            media_type="video",
            local_file_path=output_rel.as_posix(),
            provider=FINAL_COMPOSITION_PROVIDER,
            provider_model=f"ffmpeg:{capabilities.selected_video_encoder}",
            provider_payload_snapshot=payload,
            reference_asset_ids=list(dict.fromkeys(source_asset_ids)),
            metadata=metadata,
        )

    def _render_legacy(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        provider_payload: dict[str, Any],
    ) -> V2ProviderResult:
        payload = sanitize_context_for_llm_text(provider_payload)
        timeline_clips = [
            dict(clip) for clip in payload.get("timeline_clips", []) if isinstance(clip, dict)
        ]
        timeline_plan = (
            dict(payload.get("timeline_plan"))
            if isinstance(payload.get("timeline_plan"), dict)
            else dict(item.timeline_plan)
        )
        reference_asset_ids = _ordered_source_asset_ids(timeline_clips)
        if slot.slot_type != "final_video":
            return self._failure(
                payload,
                reference_asset_ids,
                code="final_composition_not_llm_generation",
                message=f"Final composition renderer only supports final_video, got {slot.slot_type}.",
            )

        video_clips = _ordered_clips(timeline_clips, clip_type="video")
        if not video_clips:
            return self._failure(
                payload,
                reference_asset_ids,
                code="composition_input_missing",
                message="Final composition requires selected storyboard video segment clips.",
            )

        video_inputs: list[tuple[dict[str, Any], WorkflowAssetVersionV2, Path]] = []
        for clip in video_clips:
            asset_id = _string(clip.get("source_asset_id"))
            if asset_id is None:
                return self._failure(
                    payload,
                    reference_asset_ids,
                    code="composition_input_missing",
                    message="Final composition video clip is missing source_asset_id.",
                )
            resolved = self._resolve_asset(asset_id)
            if resolved is None:
                return self._failure(
                    payload,
                    reference_asset_ids,
                    code="asset_file_missing",
                    message=f"Selected video segment asset file is missing: {asset_id}.",
                )
            video_inputs.append((clip, *resolved))

        muted_by_policy = _muted_output_requested(workflow, payload, timeline_plan)
        bgm_asset_id = _string(payload.get("bgm_asset_id"))
        bgm_input: tuple[WorkflowAssetVersionV2, Path] | None = None
        composition_warnings: list[dict[str, Any]] = []
        if bgm_asset_id is not None and not muted_by_policy:
            if bgm_asset_id not in reference_asset_ids:
                reference_asset_ids.append(bgm_asset_id)
            bgm_input = self._resolve_asset(bgm_asset_id)
            if bgm_input is None:
                composition_warnings.append(
                    {
                        "code": "composition_audio_missing_soft",
                        "message": "Selected BGM is unavailable; final composition will render without it.",
                        "asset_id": bgm_asset_id,
                    }
                )
        video_probes = [
            self._probe_result(video_path, "video") for _clip, _record, video_path in video_inputs
        ]
        bgm_probe = self._probe_result(bgm_input[1], "audio") if bgm_input is not None else None
        audio_mix_strategy = _audio_mix_strategy(
            muted_by_policy=muted_by_policy,
            video_probes=video_probes,
            bgm_probe=bgm_probe,
        )
        output_width, output_height, resolution_source = _select_output_resolution(
            workflow=workflow,
            payload=payload,
            timeline_plan=timeline_plan,
            video_probes=video_probes,
        )
        audio_sources = _audio_sources(
            video_inputs=video_inputs,
            video_probes=video_probes,
            bgm_input=bgm_input,
            bgm_probe=bgm_probe,
            audio_mix_strategy=audio_mix_strategy,
        )
        source_video_dimensions = _source_video_dimensions(video_inputs, video_probes)

        render_id = f"render_{uuid4().hex[:12]}"
        output_rel = (
            Path("v2")
            / "runs"
            / workflow.workflow_id
            / "composition"
            / render_id
            / "final-ad-video.mp4"
        )
        output_path = self._data_dir / output_rel
        validate_v2_data_path(self._data_dir, output_path, operation="v2-final-composition-render")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        work_dir = output_path.parent
        codec = self._settings.ffmpeg_video_codec or "libx264"
        audio_codec = "aac"
        video_paths = [video_path for _clip, _record, video_path in video_inputs]

        def build_args(video_codec: str) -> list[str]:
            return (
                self._mock_ffmpeg_args(
                    output_path=output_path,
                    codec=video_codec,
                    include_audio=audio_mix_strategy
                    in {"source_audio_only", "source_audio_plus_bgm", "bgm_only"},
                    duration_seconds=_float(timeline_plan.get("duration_seconds")) or 0.25,
                    width=output_width,
                    height=output_height,
                )
                if self._settings.media_mode.strip().lower() == "mock"
                else self._concat_ffmpeg_args(
                    work_dir=work_dir,
                    output_path=output_path,
                    video_paths=video_paths,
                    bgm_path=bgm_input[1] if bgm_input is not None else None,
                    duration_seconds=_float(timeline_plan.get("duration_seconds")) or 0.25,
                    codec=video_codec,
                    audio_codec=audio_codec,
                    audio_mix_strategy=audio_mix_strategy,
                    output_width=output_width,
                    output_height=output_height,
                )
            )

        args = build_args(codec)
        try:
            completed = self._runner(args, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            return self._failure(
                payload,
                reference_asset_ids,
                code="composition_ffmpeg_missing",
                message=f"FFmpeg executable not found: {self._settings.ffmpeg_path}.",
                metadata={"exception": str(exc), "ffmpeg_args": args},
            )
        while completed.returncode != 0:
            fallback_codec = _next_video_codec(codec, completed.stderr)
            if fallback_codec is None:
                break
            codec = fallback_codec
            args = build_args(codec)
            try:
                completed = self._runner(args, capture_output=True, text=True, check=False)
            except FileNotFoundError as exc:
                return self._failure(
                    payload,
                    reference_asset_ids,
                    code="composition_ffmpeg_missing",
                    message=f"FFmpeg executable not found: {self._settings.ffmpeg_path}.",
                    metadata={"exception": str(exc), "ffmpeg_args": args},
                )

        if completed.returncode != 0:
            return self._failure(
                payload,
                reference_asset_ids,
                code="composition_failed",
                message="FFmpeg final composition failed.",
                metadata={
                    "ffmpeg_args": args,
                    "stderr": _truncate(completed.stderr),
                    "stdout": _truncate(completed.stdout),
                },
            )
        if not output_path.exists():
            return self._failure(
                payload,
                reference_asset_ids,
                code="composition_output_missing",
                message="FFmpeg completed but did not create the final video file.",
                metadata={"ffmpeg_args": args},
            )

        output_probe = self._probe_result(output_path, "video")
        if (
            output_probe.error
            or not output_probe.video_codec
            or not output_probe.width
            or not output_probe.height
        ):
            return self._failure(
                payload,
                reference_asset_ids,
                code="composition_output_invalid",
                message="FFmpeg final composition did not produce a playable video stream.",
                metadata={
                    "output_path": output_rel.as_posix(),
                    "probe_error": output_probe.error,
                    "width": output_probe.width,
                    "height": output_probe.height,
                    "video_codec": output_probe.video_codec,
                },
            )
        output_has_audio = bool(output_probe.has_audio)
        if not output_has_audio and not muted_by_policy:
            composition_warnings.append(
                {
                    "code": "composition_audio_missing_soft",
                    "message": "Final composition completed without an audio stream.",
                }
            )
        actual_video_codec = output_probe.video_codec or codec
        actual_audio_codec = output_probe.audio_codec if output_has_audio else None
        metadata = {
            "provider": FINAL_COMPOSITION_PROVIDER,
            "composition_provider": FINAL_COMPOSITION_PROVIDER,
            "composition_tool": FINAL_COMPOSITION_PROVIDER,
            "timeline_id": timeline_plan.get("timeline_id"),
            "timeline_version": timeline_plan.get("version"),
            "timeline_duration_seconds": timeline_plan.get("duration_seconds"),
            "source_clip_ids": [
                str(clip.get("clip_id")) for clip in timeline_clips if clip.get("clip_id")
            ],
            "source_asset_ids": reference_asset_ids,
            "video_source_asset_ids": [
                str(record.asset_id) for _clip, record, _path in video_inputs
            ],
            "bgm_asset_id": bgm_asset_id,
            "has_audio": output_has_audio,
            "audio_mode": workflow.audio_mode,
            "audio_mix_strategy": audio_mix_strategy,
            "audio_sources": audio_sources,
            "warnings": composition_warnings,
            "bgm_missing_policy": _bgm_missing_policy(
                bgm_input=bgm_input,
                audio_mix_strategy=audio_mix_strategy,
            ),
            "source_video_dimensions": source_video_dimensions,
            "output_width": output_width,
            "output_height": output_height,
            "output_fps": output_probe.fps,
            "resolution_source": resolution_source,
            "actual_video_codec": actual_video_codec,
            "render_mode": "mock_synthetic"
            if self._settings.media_mode.strip().lower() == "mock"
            else "timeline_concat",
            "render_workspace": output_path.parent.relative_to(self._data_dir).as_posix(),
            "render_output_path": output_rel.as_posix(),
            "ffmpeg_args": args,
        }
        if actual_audio_codec:
            metadata["actual_audio_codec"] = actual_audio_codec
        return V2ProviderResult(
            status="completed",
            media_type="video",
            local_file_path=output_rel.as_posix(),
            provider=FINAL_COMPOSITION_PROVIDER,
            provider_model=f"ffmpeg:{codec}",
            provider_payload_snapshot=payload,
            reference_asset_ids=reference_asset_ids,
            metadata=metadata,
        )

    def _resolve_asset(
        self,
        asset_id: str,
        version_id: str | None = None,
    ) -> tuple[WorkflowAssetVersionV2, Path] | None:
        record = (
            self._asset_store.load_asset_version(asset_id, version_id)
            if version_id
            else self._asset_store.find_asset_version(asset_id=asset_id)
        )
        if record is None:
            return None
        validate_v2_relative_path(record.file_path, operation="v2-final-composition-asset-read")
        path = Path(record.file_path)
        absolute_path = path if path.is_absolute() else self._data_dir / path
        if not absolute_path.exists():
            return None
        return record, absolute_path

    def _probe_result(self, path: Path, media_type: str) -> V2MediaProbeResult:
        return V2MediaProbeResult.from_payload(
            self._probe(path, media_type),
            path=path,
            media_type=media_type,
        )

    @staticmethod
    def _valid_editor_output(
        *,
        output_path: Path,
        probe: V2MediaProbeResult,
        canvas: V2CompositionCanvas,
        expected_audio: bool,
    ) -> bool:
        if not output_path.exists() or output_path.stat().st_size <= 0:
            return False
        if probe.error or not probe.video_codec:
            return False
        if probe.width != canvas.width or probe.height != canvas.height:
            return False
        if probe.fps is None or abs(probe.fps - canvas.fps) > 0.1:
            return False
        if (
            probe.duration_seconds is None
            or abs(probe.duration_seconds - canvas.duration_seconds) > 0.15
        ):
            return False
        return not expected_audio or probe.has_audio

    def _mock_ffmpeg_args(
        self,
        *,
        output_path: Path,
        codec: str,
        include_audio: bool,
        duration_seconds: float,
        width: int,
        height: int,
    ) -> list[str]:
        duration = min(max(duration_seconds, 0.2), 1.0)
        args = [
            self._settings.ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={width}x{height}:r=24:d={duration:.3f}",
        ]
        if include_audio:
            args.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-shortest",
                    *self._video_codec_args(codec),
                    "-c:a",
                    "aac",
                ]
            )
        else:
            args.extend([*self._video_codec_args(codec), "-an"])
        args.append(output_path.as_posix())
        return args

    def _concat_ffmpeg_args(
        self,
        *,
        work_dir: Path,
        output_path: Path,
        video_paths: list[Path],
        bgm_path: Path | None,
        duration_seconds: float,
        codec: str,
        audio_codec: str,
        audio_mix_strategy: str,
        output_width: int,
        output_height: int,
    ) -> list[str]:
        concat_list = work_dir / "concat-list.txt"
        concat_list.write_text(
            "".join(f"file '{_escape_concat_path(path)}'\n" for path in video_paths),
            encoding="utf-8",
        )
        args = [
            self._settings.ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_list.as_posix(),
        ]
        video_args = [
            "-map",
            "0:v:0",
            *self._video_codec_args(codec),
            "-vf",
            f"scale={output_width}:{output_height}",
        ]
        if audio_mix_strategy == "source_audio_plus_bgm" and bgm_path is not None:
            args.extend(
                [
                    "-stream_loop",
                    "-1",
                    "-i",
                    bgm_path.as_posix(),
                    "-filter_complex",
                    (
                        f"[1:a:0]atrim=duration={duration_seconds:.3f}[bgm];"
                        "[0:a:0][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]"
                    ),
                    "-map",
                    "0:v:0",
                    "-map",
                    "[aout]",
                    "-shortest",
                    *self._video_codec_args(codec),
                    "-vf",
                    f"scale={output_width}:{output_height}",
                    "-c:a",
                    audio_codec,
                ]
            )
        elif audio_mix_strategy == "source_audio_only":
            args.extend([*video_args, "-map", "0:a?", "-shortest", "-c:a", audio_codec])
        elif audio_mix_strategy == "bgm_only" and bgm_path is not None:
            args.extend(
                [
                    "-stream_loop",
                    "-1",
                    "-i",
                    bgm_path.as_posix(),
                    "-filter_complex",
                    f"[1:a:0]atrim=duration={duration_seconds:.3f}[bgm]",
                    *video_args,
                    "-map",
                    "[bgm]",
                    "-t",
                    f"{duration_seconds:.3f}",
                    "-c:a",
                    audio_codec,
                ]
            )
        else:
            args.extend([*video_args, "-an"])
        args.append(output_path.as_posix())
        return args

    def _video_codec_args(self, codec: str) -> list[str]:
        args = ["-c:v", codec]
        if codec != "copy":
            args.extend(["-pix_fmt", "yuv420p"])
        return args

    def _failure(
        self,
        provider_payload: dict[str, Any],
        reference_asset_ids: list[str],
        *,
        code: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> V2ProviderResult:
        return V2ProviderResult(
            status="failed",
            media_type="video",
            provider=FINAL_COMPOSITION_PROVIDER,
            provider_model="ffmpeg",
            provider_payload_snapshot=provider_payload,
            reference_asset_ids=list(reference_asset_ids),
            error_code=code,
            error_message=message,
            metadata={
                "provider": FINAL_COMPOSITION_PROVIDER,
                "composition_provider": FINAL_COMPOSITION_PROVIDER,
                **sanitize_context_for_llm_text(metadata or {}),
            },
        )


def _ordered_clips(timeline_clips: list[dict[str, Any]], *, clip_type: str) -> list[dict[str, Any]]:
    return sorted(
        [clip for clip in timeline_clips if clip.get("clip_type") == clip_type],
        key=lambda clip: (
            _float(clip.get("track_index")),
            _float(clip.get("start_time")),
            _float(clip.get("order")),
            str(clip.get("clip_id") or ""),
        ),
    )


def _safe_render_id(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("render_"):
        return None
    if not value.replace("_", "").isalnum() or len(value) > 80:
        return None
    return value


def _ordered_source_asset_ids(timeline_clips: list[dict[str, Any]]) -> list[str]:
    asset_ids: list[str] = []
    for clip in timeline_clips:
        asset_id = _string(clip.get("source_asset_id"))
        if asset_id is not None:
            asset_ids.append(asset_id)
    return list(dict.fromkeys(asset_ids))


def _muted_output_requested(
    workflow: WorkflowV2,
    payload: dict[str, Any],
    timeline_plan: dict[str, Any],
) -> bool:
    if workflow.audio_mode == "none":
        return True
    render_settings = (
        timeline_plan.get("render_settings")
        if isinstance(timeline_plan.get("render_settings"), dict)
        else {}
    )
    for values in (payload, render_settings):
        if any(bool(values.get(key)) for key in ("mute", "muted", "strip_audio")):
            return True
        if str(values.get("audio_policy") or "").strip() == "muted":
            return True
    return False


def _timeline_requires_bgm(
    payload: dict[str, Any],
    timeline_plan: dict[str, Any],
) -> bool:
    render_settings = (
        timeline_plan.get("render_settings")
        if isinstance(timeline_plan.get("render_settings"), dict)
        else {}
    )
    for values in (payload, timeline_plan, render_settings):
        if any(
            bool(values.get(key))
            for key in ("bgm_required", "requires_bgm", "require_bgm", "audio_required")
        ):
            return True
    dependencies = timeline_plan.get("dependencies")
    if isinstance(dependencies, list):
        return any(
            isinstance(dependency, dict)
            and str(dependency.get("slot_type") or dependency.get("type") or "") == "bgm_audio"
            and bool(dependency.get("required"))
            for dependency in dependencies
        )
    return False


def _audio_mix_strategy(
    *,
    muted_by_policy: bool,
    video_probes: list[V2MediaProbeResult],
    bgm_probe: V2MediaProbeResult | None,
) -> str:
    if muted_by_policy:
        return "muted_by_policy"
    source_has_audio = any(probe.has_audio for probe in video_probes)
    bgm_has_audio = bool(bgm_probe and bgm_probe.has_audio)
    if source_has_audio and bgm_has_audio:
        return "source_audio_plus_bgm"
    if source_has_audio:
        return "source_audio_only"
    if bgm_has_audio:
        return "bgm_only"
    return "silent_source"


def _select_output_resolution(
    *,
    workflow: WorkflowV2,
    payload: dict[str, Any],
    timeline_plan: dict[str, Any],
    video_probes: list[V2MediaProbeResult],
) -> tuple[int, int, str]:
    explicit = _explicit_export_resolution(payload, timeline_plan)
    if explicit is not None:
        return (*explicit, "explicit_export_resolution")
    first = video_probes[0] if video_probes else None
    if first is not None and first.width and first.height:
        return first.width, first.height, "first_source_clip"
    probed = [probe for probe in video_probes if probe.width and probe.height and probe.width > 0]
    if probed:
        selected = max(probed, key=lambda probe: int(probe.width or 0) * int(probe.height or 0))
        return int(selected.width or 0), int(selected.height or 0), "highest_area_source_clip"
    width, height = _resolution(workflow.aspect_ratio)
    return width, height, "aspect_ratio_fallback"


def _explicit_export_resolution(
    payload: dict[str, Any],
    timeline_plan: dict[str, Any],
) -> tuple[int, int] | None:
    render_settings = (
        timeline_plan.get("render_settings")
        if isinstance(timeline_plan.get("render_settings"), dict)
        else {}
    )
    for values in (payload, timeline_plan, render_settings):
        for key in ("export_resolution", "output_resolution", "resolution"):
            parsed = _parse_resolution(values.get(key))
            if parsed is not None:
                return parsed
    return None


def _parse_resolution(value: object) -> tuple[int, int] | None:
    if isinstance(value, dict):
        width = _int_or_none(value.get("width"))
        height = _int_or_none(value.get("height"))
        if width and height and width > 0 and height > 0:
            return width, height
    if isinstance(value, str):
        normalized = value.strip().lower().replace(" ", "")
        if "x" in normalized:
            left, right = normalized.split("x", 1)
            width = _int_or_none(left)
            height = _int_or_none(right)
            if width and height and width > 0 and height > 0:
                return width, height
    return None


def _audio_sources(
    *,
    video_inputs: list[tuple[dict[str, Any], WorkflowAssetVersionV2, Path]],
    video_probes: list[V2MediaProbeResult],
    bgm_input: tuple[WorkflowAssetVersionV2, Path] | None,
    bgm_probe: V2MediaProbeResult | None,
    audio_mix_strategy: str,
) -> list[dict[str, Any]]:
    if audio_mix_strategy == "muted_by_policy":
        return []
    sources: list[dict[str, Any]] = []
    for (_clip, record, _path), probe in zip(video_inputs, video_probes, strict=False):
        if not probe.has_audio:
            continue
        sources.append(
            {
                "asset_id": record.asset_id,
                "source_type": "video",
                "audio_codec": probe.audio_codec,
            }
        )
    if bgm_input is not None and bgm_probe is not None and bgm_probe.has_audio:
        sources.append(
            {
                "asset_id": bgm_input[0].asset_id,
                "source_type": "bgm",
                "audio_codec": bgm_probe.audio_codec,
            }
        )
    return sources


def _source_video_dimensions(
    video_inputs: list[tuple[dict[str, Any], WorkflowAssetVersionV2, Path]],
    video_probes: list[V2MediaProbeResult],
) -> list[dict[str, Any]]:
    dimensions: list[dict[str, Any]] = []
    for (_clip, record, _path), probe in zip(video_inputs, video_probes, strict=False):
        dimensions.append(
            {
                "asset_id": record.asset_id,
                "width": probe.width,
                "height": probe.height,
                "has_audio": probe.has_audio,
                "audio_codec": probe.audio_codec,
                "video_codec": probe.video_codec,
            }
        )
    return dimensions


def _bgm_missing_policy(
    *,
    bgm_input: tuple[WorkflowAssetVersionV2, Path] | None,
    audio_mix_strategy: str,
) -> str | None:
    if bgm_input is not None:
        return None
    if audio_mix_strategy == "source_audio_only":
        return "source_audio_only"
    if audio_mix_strategy == "muted_by_policy":
        return "muted_by_policy"
    if audio_mix_strategy == "silent_source":
        return "silent_source"
    return None


def _resolution(aspect_ratio: str) -> tuple[int, int]:
    normalized = aspect_ratio.strip()
    if normalized == "9:16":
        return 360, 640
    if normalized == "1:1":
        return 512, 512
    return 640, 360


def _float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    parsed = _float(value)
    return parsed if parsed else None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None


def _string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _canonical_render_settings(
    payload: dict[str, Any],
) -> WorkflowV2TimelineRenderSettings:
    timeline_plan = payload.get("timeline_plan")
    raw_settings = (
        timeline_plan.get("render_settings")
        if isinstance(timeline_plan, dict)
        and isinstance(timeline_plan.get("render_settings"), dict)
        else {}
    )
    return WorkflowV2TimelineRenderSettings.model_validate(raw_settings)


def _probe_duration(
    payload: dict[str, Any],
    video_stream: dict[str, Any],
    audio_stream: dict[str, Any],
) -> float | None:
    format_payload = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    for value in (
        video_stream.get("duration"),
        audio_stream.get("duration"),
        format_payload.get("duration"),
    ):
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _frame_rate(value: object) -> float | None:
    if not isinstance(value, str) or not value.strip() or value == "0/0":
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        top = _float(numerator)
        bottom = _float(denominator)
        if top and bottom:
            return round(top / bottom, 3)
        return None
    return _float_or_none(value)


def _ffprobe_path(ffmpeg_path: str) -> str:
    path = Path(ffmpeg_path)
    if path.name == "ffmpeg":
        return (path.parent / "ffprobe").as_posix() if str(path.parent) != "." else "ffprobe"
    return "ffprobe"


def _next_video_codec(current_codec: str, stderr: str | None) -> str | None:
    if not _encoder_missing(stderr):
        return None
    if current_codec in FINAL_VIDEO_CODEC_FALLBACKS:
        index = FINAL_VIDEO_CODEC_FALLBACKS.index(current_codec)
        for candidate in FINAL_VIDEO_CODEC_FALLBACKS[index + 1 :]:
            return candidate
        return None
    return FINAL_VIDEO_CODEC_FALLBACKS[0]


def _encoder_missing(stderr: str | None) -> bool:
    normalized = (stderr or "").lower()
    return (
        "unknown encoder" in normalized
        or "encoder" in normalized
        and "not found" in normalized
        or "error while opening encoder" in normalized
        or "incorrect library version" in normalized
    )


def _escape_concat_path(path: Path) -> str:
    return path.as_posix().replace("'", r"'\''")


def _truncate(value: str | None, limit: int = 2000) -> str | None:
    if value is None:
        return None
    return value[-limit:] if len(value) > limit else value
