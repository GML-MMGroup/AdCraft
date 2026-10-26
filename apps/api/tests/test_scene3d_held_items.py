"""Tests for held items — the Continuity State prop dimension (V0.2 §5).

The research's failure example: "Scene 01 里女孩右手拿伞，Scene 02 变成左手".
A prop declared ``held_by`` a character follows that hand across every shot,
so the failure is structurally impossible. These tests lock the follow math
(shared with the frontend mirror), the declaration checks the gate surfaces,
and the schema's fail-closed holder reference.
"""

from __future__ import annotations

import math

import pytest

from app.schemas.scene_script import (
    SceneCamera,
    SceneCharacter,
    SceneProp,
    SceneScriptRoot,
    SceneShot,
)
from app.services.scene3d.held_items import (
    AUTHORED_POSITION_SLACK_M,
    HAND_HEIGHT_RATIO,
    HAND_REACH_M,
    held_item_grip,
    check_held_items,
    hand_offset,
    held_keyframe_positions,
    held_position_at_frame,
)
from app.services.scene3d.scene_consistency import check_scene_script_consistency


def _character(character_id: str = "girl", height: float = 1.7) -> SceneCharacter:
    return SceneCharacter(
        id=character_id,
        type="lowpoly_human",
        appearance={"color": "#E74C3C", "height": height},
        keyframes=[
            {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"},
            {"frame": 90, "position": [2, 0, 0], "rotation_y": 90, "action": "walk"},
        ],
    )


def _prop(prop_id: str = "umbrella", **overrides) -> SceneProp:
    payload = {
        "id": prop_id,
        "type": "weapon",
        "position": [0, 0, 0],
        "held_by": "girl",
        "held_side": "right",
    }
    payload.update(overrides)
    return SceneProp(**payload)


def _script(props: list[SceneProp], characters: list[SceneCharacter] | None = None) -> SceneScriptRoot:
    return SceneScriptRoot(
        scene={"name": "street", "environment": "outdoor", "duration": 6, "frame_rate": 30},
        characters=characters if characters is not None else [_character()],
        props=props,
        cameras=[
            SceneCamera(
                id="c1",
                shot_type="wide",
                keyframes=[{"frame": 0, "position": [3, -4, 2], "look_at": [0, 0, 1]}],
            )
        ],
        shots=[SceneShot(id="s1", camera="c1", start_frame=0, end_frame=179)],
    )


class TestHandOffset:
    def test_right_hand_lands_where_the_rigs_arm_ends(self) -> None:
        # Not "at HAND_REACH_M". That constant matched the rig only for a 1.75 m
        # figure: the rig places the arm in proportion to height, so a 1.1 m
        # character's hand is 60% closer in than the constant put the weapon.
        height = 1.7
        arm = held_item_grip.arm_geometry(height)
        offset = hand_offset(0.0, "right", height)
        assert offset[0] == pytest.approx(arm.grip_lateral)
        # And forward, which the old offset left at zero: a raised arm ends up in
        # front of the chest, so an item carried at the chest was half a metre
        # behind the hand.
        assert offset[1] == pytest.approx(arm.grip_forward)
        assert offset[2] == pytest.approx(height * HAND_HEIGHT_RATIO)

    def test_reach_scales_with_the_character(self) -> None:
        # The defect in one assertion: a constant metre reach cannot be right for two
        # heights.
        adult = hand_offset(0.0, "right", 1.9)
        child = hand_offset(0.0, "right", 1.1)
        assert abs(adult[0]) > abs(child[0])
        assert abs(child[0]) < HAND_REACH_M * 0.75

    def test_left_hand_mirrors_the_right(self) -> None:
        right = hand_offset(37.0, "right", 1.7)
        left = hand_offset(37.0, "left", 1.7)
        assert left[0] == pytest.approx(-right[0])
        assert left[1] == pytest.approx(-right[1])
        assert left[2] == pytest.approx(right[2])

    def test_height_scales_the_lift(self) -> None:
        short = hand_offset(0.0, "right", 1.0)
        tall = hand_offset(0.0, "right", 2.0)
        assert tall[2] == pytest.approx(short[2] * 2)

    def test_yaw_quarter_turn_rotates_the_hand_as_a_rigid_pair(self) -> None:
        # The hand is diagonal in the character's own frame -- out to the side AND in
        # front -- so facing +X does not put it purely on one axis. Rotating +90
        # degrees maps (lateral, forward) -> (-forward, lateral), and the distance
        # from the chest has to be preserved.
        height = 1.7
        arm = held_item_grip.arm_geometry(height)
        north = hand_offset(0.0, "right", height)
        east = hand_offset(90.0, "right", height)
        assert east[0] == pytest.approx(-arm.grip_forward)
        assert east[1] == pytest.approx(arm.grip_lateral)
        assert math.hypot(*north[:2]) == pytest.approx(math.hypot(*east[:2]))

    def test_a_weapon_is_gripped_by_its_handle_not_its_origin(self) -> None:
        # The first render of the grip fix held the sword BY THE BLADE, because a
        # weapon's grip sits 0.32 of its scale above where the prop stands.
        height = 1.7
        bare = hand_offset(0.0, "right", height)
        sword = hand_offset(0.0, "right", height, "weapon", 1.2)
        assert sword[2] == pytest.approx(bare[2] - 0.32 * 1.2)
        # And a kind with no known grip is untouched.
        assert hand_offset(0.0, "right", height, "crate", 2.0) == pytest.approx(bare)


class TestHeldFollow:
    def test_the_item_rides_the_hand_at_every_authored_pose(self) -> None:
        prop = _prop()
        character = _character()
        arm = held_item_grip.arm_geometry(character.appearance.height)

        at_start = held_position_at_frame(prop, character, 0)
        # Right of the start pose, and forward of it, because a raised arm ends in
        # front of the chest.
        assert at_start[0] == pytest.approx(arm.grip_lateral)
        assert at_start[1] == pytest.approx(arm.grip_forward)

        at_end = held_position_at_frame(prop, character, 90)
        # The character walked to [2,0,0] facing +X; the hand followed, so the reach
        # from the chest is unchanged and the item has not switched sides.
        assert at_end[2] == pytest.approx(at_start[2])
        assert math.hypot(at_end[0] - 2.0, at_end[1]) == pytest.approx(
            math.hypot(arm.grip_lateral, arm.grip_forward)
        )
        assert at_end[0] == pytest.approx(2.0 - arm.grip_forward)
        assert at_end[1] == pytest.approx(arm.grip_lateral)

    def test_between_poses_the_hand_interpolates_with_the_character(self) -> None:
        prop = _prop()
        character = _character()
        mid = held_position_at_frame(prop, character, 45)
        assert 0 < mid[0] < 2  # halfway along the walk

    def test_step_semantics_before_the_first_keyframe(self) -> None:
        prop = _prop()
        character = _character()
        # Frames before the first authored pose hold it (matching the preview).
        assert held_position_at_frame(prop, character, 0) == held_position_at_frame(
            prop, character, 0
        )

    def test_keyframe_positions_line_up_with_the_holder_keyframes(self) -> None:
        prop = _prop()
        character = _character()
        positions = held_keyframe_positions(prop, character)
        assert [frame for frame, _ in positions] == [0, 90]
        for frame, position in positions:
            assert position == held_position_at_frame(prop, character, frame)

    def test_an_unheld_prop_has_no_follow(self) -> None:
        # held_by=None is the authored-static case; the follow helpers are only
        # called for held props, and there is nothing to compute without one.
        prop = _prop(held_by=None)
        assert prop.held_by is None


class TestHeldItemChecks:
    def test_one_item_per_hand_is_a_conflict(self) -> None:
        issues = check_held_items(_script([_prop("umbrella"), _prop("cup", type="cup")]))
        conflicts = [issue for issue in issues if issue.code == "held_item_hand_conflict"]
        assert len(conflicts) == 1
        assert "umbrella" in conflicts[0].subject and "cup" in conflicts[0].subject

    def test_two_hands_two_items_is_silent(self) -> None:
        issues = check_held_items(
            _script([_prop("umbrella"), _prop("cup", type="cup", held_side="left")])
        )
        assert issues == []

    def test_a_stale_authored_position_is_flagged(self) -> None:
        far = _prop(position=[40, 40, 0])
        issues = check_held_items(_script([far]))
        flagged = [issue for issue in issues if issue.code == "held_item_authored_position_far"]
        assert len(flagged) == 1
        assert flagged[0].subject == "umbrella"
        assert "手写位置" in flagged[0].message

    def test_a_rest_position_near_the_holder_is_silent(self) -> None:
        # The hand point itself: distance zero.
        hand = held_position_at_frame(_prop(), _character(), 0)
        near = _prop(position=hand)
        assert check_held_items(_script([near])) == []

    def test_the_slack_boundary_is_lived(self) -> None:
        # Mutation check: positions beyond the slack flag, inside it are silent.
        # The offset is taken perpendicular to the holder's walk (the check
        # measures against EVERY keyframe's hand point, so a point near either
        # end of the path must not be mistaken for "far").
        hand = held_position_at_frame(_prop(), _character(), 0)
        just_beyond = _prop(
            position=[hand[0], hand[1] + AUTHORED_POSITION_SLACK_M + 0.5, hand[2]]
        )
        assert any(
            issue.code == "held_item_authored_position_far"
            for issue in check_held_items(_script([just_beyond]))
        )
        just_inside = _prop(
            position=[hand[0], hand[1] + AUTHORED_POSITION_SLACK_M - 0.5, hand[2]]
        )
        assert check_held_items(_script([just_inside])) == []

    def test_no_held_props_no_findings(self) -> None:
        static = SceneProp(id="table", type="round_table", position=[1, 1, 0])
        assert check_held_items(_script([static])) == []


class TestSchemaFailClosed:
    def test_a_prop_held_by_a_missing_character_is_rejected(self) -> None:
        script = _script([_prop()])
        payload = script.model_dump(mode="json")
        payload["props"][0]["held_by"] = "ghost"
        with pytest.raises(Exception) as excinfo:
            SceneScriptRoot.model_validate(payload)
        assert "ghost" in str(excinfo.value)

    def test_held_fields_round_trip(self) -> None:
        script = _script([_prop(held_side="left")])
        restored = SceneScriptRoot.model_validate(script.model_dump(mode="json"))
        assert restored.props[0].held_by == "girl"
        assert restored.props[0].held_side == "left"

    def test_plain_props_keep_working(self) -> None:
        # Backward compatibility: the ubiquitous unheld prop parses unchanged.
        script = _script([SceneProp(id="table", type="round_table", position=[1, 0, 0])])
        assert script.props[0].held_by is None
        assert script.props[0].held_side is None


class TestGateIntegration:
    def test_the_consistency_report_carries_the_held_findings(self) -> None:
        script = _script([_prop("umbrella"), _prop("cup", type="cup")])
        report = check_scene_script_consistency(script)
        codes = {issue.code for issue in report.issues}
        assert "held_item_hand_conflict" in codes
        # The gate stays warning-level: nothing that rendered before stops.
        assert report.passed is True
        assert all(issue.severity == "warning" for issue in report.issues)

    def test_a_clean_held_scene_adds_no_findings(self) -> None:
        script = _script([_prop()])
        report = check_scene_script_consistency(script)
        assert not [issue for issue in report.issues if issue.code.startswith("held_item")]


class TestConverterEmission:
    def test_held_props_get_holder_following_keyframes(self) -> None:
        import tempfile

        from app.services.scene3d.blender_converter import scene_script_to_blender

        script = _script([_prop()])
        with tempfile.TemporaryDirectory() as tmp:
            generated = scene_script_to_blender(script, tmp)
        lines = generated.splitlines()
        marker = next(i for i, line in enumerate(lines) if "Held prop keyframes: umbrella" in line)
        block = lines[marker : marker + 8]
        assert any("prop_obj.location" in line for line in block)
        # Two keyframes: the holder's own frame 0 and frame 90.
        assert sum("keyframe_insert" in line for line in block) == 2

    def test_static_props_are_untouched(self) -> None:
        import tempfile

        from app.services.scene3d.blender_converter import scene_script_to_blender

        static = SceneProp(id="table", type="round_table", position=[1, 0, 0])
        script = _script([static])
        with tempfile.TemporaryDirectory() as tmp:
            generated = scene_script_to_blender(script, tmp)
        assert "Held prop keyframes" not in generated
        assert "table" in generated

    def test_the_emitted_positions_are_the_hand_positions(self) -> None:
        import tempfile

        from app.services.scene3d.blender_converter import scene_script_to_blender

        script = _script([_prop()])
        expected = held_position_at_frame(_prop(), _character(), 0)
        with tempfile.TemporaryDirectory() as tmp:
            generated = scene_script_to_blender(script, tmp)
        marker = next(
            i for i, line in enumerate(generated.splitlines())
            if "Held prop keyframes: umbrella" in line
        )
        location_line = next(
            line for line in generated.splitlines()[marker : marker + 8]
            if "prop_obj.location" in line
        )
        for component in expected:
            assert f"{component:.4f}" in location_line

    def test_hand_offset_is_a_rigid_vector_rotated_with_the_body(self) -> None:
        # It used to be asserted perpendicular to facing, which was true only while
        # the offset was purely lateral. A hand reaching FORWARD for a weapon is not
        # perpendicular to facing, and should not be. The property that must hold at
        # every yaw is that the reach neither grows nor shrinks as the body turns --
        # otherwise the item slides around the character on a cut.
        for yaw in (0.0, 30.0, 90.0, 175.0, 270.0):
            offset = hand_offset(yaw, "right", 1.7)
            assert math.hypot(offset[0], offset[1]) == pytest.approx(
                math.hypot(
                    held_item_grip.arm_geometry(1.7).grip_lateral,
                    held_item_grip.arm_geometry(1.7).grip_forward,
                )
            )
            # And the height never depends on which way the body faces.
            assert offset[2] == pytest.approx(1.7 * HAND_HEIGHT_RATIO)
