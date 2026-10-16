"""Geometric control pass collection for previs video-model guidance (ADR 0005 §4).

Collects depth / normal / motion-vector (flow) pass images rendered by
Blender (see ``blender_converter._control_pass_lines``) into a per-shot
asset structure that can be delivered to a video provider as control
references. Follows the repo's queryable-degradation discipline
(engineering standard §4): a pass that is requested but absent yields a
queryable degradation marker per shot, never a silent omission.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas.scene_script import SceneScriptRoot

from app.services.scene3d.keyframes import _shot_keyframe_frames

_CONTROL_PASS_NAMES = ("depth", "normal", "flow")

# Blender compositor OutputFile nodes write ``<base_path> + frame`` where
# base_path ends with the pass name prefix (e.g. ``depth_``). Whether the
# result carries a ``.png`` extension depends on ``use_file_extensions`` and
# the pass's configured file format, so match with or without an extension.
_PASS_NAME_RE = re.compile(r"^(\w+)_(\d+)(?:\.png)?$")


@dataclass
class ShotControlPasses:
    """Per-shot control-pass image files, aligned with the shot's keyframes."""

    shot_id: str
    frames: list[int] = field(default_factory=list)  # absolute SceneScript frames
    depth_files: list[str] = field(default_factory=list)
    normal_files: list[str] = field(default_factory=list)
    flow_files: list[str] = field(default_factory=list)

    @property
    def available_passes(self) -> tuple[str, ...]:
        """Which of depth/normal/flow actually produced files for this shot."""
        available = []
        if self.depth_files:
            available.append("depth")
        if self.normal_files:
            available.append("normal")
        if self.flow_files:
            available.append("flow")
        return tuple(available)


@dataclass
class ControlPassResult:
    """Shot-aligned control-pass bundle for one render job."""

    shots: list[ShotControlPasses] = field(default_factory=list)

    @property
    def degradation_markers(self) -> dict[str, list[str]]:
        """Per-shot queryable degradation markers (engineering standard §4).

        Lists the requested-but-unavailable passes per shot; empty dict
        means every requested pass is present.
        """
        markers: dict[str, list[str]] = {}
        for shot in self.shots:
            missing = [
                name
                for name, files in (
                    ("depth", shot.depth_files),
                    ("normal", shot.normal_files),
                    ("flow", shot.flow_files),
                )
                if not files
            ]
            if missing:
                markers[shot.shot_id] = missing
        return markers

    @property
    def completeness(self) -> str:
        """Queryable control-signal completeness for the whole job.

        - "full": every shot has depth + normal + flow
        - "partial": some shots missing at least one pass
        - "none": no shot has any pass
        """
        if not self.shots:
            return "none"
        full_count = sum(
            1 for shot in self.shots if set(_CONTROL_PASS_NAMES) <= set(shot.available_passes)
        )
        if full_count == len(self.shots):
            return "full"
        has_any = any(shot.available_passes for shot in self.shots)
        return "partial" if has_any else "none"


def _find_pass_file(pass_dir: Path, frame_num: int) -> Path | None:
    """Locate the pass file for a 0-indexed SceneScript frame.

    ``blender_converter._control_pass_lines`` writes ``depth_<N>.png`` where
    ``N`` is the 0-based SceneScript frame (unlike the color pass, which is
    1-indexed because Blender numbers its animation frames from
    ``frame_start = 1``). Enumerates ``.png`` and extensionless files, since
    the extension depends on the writer's file format.
    """
    candidates = sorted(pass_dir.iterdir()) if pass_dir.is_dir() else []
    for path in candidates:
        if not path.is_file():
            continue
        if path.suffix in (".png", ""):
            match = _PASS_NAME_RE.match(path.name)
            if match and int(match.group(2)) == frame_num:
                return path
    return None


def collect_control_passes(
    scene_script: SceneScriptRoot,
    frames_dir: str,
) -> ControlPassResult:
    """Collect per-shot control-pass files from a Blender render directory.

    Args:
        scene_script: Validated SceneScript root (shot ranges drive sampling).
        frames_dir: Directory that held the color-pass ``frame_*.png`` output;
            control passes are expected in sibling subdirectories
            ``control_depth`` / ``control_normal`` / ``control_flow``
            (layout written by ``blender_converter._control_pass_lines``).

    Returns:
        ControlPassResult with per-shot file lists and a queryable
        completeness marker; missing passes surface in
        ``degradation_markers`` (never silent).
    """
    base = Path(frames_dir)
    depth_dir = base / "control_depth"
    normal_dir = base / "control_normal"
    flow_dir = base / "control_flow"

    result = ControlPassResult()
    for shot in scene_script.shots:
        shot_passes = ShotControlPasses(shot_id=shot.id)
        frames = _shot_keyframe_frames(shot)
        shot_passes.frames = frames

        for frame_num in frames:
            for file_list, pass_dir, prefix in (
                (shot_passes.depth_files, depth_dir, "depth"),
                (shot_passes.normal_files, normal_dir, "normal"),
                (shot_passes.flow_files, flow_dir, "flow"),
            ):
                src = _find_pass_file(pass_dir, frame_num) if pass_dir.is_dir() else None
                if src is not None:
                    file_list.append(src.as_posix())

        result.shots.append(shot_passes)
    return result


def control_passes_for_shot(
    result: ControlPassResult, shot_id: str
) -> ShotControlPasses | None:
    """Look up one shot's control passes from a collection result."""
    for shot in result.shots:
        if shot.shot_id == shot_id:
            return shot
    return None
