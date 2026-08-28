"""Deterministic, local-only media fixtures used by mock execution paths."""

from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path


class MockMediaFixtureError(RuntimeError):
    """Raised when a deterministic mock asset cannot be produced."""


# A valid 1x1 transparent PNG; keeping this inline avoids another runtime asset.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def deterministic_mock_media_bytes(
    media_type: str,
    *,
    data_dir: Path,
    ffmpeg_path: str,
    native_audio: bool = False,
) -> bytes:
    """Return a small valid deterministic image, audio, or video fixture."""

    kind = media_type.strip().lower()
    if kind == "image":
        return _PNG_1X1
    if kind not in {"audio", "video"}:
        raise MockMediaFixtureError(f"unsupported mock media type: {media_type!r}")

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=data_dir) as temporary:
            output = Path(temporary) / ("fixture.mp4" if kind == "video" else "fixture.mp3")
            command = [ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y"]
            if kind == "video":
                command += ["-f", "lavfi", "-i", "color=c=black:s=16x16:r=1", "-t", "1"]
                if native_audio:
                    command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest"]
                command += ["-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]
            else:
                command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(output)]
            subprocess.run(command, check=True, capture_output=True)
            return output.read_bytes()
    except (OSError, subprocess.CalledProcessError) as error:
        raise MockMediaFixtureError("ffmpeg could not create mock media") from error
