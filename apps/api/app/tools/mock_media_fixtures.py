"""Deterministic playable media fixtures for the unpaid Mock provider path."""

from __future__ import annotations

from pathlib import Path
import subprocess
from uuid import uuid4


class MockMediaFixtureError(RuntimeError):
    """Bounded failure while constructing a deterministic Mock media stream."""


def deterministic_mock_media_bytes(
    media_type: str,
    *,
    data_dir: Path,
    ffmpeg_path: str,
    native_audio: bool = False,
) -> bytes:
    """Build or reuse one probeable fixture below the isolated V2 data root."""

    fixture_dir = data_dir / "v2" / "mock-media-fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    if media_type == "image":
        path = fixture_dir / "image-1024x576.png"
        command = [
            ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x148A9C:s=1024x576",
            "-frames:v",
            "1",
            "-c:v",
            "png",
            "-f",
            "image2",
        ]
    elif media_type == "video":
        suffix = "-native-audio" if native_audio else ""
        path = fixture_dir / f"video-15s-1280x720{suffix}.mp4"
        command = [
            ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x148A9C:s=1280x720:r=24:d=15",
        ]
        if native_audio:
            command.extend(
                (
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=660:sample_rate=48000:duration=15",
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:a",
                    "aac",
                    "-shortest",
                )
            )
        else:
            command.append("-an")
        command.extend(("-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-f", "mp4"))
    elif media_type == "audio":
        path = fixture_dir / "bgm-30s.mp3"
        command = [
            ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=30",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            "-f",
            "mp3",
        ]
    else:
        raise MockMediaFixtureError(f"Unsupported Mock media fixture type: {media_type}.")
    if path.is_file() and path.stat().st_size > 0:
        return path.read_bytes()

    staging_path = path.with_name(f".{path.name}.{uuid4().hex}.part")
    try:
        completed = subprocess.run(
            [*command, staging_path.as_posix()],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        staging_path.unlink(missing_ok=True)
        raise MockMediaFixtureError(
            f"Unable to create deterministic {media_type} fixture."
        ) from error
    if completed.returncode != 0 or not staging_path.is_file():
        staging_path.unlink(missing_ok=True)
        detail = completed.stderr.strip()[:500]
        raise MockMediaFixtureError(
            f"Unable to create deterministic {media_type} fixture: {detail}"
        )
    staging_path.replace(path)
    return path.read_bytes()
