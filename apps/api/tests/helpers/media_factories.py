from pathlib import Path
import subprocess


def media_extension(media_type: str) -> str:
    return {
        "audio": ".mp3",
        "image": ".png",
        "video": ".mp4",
    }.get(media_type, ".bin")


def write_dummy_media_file(
    data_dir: Path,
    relative_path: str | Path,
    *,
    content: bytes | None = None,
) -> Path:
    path = data_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if content is not None else b"test-media")
    return path


def write_playable_test_video(
    data_dir: Path,
    relative_path: str | Path,
) -> Path:
    """Create a minimal deterministic MP4 for the small real-FFmpeg acceptance path."""
    path = data_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=12:d=0.2",
            "-an",
            "-c:v",
            "mpeg4",
            "-pix_fmt",
            "yuv420p",
            path.as_posix(),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Unable to create test video: {completed.stderr}")
    return path


def write_corner_marked_test_video(
    data_dir: Path,
    relative_path: str | Path,
    *,
    color: str,
    width: int = 96,
    height: int = 64,
    fps: int = 12,
    duration_seconds: float = 0.4,
    include_audio: bool = True,
) -> Path:
    path = data_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = max(4, min(width, height) // 8)
    video_filter = ",".join(
        [
            f"drawbox=x=0:y=0:w={marker}:h={marker}:color=red:t=fill",
            f"drawbox=x=iw-{marker}:y=0:w={marker}:h={marker}:color=green:t=fill",
            f"drawbox=x=0:y=ih-{marker}:w={marker}:h={marker}:color=blue:t=fill",
            (f"drawbox=x=iw-{marker}:y=ih-{marker}:w={marker}:h={marker}:color=white:t=fill"),
        ]
    )
    args = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={width}x{height}:r={fps}:d={duration_seconds}",
    ]
    if include_audio:
        args.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:sample_rate=48000:duration={duration_seconds}",
            ]
        )
    args.extend(["-vf", video_filter, "-c:v", "mpeg4", "-pix_fmt", "yuv420p"])
    if include_audio:
        args.extend(["-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest"])
    else:
        args.append("-an")
    args.append(path.as_posix())
    completed = subprocess.run(args, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Unable to create corner-marked video: {completed.stderr}")
    return path


def write_test_tone(
    data_dir: Path,
    relative_path: str | Path,
    *,
    duration_seconds: float = 0.3,
    frequency_hz: int = 220,
) -> Path:
    path = data_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            (f"sine=frequency={frequency_hz}:sample_rate=48000:duration={duration_seconds}"),
            "-c:a",
            "pcm_s16le",
            path.as_posix(),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Unable to create test tone: {completed.stderr}")
    return path


def read_rgb_frame(
    path: Path,
    *,
    at_seconds: float,
    width: int,
    height: int,
) -> bytes:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-ss",
            f"{at_seconds:.3f}",
            "-i",
            path.as_posix(),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Unable to extract test frame: {completed.stderr.decode('utf-8', errors='replace')}"
        )
    expected_size = width * height * 3
    if len(completed.stdout) != expected_size:
        raise RuntimeError(
            f"Unexpected raw frame size: expected {expected_size}, got {len(completed.stdout)}"
        )
    return completed.stdout
