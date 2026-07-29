"""FFmpeg renderer for ordered Agent Canvas Editing inputs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import subprocess

from app.core.config import Settings
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_editing import EditingOutputSettingsV2
from app.services.agent_canvas_editing import ResolvedEditingInputs
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
        bgm_volume: float,
        staging_path: Path,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> EditingRenderResult:
        probes = tuple(self._require_video(item.path) for item in inputs.videos)
        width, height = _output_geometry(output, probes[0])
        fps = output.fps or probes[0].fps or 30.0
        encoder = self._encoder or self._configured_encoder()
        if cancelled():
            raise _error("editing_export_cancelled", "Editing Export was cancelled.")
        command = self._command(
            inputs,
            probes,
            width=width,
            height=height,
            fps=fps,
            encoder=encoder,
            bgm_volume=bgm_volume,
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
        ):
            raise _error(
                "editing_output_invalid",
                "Editing Export output failed media validation.",
            )
        return EditingRenderResult(
            output_path=staging_path,
            width=width,
            height=height,
            duration_seconds=rendered.duration_seconds
            or sum(probe.duration_seconds or 0 for probe in probes),
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
        rendered = self._probe(staging_path, "video")
        if (
            rendered.error
            or rendered.width != width
            or rendered.height != height
            or not staging_path.is_file()
        ):
            raise _error(
                "editing_output_invalid",
                "Recovered Editing output failed media validation.",
            )
        return EditingRenderResult(
            output_path=staging_path,
            width=width,
            height=height,
            duration_seconds=rendered.duration_seconds or 0,
            ffmpeg_command=(),
            video_encoder=self._encoder or self._configured_encoder(),
        )

    def fingerprint_payload(self) -> dict[str, object]:
        """Return non-secret renderer identity used by export idempotency."""

        snapshot = V2MediaToolchainCapabilityService(self._settings).snapshot()
        return {
            "contract": "agent-canvas-composition-renderer-v1",
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
        bgm_volume: float,
        staging_path: Path,
    ) -> list[str]:
        command = [self._settings.ffmpeg_path, "-y"]
        for item in inputs.videos:
            command.extend(["-i", item.path.as_posix()])
        if inputs.bgm is not None:
            command.extend(["-stream_loop", "-1", "-i", inputs.bgm.path.as_posix()])
        filters: list[str] = []
        concat_inputs: list[str] = []
        for index, probe in enumerate(probes):
            filters.append(
                f"[{index}:v:0]"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                f"setsar=1,fps={fps:.6f},format=yuv420p,"
                "setpts=PTS-STARTPTS"
                f"[v{index}]"
            )
            if probe.has_audio:
                filters.append(
                    f"[{index}:a:0]aresample=48000,"
                    f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"asetpts=PTS-STARTPTS[a{index}]"
                )
            else:
                duration = max(probe.duration_seconds or 0.001, 0.001)
                filters.append(
                    "anullsrc=r=48000:cl=stereo,"
                    f"atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[a{index}]"
                )
            concat_inputs.extend((f"[v{index}]", f"[a{index}]"))
        filters.append("".join(concat_inputs) + f"concat=n={len(probes)}:v=1:a=1[vcat][acat]")
        audio_label = "[acat]"
        if inputs.bgm is not None:
            bgm_index = len(probes)
            filters.append(
                f"[{bgm_index}:a:0]volume={bgm_volume:.6f},"
                "aresample=48000,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo[bgm]"
            )
            filters.append(
                "[acat][bgm]amix=inputs=2:duration=first:"
                "dropout_transition=0:normalize=0,"
                "alimiter=limit=0.95[aout]"
            )
            audio_label = "[aout]"
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vcat]",
                "-map",
                audio_label,
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
