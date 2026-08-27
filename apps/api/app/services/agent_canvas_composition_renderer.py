"""FFmpeg renderer for ordered Agent Canvas Editing inputs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import subprocess

from app.core.config import Settings
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_editing import (
    EditingBgmEntryV2,
    EditingOutputSettingsV2,
    EditingVideoEntryV2,
)
from app.services.agent_canvas_editing import ResolvedEditingInputs, ResolvedEditingMedia
from app.services.agent_canvas_editing_timeline import TIMELINE_EPSILON
from app.services.v2_final_composition_renderer import (
    V2MediaProbe,
    V2MediaProbeResult,
)
from app.services.v2_media_toolchain_capabilities import V2MediaToolchainCapabilityService


Runner = Callable[..., subprocess.CompletedProcess[str]]
Probe = Callable[[Path, str], V2MediaProbeResult]


@dataclass(frozen=True, slots=True)
class EditingRenderResult:
    output_path: Path
    width: int
    height: int
    duration_seconds: float
    ffmpeg_command: tuple[str, ...]
    video_encoder: str


class AgentCanvasCompositionRenderer:
    """Normalize ordered clips, preserve native audio, and optionally mix BGM."""

    def __init__(
        self,
        settings: Settings,
        *,
        runner: Runner | None = None,
        probe: Probe | None = None,
        encoder: str | None = None,
    ) -> None:
        self._settings = settings
        self._runner = runner or subprocess.run
        self._probe = probe or V2MediaProbe(ffprobe_path=settings.ffprobe_path)
        self._encoder = encoder

    def render(
        self,
        inputs: ResolvedEditingInputs,
        output: EditingOutputSettingsV2,
        *,
        staging_path: Path,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> EditingRenderResult:
        probes = tuple(self._require_video(item.path) for item in inputs.videos)
        width, height = _output_geometry(output, probes[0])
        fps = output.fps or probes[0].fps or 30.0
        encoder = self._encoder or self._configured_encoder()
        timeline_duration = _timeline_duration(inputs, probes)
        if cancelled():
            raise _error("editing_export_cancelled", "Editing Export was cancelled.")
        command = self._command(
            inputs,
            probes,
            width=width,
            height=height,
            fps=fps,
            encoder=encoder,
            timeline_duration=timeline_duration,
            staging_path=staging_path,
        )
        staging_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            completed = self._runner(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=3600,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise _error(
                "editing_ffmpeg_failed",
                "Editing Export could not run the configured FFmpeg toolchain.",
            ) from error
        if completed.returncode != 0:
            raise _error(
                "editing_ffmpeg_failed",
                _safe_ffmpeg_error(completed.stderr or completed.stdout),
            )
        if cancelled():
            staging_path.unlink(missing_ok=True)
            raise _error("editing_export_cancelled", "Editing Export was cancelled.")
        rendered = self._probe(staging_path, "video")
        if (
            rendered.error
            or rendered.width != width
            or rendered.height != height
            or not staging_path.is_file()
            or not _duration_matches(rendered.duration_seconds, timeline_duration)
        ):
            raise _error(
                "editing_output_invalid",
                "Editing Export output failed media validation.",
            )
        return EditingRenderResult(
            output_path=staging_path,
            width=width,
            height=height,
            duration_seconds=rendered.duration_seconds or timeline_duration,
            ffmpeg_command=tuple(command),
            video_encoder=encoder,
        )

    def recover(
        self,
        inputs: ResolvedEditingInputs,
        output: EditingOutputSettingsV2,
        *,
        staging_path: Path,
    ) -> EditingRenderResult:
        """Validate and reuse a completed staging file after process restart."""

        first = self._require_video(inputs.videos[0].path)
        width, height = _output_geometry(output, first)
        timeline_duration = _timeline_duration(
            inputs,
            tuple(self._require_video(item.path) for item in inputs.videos),
        )
        rendered = self._probe(staging_path, "video")
        if (
            rendered.error
            or rendered.width != width
            or rendered.height != height
            or not staging_path.is_file()
            or not _duration_matches(rendered.duration_seconds, timeline_duration)
        ):
            raise _error(
                "editing_output_invalid",
                "Recovered Editing output failed media validation.",
            )
        return EditingRenderResult(
            output_path=staging_path,
            width=width,
            height=height,
            duration_seconds=rendered.duration_seconds or timeline_duration,
            ffmpeg_command=(),
            video_encoder=self._encoder or self._configured_encoder(),
        )

    def fingerprint_payload(self) -> dict[str, object]:
        """Return non-secret renderer identity used by export idempotency."""

        snapshot = V2MediaToolchainCapabilityService(self._settings).snapshot()
        return {
            "contract": "agent-canvas-composition-renderer-v2",
            "ffmpeg_fingerprint": snapshot.ffmpeg_fingerprint,
            "ffprobe_fingerprint": snapshot.ffprobe_fingerprint,
            "video_encoder": self._encoder or snapshot.selected_video_encoder,
            "audio_encoder": snapshot.audio_encoder,
        }

    def _command(
        self,
        inputs: ResolvedEditingInputs,
        probes: tuple[V2MediaProbeResult, ...],
        *,
        width: int,
        height: int,
        fps: float,
        encoder: str,
        timeline_duration: float,
        staging_path: Path,
    ) -> list[str]:
        command = [self._settings.ffmpeg_path, "-y"]
        for item in inputs.videos:
            command.extend(["-i", item.path.as_posix()])
        if inputs.bgm is not None:
            command.extend(["-stream_loop", "-1", "-i", inputs.bgm.path.as_posix()])
        filters: list[str] = []
        concat_inputs: list[str] = []
        render_items = sorted(
            zip(range(len(inputs.videos)), inputs.videos, probes, strict=True),
            key=lambda item: (
                _video_entry(item[1]).timeline_start_seconds
                if _video_entry(item[1]).timeline_start_seconds is not None
                else 0.0,
                _video_entry(item[1]).source_key,
                item[0],
            ),
        )
        cursor = 0.0
        piece_index = 0
        for input_index, media, probe in render_items:
            entry = _video_entry(media)
            duration = _effective_duration(entry, probe)
            start = entry.timeline_start_seconds
            if start is None:
                start = cursor
            if start < cursor - TIMELINE_EPSILON:
                raise _error(
                    "editing_timeline_overlap",
                    "Editing video inputs overlap on the fixed timeline.",
                )
            if start > cursor + TIMELINE_EPSILON:
                gap_duration = start - cursor
                filters.extend(
                    _gap_filters(
                        piece_index,
                        gap_duration,
                        width=width,
                        height=height,
                        fps=fps,
                    )
                )
                concat_inputs.extend((f"[vgap{piece_index}]", f"[agap{piece_index}]"))
                piece_index += 1
            trim = _trim_filter(
                entry.trim_start_seconds,
                entry.trim_end_seconds,
            )
            geometry = _geometry_filter(entry.fit_mode, width=width, height=height)
            video_filters = [
                trim,
                geometry,
                "setsar=1",
                f"fps={fps:.6f}",
                "format=yuv420p",
            ]
            if entry.transition == "fade" and entry.transition_duration_seconds > 0:
                fade_start = max(duration - entry.transition_duration_seconds, 0.0)
                video_filters.append(
                    f"fade=t=out:st={fade_start:.6f}:d={entry.transition_duration_seconds:.6f}"
                )
            video_filters.append("setpts=PTS-STARTPTS")
            filters.append(f"[{input_index}:v:0]" + ",".join(video_filters) + f"[v{piece_index}]")
            if probe.has_audio and entry.preserve_native_audio:
                audio_filters = [
                    _trim_filter(
                        entry.trim_start_seconds,
                        entry.trim_end_seconds,
                        audio=True,
                    ),
                    f"volume={entry.volume:.6f}",
                ]
                if entry.transition == "fade" and entry.transition_duration_seconds > 0:
                    fade_start = max(duration - entry.transition_duration_seconds, 0.0)
                    audio_filters.append(
                        f"afade=t=out:st={fade_start:.6f}:d={entry.transition_duration_seconds:.6f}"
                    )
                audio_filters.extend(
                    (
                        "aresample=48000",
                        "aformat=sample_fmts=fltp:channel_layouts=stereo",
                        "asetpts=PTS-STARTPTS",
                    )
                )
                filters.append(
                    f"[{input_index}:a:0]" + ",".join(audio_filters) + f"[a{piece_index}]"
                )
            else:
                filters.append(
                    "anullsrc=r=48000:cl=stereo,"
                    f"atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[a{piece_index}]"
                )
            concat_inputs.extend((f"[v{piece_index}]", f"[a{piece_index}]"))
            piece_index += 1
            cursor = start + duration
            if cursor > timeline_duration + TIMELINE_EPSILON:
                raise _error(
                    "editing_timeline_out_of_bounds",
                    "Editing video inputs exceed the fixed timeline duration.",
                )
        if cursor < timeline_duration - TIMELINE_EPSILON:
            gap_duration = timeline_duration - cursor
            filters.extend(
                _gap_filters(
                    piece_index,
                    gap_duration,
                    width=width,
                    height=height,
                    fps=fps,
                )
            )
            concat_inputs.extend((f"[vgap{piece_index}]", f"[agap{piece_index}]"))
            piece_index += 1
        filters.append("".join(concat_inputs) + f"concat=n={piece_index}:v=1:a=1[vcat][acat]")
        audio_label = "[acat]"
        if inputs.bgm is not None:
            bgm_index = len(probes)
            bgm_entry = _bgm_entry(inputs.bgm)
            bgm_duration = (
                bgm_entry.trim_end_seconds - bgm_entry.trim_start_seconds
                if bgm_entry.trim_end_seconds is not None
                else max(timeline_duration - bgm_entry.trim_start_seconds, 0.001)
            )
            bgm_filters = [
                _trim_filter(
                    bgm_entry.trim_start_seconds,
                    bgm_entry.trim_end_seconds,
                    audio=True,
                ),
                f"volume={bgm_entry.volume:.6f}",
            ]
            if bgm_entry.trim_end_seconds is None:
                bgm_filters.append(f"atrim=duration={bgm_duration:.6f}")
            if bgm_entry.fade_in_seconds > 0:
                bgm_filters.append(f"afade=t=in:st=0:d={bgm_entry.fade_in_seconds:.6f}")
            if bgm_entry.fade_out_seconds > 0:
                fade_start = max(bgm_duration - bgm_entry.fade_out_seconds, 0.0)
                bgm_filters.append(
                    f"afade=t=out:st={fade_start:.6f}:d={bgm_entry.fade_out_seconds:.6f}"
                )
            bgm_filters.extend(
                (
                    "aresample=48000",
                    "aformat=sample_fmts=fltp:channel_layouts=stereo",
                )
            )
            filters.append(f"[{bgm_index}:a:0]" + ",".join(bgm_filters) + "[bgm]")
            filters.append(
                "[acat][bgm]amix=inputs=2:duration=first:"
                "dropout_transition=0:normalize=0,"
                "alimiter=limit=0.95[amixed]"
            )
            audio_label = "[amixed]"
        filters.append(
            f"[vcat]tpad=stop_mode=add:stop_duration={timeline_duration:.6f},"
            f"trim=duration={timeline_duration:.6f},setpts=PTS-STARTPTS[vout]"
        )
        filters.append(
            f"{audio_label}apad=pad_dur={timeline_duration:.6f},"
            f"atrim=duration={timeline_duration:.6f},asetpts=PTS-STARTPTS[aout]"
        )
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-c:v",
                encoder,
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                staging_path.as_posix(),
            ]
        )
        return command

    def _require_video(self, path: Path) -> V2MediaProbeResult:
        result = self._probe(path, "video")
        if result.error or not result.width or not result.height:
            raise _error(
                "editing_source_media_invalid",
                "An Editing video input failed media validation.",
            )
        return result

    def _configured_encoder(self) -> str:
        capabilities = V2MediaToolchainCapabilityService(self._settings).snapshot()
        if (
            not capabilities.selected_video_encoder
            or not capabilities.feature_flags.get("visual_composition", False)
            or not capabilities.feature_flags.get("source_audio", False)
        ):
            raise _error(
                "editing_ffmpeg_unsupported",
                "Required Editing FFmpeg capabilities are unavailable.",
            )
        return capabilities.selected_video_encoder


def _video_entry(media: ResolvedEditingMedia) -> EditingVideoEntryV2:
    if media.video_entry is not None:
        return media.video_entry
    if media.binding_id is not None:
        return EditingVideoEntryV2(binding_id=media.binding_id)
    return EditingVideoEntryV2(asset_id=media.asset.asset_id)


def _bgm_entry(media: ResolvedEditingMedia) -> EditingBgmEntryV2:
    if media.bgm_entry is not None:
        return media.bgm_entry
    if media.binding_id is not None:
        return EditingBgmEntryV2(binding_id=media.binding_id)
    return EditingBgmEntryV2(asset_id=media.asset.asset_id)


def _effective_duration(
    entry: EditingVideoEntryV2,
    probe: V2MediaProbeResult,
) -> float:
    if (
        probe.duration_seconds is not None
        and entry.trim_start_seconds >= probe.duration_seconds - TIMELINE_EPSILON
    ):
        raise _error(
            "editing_timeline_duration_invalid",
            "Editing trim start exceeds the source media duration.",
        )
    end = entry.trim_end_seconds
    if end is None:
        end = probe.duration_seconds or entry.trim_start_seconds + 0.001
    if probe.duration_seconds is not None and end > probe.duration_seconds + TIMELINE_EPSILON:
        raise _error(
            "editing_timeline_duration_invalid",
            "Editing trim end exceeds the source media duration.",
        )
    return max(end - entry.trim_start_seconds, 0.001)


def _timeline_duration(
    inputs: ResolvedEditingInputs,
    probes: tuple[V2MediaProbeResult, ...],
) -> float:
    if inputs.timeline_duration_seconds is not None:
        if inputs.timeline_duration_seconds <= TIMELINE_EPSILON:
            raise _error(
                "editing_timeline_duration_invalid",
                "Editing timeline duration must be positive.",
            )
        return inputs.timeline_duration_seconds
    return sum(probe.duration_seconds or 0.0 for probe in probes)


def _duration_matches(actual: float | None, expected: float) -> bool:
    return actual is not None and abs(actual - expected) <= max(0.05, expected * 0.02)


def _gap_filters(
    index: int,
    duration: float,
    *,
    width: int,
    height: int,
    fps: float,
) -> tuple[str, str]:
    return (
        f"color=c=black:s={width}x{height}:r={fps:.6f}:d={duration:.6f},"
        f"format=yuv420p,setpts=PTS-STARTPTS[vgap{index}]",
        f"anullsrc=r=48000:cl=stereo,atrim=duration={duration:.6f},"
        f"asetpts=PTS-STARTPTS[agap{index}]",
    )


def _trim_filter(
    start: float,
    end: float | None,
    *,
    audio: bool = False,
) -> str:
    name = "atrim" if audio else "trim"
    result = f"{name}=start={start:.6f}"
    if end is not None:
        result += f":end={end:.6f}"
    return result


def _geometry_filter(mode: str, *, width: int, height: int) -> str:
    if mode == "fit":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2"
    )


def _output_geometry(
    settings: EditingOutputSettingsV2,
    first: V2MediaProbeResult,
) -> tuple[int, int]:
    if settings.resolution:
        try:
            width_text, height_text = settings.resolution.lower().split("x", 1)
            width, height = int(width_text), int(height_text)
        except (TypeError, ValueError) as error:
            raise _error(
                "editing_output_geometry_invalid",
                "Editing output resolution must use WIDTHxHEIGHT.",
            ) from error
    else:
        width, height = first.width or 0, first.height or 0
    if width < 2 or height < 2:
        raise _error(
            "editing_output_geometry_invalid",
            "Editing output geometry is invalid.",
        )
    return width - (width % 2), height - (height % 2)


def _safe_ffmpeg_error(value: str) -> str:
    line = next((line.strip() for line in value.splitlines() if line.strip()), "")
    return f"Editing FFmpeg failed: {line[:300]}" if line else "Editing FFmpeg failed."


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_composition_renderer")
