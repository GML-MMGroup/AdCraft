"""SceneScript consistency gate (the Dramagic-style pre-render check).

Dramagic's defining feature is that a崩坏 frame never reaches the cut: the
pipeline verifies identity BEFORE generating, not after. This service is the
AdCraft equivalent for the 3D previs path — a queryable report of the ways a
SceneScript can quietly lose consistency:

- ``character_unbound`` — a character with no ``character_asset_id`` in a
  multi-shot scene. Previs renders characters as colored primitives, so a
  character that exists only as a color has no identity contract: the next
  generation step (video model, later scene) has nothing to keep it the same
  person. Warning, not error — binding is advice the author can decline.
- ``character_color_collision`` — two characters sharing an appearance color.
  In a low-fidelity scene color IS the identity channel; two same-colored
  characters are indistinguishable to a reviewer AND to the reference mapping
  a downstream video node builds.
- ``camera_unused`` — a camera no shot references: dead weight that usually
  means an abandoned take.
- ``shot_coverage_gap`` — the shots do not cover the full timeline, so part
  of the previs renders as nothing.
- ``scene_empty`` — nothing to look at.
- ``held_item_hand_conflict`` / ``held_item_authored_position_far`` — a held
  item (``SceneProp.held_by``) cannot hold its declaration: two props claim
  the same character+hand, or the authored position is a stale rest position
  the follow will move. See ``held_items.py``.

Issues carry stable codes (the UI localizes), a remedy (what to do about
it), and a subject (which element). They are WARNINGS by design: the report
is published onto the node's structured content so a reviewer can ask for it,
and the pre-render surface can gate on it — but nothing that used to render
stops rendering.

Extending the gate: add a check function and a code; the report shape is the
contract, so consumers need no change.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.held_items import check_held_items


SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class SceneConsistencyIssue:
    """One consistency finding about a SceneScript."""

    code: str
    severity: str
    subject: str
    message: str
    remedy: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "subject": self.subject,
            "message": self.message,
            "remedy": self.remedy,
        }


@dataclass(frozen=True)
class SceneConsistencyReport:
    """The full report for one SceneScript."""

    issues: tuple[SceneConsistencyIssue, ...] = ()

    @property
    def errors(self) -> tuple[SceneConsistencyIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == SEVERITY_ERROR)

    @property
    def warnings(self) -> tuple[SceneConsistencyIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == SEVERITY_WARNING)

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def check_scene_script_consistency(scene_script: SceneScriptRoot) -> SceneConsistencyReport:
    """Run every consistency check against a validated SceneScript."""

    issues: list[SceneConsistencyIssue] = []
    multi_shot = len(scene_script.shots) > 1

    # 1. Unbound characters in multi-shot scenes (the Dramagic core check).
    if multi_shot:
        for character in scene_script.characters:
            if not character.character_asset_id:
                issues.append(
                    SceneConsistencyIssue(
                        code="character_unbound",
                        severity=SEVERITY_WARNING,
                        subject=character.id,
                        message=(
                            f"Character '{character.id}' has no bound character asset in a "
                            f"{len(scene_script.shots)}-shot scene."
                        ),
                        remedy=(
                            "Bind a character asset (character_asset_id) so later shots and "
                            "the video model keep the same identity."
                        ),
                    )
                )

    # 2. Color collisions: color is the identity channel in low-fidelity.
    by_color: dict[str, list[str]] = {}
    for character in scene_script.characters:
        color = (character.appearance.color or "").strip().lower()
        if color:
            by_color.setdefault(color, []).append(character.id)
    for color, ids in sorted(by_color.items()):
        if len(ids) > 1:
            issues.append(
                SceneConsistencyIssue(
                    code="character_color_collision",
                    severity=SEVERITY_WARNING,
                    subject=",".join(sorted(ids)),
                    message=(
                        f"Characters {sorted(ids)} share appearance color {color}; the "
                        "low-fidelity preview cannot tell them apart."
                    ),
                    remedy="Give each character a distinct appearance color.",
                )
            )

    # 3. Cameras no shot references.
    used_cameras = {shot.camera for shot in scene_script.shots}
    for camera in scene_script.cameras:
        if camera.id not in used_cameras:
            issues.append(
                SceneConsistencyIssue(
                    code="camera_unused",
                    severity=SEVERITY_WARNING,
                    subject=camera.id,
                    message=f"Camera '{camera.id}' is not referenced by any shot.",
                    remedy="Reference it from a shot or remove it.",
                )
            )

    # 4. Shot coverage gaps.
    total_frames = scene_script.total_frames
    covered: list[tuple[int, int]] = sorted(
        (shot.start_frame, shot.end_frame) for shot in scene_script.shots
    )
    cursor = 0
    gap_ranges: list[tuple[int, int]] = []
    for start, end in covered:
        if start > cursor:
            gap_ranges.append((cursor, start - 1))
        cursor = max(cursor, end + 1)
    if cursor <= total_frames - 1:
        gap_ranges.append((cursor, total_frames - 1))
    for start, end in gap_ranges:
        issues.append(
            SceneConsistencyIssue(
                code="shot_coverage_gap",
                severity=SEVERITY_WARNING,
                subject=f"frames {start}-{end}",
                message=f"No shot covers frames {start}-{end} of {total_frames}.",
                remedy="Extend a shot's range or add a shot for the gap.",
            )
        )

    # 5. Empty scenes.
    if not scene_script.characters and not scene_script.props and not scene_script.environment:
        issues.append(
            SceneConsistencyIssue(
                code="scene_empty",
                severity=SEVERITY_WARNING,
                subject="scene",
                message="The scene has no characters, props, or environment objects.",
                remedy="Add at least one object before rendering a previs.",
            )
        )

    # 6. Held items (Continuity State's prop dimension, V0.2 §5): the
    #    declaration checks live in held_items.py; the gate only aggregates
    #    (that module cannot import this one back — it would be a cycle).
    for finding in check_held_items(scene_script):
        issues.append(
            SceneConsistencyIssue(
                code=finding.code,
                severity=SEVERITY_WARNING,
                subject=finding.subject,
                message=finding.message,
                remedy=finding.remedy,
            )
        )

    return SceneConsistencyReport(issues=tuple(issues))
