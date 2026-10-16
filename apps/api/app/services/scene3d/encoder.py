"""PNG sequence to MP4 encoder using ffmpeg.

Reuses the project's existing ffmpeg foundation (app/tools/ffmpeg.py)
for encoding rendered PNG frames into H.264 MP4.

See: docs/3d-previs/blender-integration-guide.md (known issue: Blender
FFMPEG enum unavailable after loading .blend, so we render PNGs and encode
with ffmpeg).
"""

from __future__ import annotations

import os
import tempfile
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EncodeResult:
    """Result of PNG-to-MP4 encoding."""

    success: bool
    output_path: str | None = None
    frame_count: int = 0
    error: str | None = None


@dataclass
class MuxResult:
    """Result of muxing audio into a video."""

    success: bool
    output_path: str | None = None
    error: str | None = None


_FRAME_NAME_RE = re.compile(r"^frame_(\d+)\.png$")


def _numeric_frame_sort_key(path: Path) -> int:
    match = _FRAME_NAME_RE.match(path.name)
    return int(match.group(1)) if match else 0


def _frame_durations(frame_numbers: list[int], fps: int) -> list[float]:
    """How long each frame should be on screen, in seconds.

    A full animation is evenly spaced, so every gap is one frame and this
    returns ``1 / fps`` throughout -- exactly the fixed duration the encoder
    always used.  A *draft* pass renders only each shot's keyframes, so its
    gaps are tens of frames wide; giving each still the run-up to the next one
    keeps the cut roughly the length of the real animation instead of
    compressing 24 keyframes into under a second.  Without this, the draft
    previs is unwatchable and any downstream consumer that measures the clip
    against the scene duration sees a 0.8s file where it expected 24s.
    """

    single = 1.0 / fps if fps > 0 else 1.0
    durations: list[float] = []
    for index, number in enumerate(frame_numbers):
        if index + 1 < len(frame_numbers):
            gap = frame_numbers[index + 1] - number
        elif durations:
            # Tail frame: no measured gap, so repeat the last known one.  For a
            # full animation that is one frame; for a draft it borrows the
            # closing shot's keyframe spacing.
            gap = number - frame_numbers[index - 1]
        else:
            gap = 1
        durations.append(max(gap, 1) / fps if fps > 0 else float(max(gap, 1)))
    if not durations:
        return [single]
    return durations


def _frame_repeat_counts(durations: list[float], fps: int) -> list[int]:
    """Turn per-still seconds into how many manifest entries each still needs.

    A concat manifest can only express timing two ways, and only one of them
    survives ffmpeg's constant-frame-rate resampler:

    * one entry per still carrying a wide ``duration`` -- the demuxer honours
      it, but ``-r <fps>`` then *resamples* the stream, duplicating every still
      until it fills its duration and inflating the clip.  A 5-keyframe draft
      of a 20s shot came out as 717 frames / 29.9s instead of ~480 / 20s.
    * one entry per *output frame*, each carrying ``1 / fps`` -- the stream is
      constant-rate before the encoder ever sees it, so ``-r <fps>`` becomes a
      no-op that only labels the container.

    This returns the counts for the second shape, which is the only one whose
    encoded frame count is exact.
    """

    if fps > 0:
        return [max(1, int(round(duration * fps + 1e-6))) for duration in durations]
    return [max(1, int(round(duration))) for duration in durations]


