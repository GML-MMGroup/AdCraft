"""Keyframe extractor for 3D previs video-model guidance.

Extracts exactly 5 keyframes per shot at 0%, 25%, 50%, 75%, 100% of the
shot duration. Used as fallback reference for video models that don't support
reference video input (ADR 0005 §4a).
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas.scene_script import SceneScriptRoot, SceneShot


_FRAME_NAME_RE = re.compile(r"^frame_(\d+)\.png$")


def rendered_frame_files(frames_dir: str | Path) -> dict[int, Path]:
    """Map 0-indexed SceneScript frame number -> rendered PNG, in one pass.

    Reading the whole directory once matters when the caller wants the first
    frame of a full animation: doing it per candidate frame re-globs a
    240-file directory up to 240 times.
    """
    found: dict[int, Path] = {}
    for path in Path(frames_dir).glob("frame_*.png"):
        match = _FRAME_NAME_RE.match(path.name)
        if match:
            found[int(match.group(1)) - 1] = path
    return found


def find_frame_file(frames_dir: str | Path, frame_num: int) -> Path | None:
    """Locate the rendered PNG for a 0-indexed SceneScript frame number.

    Blender output is 1-indexed and not zero-padded, so enumerate the
    directory instead of matching a fixed-width pattern.
    """
    for path in Path(frames_dir).glob("frame_*.png"):
        match = _FRAME_NAME_RE.match(path.name)
        if match and int(match.group(1)) == frame_num + 1:
            return path
    return None


@dataclass
class ShotKeyframes:
    """5 keyframes for one shot."""

    shot_id: str
    frames: list[int] = field(default_factory=list)  # absolute frame numbers
    files: list[str] = field(default_factory=list)  # copied file paths


def _shot_keyframe_frames(shot: SceneShot) -> list[int]:
    """Return 5 absolute frame numbers at 0/25/50/75/100% of shot range.

    ``end_frame`` is exclusive — a shot spanning 0..30 covers frames 0-29,
    which is exactly the 30 frames Blender renders for a 1s/30fps scene. The
    100% sample must therefore land on ``end_frame - 1``, the last frame that
    actually exists; sampling ``end_frame`` yields a file that was never
    written and silently drops the shot to 4 keyframes.
    """
    start = shot.start_frame
    last = shot.end_frame - 1
    duration = last - start
    if duration <= 0:
        return [start]
    percentages = [0.0, 0.25, 0.50, 0.75, 1.0]
    frames = []
    for pct in percentages:
        frame = int(round(start + duration * pct))
        frame = max(start, min(last, frame))
        if frame not in frames:
            frames.append(frame)
    return frames


def extract_keyframes(
    scene_script: SceneScriptRoot,
    frames_dir: str,
    output_dir: str,
) -> list[ShotKeyframes]:
    """Extract 5 keyframes per shot from rendered PNG frames.

    Args:
        scene_script: Validated SceneScript root (for shot ranges).
        frames_dir: Directory containing rendered frame_XXXX.png files.
        output_dir: Directory to copy keyframe images.

    Returns:
        List of ShotKeyframes, one per shot.
    """
    frames_path = Path(frames_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    results: list[ShotKeyframes] = []

    for shot in scene_script.shots:
        shot_kf = ShotKeyframes(shot_id=shot.id)
        frames = _shot_keyframe_frames(shot)
        shot_kf.frames = frames

        for i, frame_num in enumerate(frames):
            # Blender outputs frame_0001.png for frame 0 (1-indexed output)
            # Our SceneScript uses 0-indexed frames, so Blender frame = frame_num + 1
            src = find_frame_file(frames_path, frame_num)

            if src is not None:
                dst_name = f"{shot.id}_kf{i:02d}_f{frame_num:04d}.png"
                dst = output_path / dst_name
                shutil.copy2(src, dst)
                shot_kf.files.append(str(dst))

        results.append(shot_kf)

    return results


def keyframe_manifest(scene_script: SceneScriptRoot) -> dict:
    """Generate a manifest of keyframe positions for prompt generation.

    Returns a dict mapping shot_id -> list of {frame, percentage} entries.
    """
    manifest: dict[str, list[dict]] = {}
    for shot in scene_script.shots:
        frames = _shot_keyframe_frames(shot)
        last = shot.end_frame - 1
        duration = last - shot.start_frame
        manifest[shot.id] = [
            {
                "frame": f,
                "percentage": round((f - shot.start_frame) / duration * 100, 1) if duration > 0 else 0,
            }
            for f in frames
        ]
    return manifest
