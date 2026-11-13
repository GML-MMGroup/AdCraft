"""Lossless adjacent-beat grouping before a new outline becomes authoritative."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.schemas.agent_canvas_storyboard_sequences import (
    StoryboardOutlineSegmentDraftV2,
    StoryboardSequenceAuthorityPlanV2,
    StoryboardSequenceOutlineDraftV2,
    StoryboardSequenceWindowV2,
)
from app.services.agent_canvas_storyboard_sequence_windows import StoryboardSequenceWindowPlanner

COALESCING_RULE = "storyboard_adjacent_beat_coalescing_v1"


def coalesce_storyboard_beats(
    context: dict[str, Any], value: dict[str, Any]
) -> dict[str, Any] | None:
    """Remove only boundaries; never split, retime, truncate, or reinterpret a beat.

    Only narrative mode delegates generation count. Explicit counts and fixed
    windows must use the regular validation/repair path. Preserve the maximum
    number of original boundaries compatible with duration and text budgets.
    """
    try:
        authority = StoryboardSequenceAuthorityPlanV2.model_validate(context)
        outline = StoryboardSequenceOutlineDraftV2.model_validate(value)
    except (ValidationError, ValueError):
        return None
    if (
        authority.timing_mode != "narrative"
        or outline.aspect_ratio != authority.aspect_ratio
        or outline.total_duration_seconds != authority.total_duration_seconds
    ):
        return None
    beats = outline.segments
    cursor = 0.0
    for order, beat in enumerate(beats, 1):
        if beat.order != order or beat.start_seconds != cursor:
            return None
        cursor = beat.end_seconds
    if cursor != authority.total_duration_seconds:
        return None
    try:
        StoryboardSequenceWindowPlanner.accept_authored_windows(authority, _windows(beats))
        return None
    except ValueError:
        pass

    # Dynamic programming keeps all internal events and chooses fewest merges.
    best: dict[int, tuple[StoryboardOutlineSegmentDraftV2, ...]] = {len(beats): ()}
    for start in range(len(beats) - 1, -1, -1):
        for stop in range(start + 1, len(beats) + 1):
            duration = beats[stop - 1].end_seconds - beats[start].start_seconds
            if duration > authority.max_sequence_duration_seconds:
                break
            if duration < 4 or not duration.is_integer() or stop not in best:
                continue
            try:
                segment = _merge(beats[start:stop])
            except ValidationError:
                continue
            candidate = (segment, *best[stop])
            if start not in best or len(candidate) > len(best[start]):
                best[start] = candidate
    if 0 not in best:
        return None
    merged = tuple(segment.model_copy(update={"order": i}) for i, segment in enumerate(best[0], 1))
    windows = ", ".join(f"{s.start_seconds:g}-{s.end_seconds:g}s" for s in merged)
    try:
        repaired = StoryboardSequenceOutlineDraftV2.model_validate(
            {
                **outline.model_dump(mode="json"),
                "narrative_outline": (
                    f"Generation windows: {windows}. Original segment labels below identify story beats, "
                    "not separate generation nodes. Internal timecodes remain on the original story timeline.\n\n"
                    + outline.narrative_outline
                ),
                "segments": merged,
            }
        )
        StoryboardSequenceWindowPlanner.accept_authored_windows(authority, _windows(merged))
    except (ValidationError, ValueError):
        return None
    return repaired.model_dump(mode="json")


def _windows(
    beats: tuple[StoryboardOutlineSegmentDraftV2, ...],
) -> tuple[StoryboardSequenceWindowV2, ...]:
    return tuple(
        StoryboardSequenceWindowV2(
            order=b.order, start_seconds=b.start_seconds, end_seconds=b.end_seconds
        )
        for b in beats
    )


def _merge(beats: tuple[StoryboardOutlineSegmentDraftV2, ...]) -> StoryboardOutlineSegmentDraftV2:
    if len(beats) == 1:
        return beats[0]
    blocks = []
    for beat in beats:
        blocks.append(
            f"Original beat {beat.order} [{beat.start_seconds:g}-{beat.end_seconds:g}s]:\n"
            f"{beat.narrative_goal}\nOpening state: {beat.start_state}\nClosing state: {beat.end_state}"
            + (
                f"\nIncoming continuity: {beat.continuity_from_previous}"
                if beat.continuity_from_previous
                else ""
            )
        )
    return StoryboardOutlineSegmentDraftV2(
        order=beats[0].order,
        start_seconds=beats[0].start_seconds,
        end_seconds=beats[-1].end_seconds,
        narrative_goal="\n\n".join(blocks),
        start_state=beats[0].start_state,
        end_state=beats[-1].end_state,
        continuity_from_previous=beats[0].continuity_from_previous,
    )