def encode_png_sequence(
    input_dir: str,
    output_path: str,
    fps: int = 30,
    crf: int = 23,
    preset: str = "medium",
) -> EncodeResult:
    """Encode a directory of PNG frames into an H.264 MP4.

    Expects frames named frame_0001.png, frame_0002.png, etc.
    (Blender's default output pattern with filepath ending in 'frame_').
    Frame numbers are parsed numerically so sequences longer than 9999
    frames survive without the 4-digit ffmpeg pattern truncating them.

    Args:
        input_dir: Directory containing PNG frames.
        output_path: Output MP4 path.
        fps: Frames per second.
        crf: Constant rate factor (quality, lower=better).
        preset: Encoding preset (ultrafast ... veryslow).

    Returns:
        EncodeResult with success status and output path.
    """
    frame_files = sorted(
        (p for p in Path(input_dir).glob("frame_*.png") if _FRAME_NAME_RE.match(p.name)),
        key=_numeric_frame_sort_key,
    )
    if not frame_files:
        return EncodeResult(success=False, error=f"No PNG frames found in {input_dir}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Use the concat *demuxer* (not filter): write a manifest listing each
    # output frame with an explicit duration, then feed ffmpeg one input. The
    # concat-filter approach with per-frame -i inputs collapses to ~0s
    # because single-PNG inputs do not carry a usable duration.
    #
    # Each still is repeated once per output frame it occupies rather than
    # listed once with a wide duration: a wide duration makes the stream
    # variable-rate, and the ``-r`` below then resamples it, duplicating every
    # still to fill its duration and inflating a keyframe draft from ~480
    # frames into 717.  Repeating the entries makes the stream constant-rate
    # first, so ``-r`` only stamps the container's nominal rate.
    #
    # The trailing duplicate of the last file is deliberately absent: with
    # per-entry ``duration`` lines it makes the demuxer collapse the whole
    # sequence to a handful of frames.
    # PNG inputs otherwise inherit the image demuxer's default 25fps timebase.
    # Durations alone do not fix that: at 30fps a 60-PNG sequence became 61
    # encoded frames and repeated/dropped intermediate images. Set each file's
    # input rate before concat timestamps are quantized, not by trimming output.
    frame_numbers = [_numeric_frame_sort_key(frame) for frame in frame_files]
    durations = _frame_durations(frame_numbers, fps)
    repeat_counts = _frame_repeat_counts(durations, fps)
    single_duration = 1.0 / fps if fps > 0 else 1.0

    manifest_dir = tempfile.mkdtemp(prefix="scene3d_concat_")
    manifest_path = os.path.join(manifest_dir, "concat.txt")
    try:
        with open(manifest_path, "w", encoding="utf-8") as mf:
            for frame, count in zip(frame_files, repeat_counts):
                safe_path = str(frame).replace("\\", "/")
                for _ in range(count):
                    mf.write(f"file '{safe_path}'\n")
                    mf.write(f"option framerate {fps}\n")
                    mf.write(f"duration {single_duration:.6f}\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", manifest_path,
            "-r", str(fps),
            "-c:v", "libx264",
            "-preset", preset,
            "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            output_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except FileNotFoundError:
            return EncodeResult(
                success=False,
                frame_count=len(frame_files),
                error="ffmpeg not found on PATH",
            )
        except subprocess.TimeoutExpired:
            return EncodeResult(
                success=False,
                frame_count=len(frame_files),
                error="ffmpeg encoding timed out",
            )

        if result.returncode != 0:
            error_tail = (result.stderr or "")[-500:]
            return EncodeResult(
                success=False,
                frame_count=len(frame_files),
                error=f"ffmpeg exited with code {result.returncode}: {error_tail}",
            )
        if not os.path.exists(output_path):
            return EncodeResult(
                success=False,
                frame_count=len(frame_files),
                error=f"Output file not created: {output_path}",
            )
        return EncodeResult(
            success=True,
            output_path=output_path,
            frame_count=len(frame_files),
        )
    finally:
        shutil.rmtree(manifest_dir, ignore_errors=True)


def mux_audio_to_video(
    video_path: str,
    audio_path: str,
    output_path: str,
) -> MuxResult:
    """Mux an audio track into a video file using ffmpeg.

    Uses -c:v copy to avoid re-encoding the video (fast), and encodes
    audio to AAC. The -shortest flag ensures output duration matches
    the shorter of the two inputs.

    Args:
        video_path: Path to the input video file (MP4).
        audio_path: Path to the input audio file (MP3/WAV/etc).
        output_path: Path for the output video with audio.

    Returns:
        MuxResult with success status and output path.
    """
    if not os.path.exists(video_path):
        return MuxResult(success=False, error=f"Video file not found: {video_path}")
    if not os.path.exists(audio_path):
        return MuxResult(success=False, error=f"Audio file not found: {audio_path}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            error_tail = (result.stderr or "")[-500:]
            return MuxResult(
                success=False,
                error=f"ffmpeg mux exited with code {result.returncode}: {error_tail}",
            )
        if not os.path.exists(output_path):
            return MuxResult(
                success=False,
                error=f"Output file not created: {output_path}",
            )
        return MuxResult(success=True, output_path=output_path)
    except FileNotFoundError:
        return MuxResult(success=False, error="ffmpeg not found on PATH")
    except subprocess.TimeoutExpired:
        return MuxResult(success=False, error="ffmpeg mux timed out after 300s")
