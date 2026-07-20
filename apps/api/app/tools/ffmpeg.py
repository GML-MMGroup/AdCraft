from dataclasses import dataclass
from pathlib import Path
import subprocess

from app.schemas.video_editing import ExportSettings, Watermark

VIDEO_CODEC_FALLBACKS = ("libx264", "libopenh264", "h264", "mpeg4")


@dataclass(frozen=True)
class FfmpegResult:
    command: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class FfmpegTool:
    def __init__(self, ffmpeg_path: str = "ffmpeg", dry_run: bool = False) -> None:
        self._ffmpeg_path = ffmpeg_path
        self._dry_run = dry_run

    def trim_video(
        self,
        source_path: Path,
        output_path: Path,
        start_time: float,
        end_time: float,
    ) -> FfmpegResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self._ffmpeg_path,
            "-y",
            "-ss",
            _ffmpeg_number(start_time),
            "-i",
            source_path.as_posix(),
            "-t",
            _ffmpeg_number(end_time - start_time),
            "-c",
            "copy",
            output_path.as_posix(),
        ]
        return self._execute(command)

    def concat_videos(
        self,
        input_paths: list[Path],
        output_path: Path,
        concat_list_path: Path,
        export_settings: ExportSettings,
        reencode: bool = False,
    ) -> FfmpegResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        concat_list_path.parent.mkdir(parents=True, exist_ok=True)
        concat_list_path.write_text(
            "\n".join(f"file '{_escape_concat_path(path)}'" for path in input_paths) + "\n",
            encoding="utf-8",
        )
        command = [
            self._ffmpeg_path,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_list_path.as_posix(),
        ]
        if reencode:
            command.extend(_encoding_args(export_settings))
        else:
            command.extend(["-c", "copy"])
        command.append(output_path.as_posix())
        return self._execute(command)

    def burn_subtitles(
        self,
        source_path: Path,
        subtitle_path: Path,
        output_path: Path,
        export_settings: ExportSettings,
    ) -> FfmpegResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self._ffmpeg_path,
            "-y",
            "-i",
            source_path.as_posix(),
            "-vf",
            f"subtitles={_escape_filter_path(subtitle_path)}",
            "-c:v",
            export_settings.video_codec,
            "-c:a",
            "copy",
            output_path.as_posix(),
        ]
        return self._execute(command)

    def add_watermark(
        self,
        source_path: Path,
        watermark_path: Path,
        output_path: Path,
        watermark: Watermark,
        export_settings: ExportSettings,
    ) -> FfmpegResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        overlay = _overlay_expression(watermark)
        enable = _enable_expression(watermark)
        filter_complex = (
            f"[1:v]format=rgba,colorchannelmixer=aa={watermark.opacity},"
            f"scale=iw*{watermark.scale}:ih*{watermark.scale}[wm];"
            f"[0:v][wm]overlay={overlay}{enable}"
        )
        command = [
            self._ffmpeg_path,
            "-y",
            "-i",
            source_path.as_posix(),
            "-i",
            watermark_path.as_posix(),
            "-filter_complex",
            filter_complex,
            "-c:v",
            export_settings.video_codec,
            "-c:a",
            "copy",
            output_path.as_posix(),
        ]
        return self._execute(command)

    def transcode_video(
        self,
        source_path: Path,
        output_path: Path,
        export_settings: ExportSettings,
    ) -> FfmpegResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self._ffmpeg_path,
            "-y",
            "-i",
            source_path.as_posix(),
            *(_encoding_args(export_settings)),
            output_path.as_posix(),
        ]
        return self._execute(command)

    def export_timeline(self, command: list[str]) -> FfmpegResult:
        return self._execute(command)

    def available_video_encoders(self) -> set[str]:
        if self._dry_run:
            return set()
        result = self.run_command([self._ffmpeg_path, "-hide_banner", "-encoders"])
        if not result.ok:
            return set()
        return _parse_video_encoders(f"{result.stdout}\n{result.stderr}")

    def resolve_video_codec(self, preferred_codec: str | None) -> str:
        preferred = (preferred_codec or VIDEO_CODEC_FALLBACKS[0]).strip() or VIDEO_CODEC_FALLBACKS[
            0
        ]
        if self._dry_run:
            return preferred
        available = self.available_video_encoders()
        if not available:
            return preferred
        for codec in _codec_candidates(preferred):
            if codec in available:
                return codec
        return preferred

    def run_command(self, command: list[str]) -> FfmpegResult:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                text=True,
            )
        except OSError as exc:
            return FfmpegResult(command=command, returncode=1, stderr=str(exc))
        return FfmpegResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )

    def _execute(self, command: list[str]) -> FfmpegResult:
        if self._dry_run:
            return FfmpegResult(command=command, returncode=0)
        return self.run_command(command)


def _encoding_args(export_settings: ExportSettings) -> list[str]:
    return [
        "-vf",
        _scale_filter(export_settings),
        "-r",
        str(export_settings.fps),
        "-c:v",
        export_settings.video_codec,
        "-c:a",
        export_settings.audio_codec,
        "-b:v",
        export_settings.bitrate,
    ]


def _parse_video_encoders(output: str) -> set[str]:
    encoders: set[str] = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        flags, encoder = parts[0], parts[1]
        if flags.startswith("V"):
            encoders.add(encoder)
    return encoders


def _codec_candidates(preferred: str) -> list[str]:
    candidates: list[str] = []
    for codec in (preferred, *VIDEO_CODEC_FALLBACKS):
        if codec and codec not in candidates:
            candidates.append(codec)
    return candidates


def _scale_filter(export_settings: ExportSettings) -> str:
    height = {
        "480p": 480,
        "720p": 720,
        "1080p": 1080,
    }.get(export_settings.resolution.lower(), 480)
    if export_settings.aspect_ratio == "9:16":
        return f"scale={height}:-2,fps={export_settings.fps}"
    return f"scale=-2:{height},fps={export_settings.fps}"


def _overlay_expression(watermark: Watermark) -> str:
    positions = {
        "top-left": "20:20",
        "top-right": "main_w-overlay_w-20:20",
        "bottom-left": "20:main_h-overlay_h-20",
        "bottom-right": "main_w-overlay_w-20:main_h-overlay_h-20",
        "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
    }
    return positions[watermark.position]


def _enable_expression(watermark: Watermark) -> str:
    if watermark.end_time is None:
        return f":enable='gte(t,{_ffmpeg_number(watermark.start_time)})'"
    return (
        ":enable='between(t,"
        f"{_ffmpeg_number(watermark.start_time)},{_ffmpeg_number(watermark.end_time)})'"
    )


def _escape_concat_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "'\\''")


def _escape_filter_path(path: Path) -> str:
    return path.resolve().as_posix().replace("\\", "\\\\").replace(":", "\\:")


def _ffmpeg_number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")
