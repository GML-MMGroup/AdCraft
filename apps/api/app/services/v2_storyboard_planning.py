from __future__ import annotations

from math import ceil
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.workflow_v2_planning import V2ScriptPlan


V2_DEFAULT_STORYBOARD_SHOT_COUNT = 4
V2_DEFAULT_SHOT_CELL_COUNT = 4
V2_MAX_STORYBOARD_SHOT_COUNT = 12
V2_MAX_TOTAL_DURATION_SECONDS = 60
V2_MIN_SHOT_DURATION_SECONDS = 3
V2_MAX_SHOT_DURATION_SECONDS = 10
V2_TARGET_SHOT_DURATION_SECONDS = 8
V2StoryboardShotCountSource = Literal[
    "default",
    "inferred",
    "explicit",
    "explicit_request",
    "explicit_user_prompt",
]


class V2StoryboardPlanningResult(BaseModel):
    status: Literal["ready", "needs_clarification"]
    storyboard_config: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    suggested_actions: list[dict[str, Any]] = Field(default_factory=list)


def plan_storyboard_config(
    *,
    duration_seconds: int,
    requested_shot_count: int | None,
    requested_shot_count_source: V2StoryboardShotCountSource | None = None,
) -> V2StoryboardPlanningResult:
    if duration_seconds > V2_MAX_TOTAL_DURATION_SECONDS:
        return _duration_not_supported(duration_seconds)
    if requested_shot_count is None:
        shot_count = _default_shot_count(duration_seconds)
        return _ready_result(
            duration_seconds=duration_seconds,
            requested_shot_count=None,
            applied_shot_count=shot_count,
            shot_count_source="default",
        )
    if requested_shot_count < 1:
        return _shot_count_not_supported(duration_seconds, requested_shot_count)
    if requested_shot_count > V2_MAX_STORYBOARD_SHOT_COUNT:
        return _shot_count_not_supported(duration_seconds, requested_shot_count)
    if duration_seconds / requested_shot_count > V2_MAX_SHOT_DURATION_SECONDS:
        return _shot_duration_not_supported(duration_seconds, requested_shot_count)
    if duration_seconds / requested_shot_count < V2_MIN_SHOT_DURATION_SECONDS:
        return _shot_count_not_supported(duration_seconds, requested_shot_count)
    return _ready_result(
        duration_seconds=duration_seconds,
        requested_shot_count=(
            None if requested_shot_count_source == "default" else requested_shot_count
        ),
        applied_shot_count=requested_shot_count,
        shot_count_source=requested_shot_count_source or "explicit",
    )


def requested_shot_count_from_payload(
    *,
    prompt: str,
    metadata: dict[str, Any],
    requested_shot_count: int | None = None,
) -> int | None:
    if requested_shot_count is not None:
        return requested_shot_count
    for key in (
        "requested_shot_count",
        "storyboard_shot_count",
        "shot_count",
    ):
        value = metadata.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    nested = metadata.get("storyboard_config")
    if isinstance(nested, dict):
        value = nested.get("requested_shot_count")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return _shot_count_from_prompt(prompt)


def apply_storyboard_config_to_script_plan(
    script_plan: V2ScriptPlan,
    storyboard_config: dict[str, Any],
) -> V2ScriptPlan:
    shot_count = int(storyboard_config.get("applied_shot_count") or len(script_plan.shots))
    durations = [
        int(value)
        for value in storyboard_config.get("shot_durations_seconds", [])
        if isinstance(value, int)
    ]
    if shot_count <= 0 or not script_plan.shots:
        return script_plan
    if len(durations) != shot_count:
        durations = _shot_durations(int(script_plan.duration_seconds), shot_count)
    scene_ids = {scene.scene_id for scene in script_plan.scenes}
    fallback_scene_id = script_plan.scenes[0].scene_id if script_plan.scenes else "scene-1"
    normalized_shots = []
    for index in range(shot_count):
        source = script_plan.shots[min(index, len(script_plan.shots) - 1)]
        scene_id = source.scene_id if source.scene_id in scene_ids else fallback_scene_id
        normalized_shots.append(
            source.model_copy(
                update={
                    "shot_id": f"shot-{index + 1}",
                    "scene_id": scene_id,
                    "shot_index": index + 1,
                    "duration_seconds": durations[index],
                },
                deep=True,
            )
        )
    scenes = list(script_plan.scenes)
    if scenes:
        shots_by_scene: dict[str, list[Any]] = {}
        for shot in normalized_shots:
            shots_by_scene.setdefault(shot.scene_id, []).append(shot)
        scenes = [
            scene.model_copy(
                update={
                    "shot_ids": [shot.shot_id for shot in shots_by_scene[scene.scene_id]],
                    "duration_seconds": sum(
                        shot.duration_seconds for shot in shots_by_scene[scene.scene_id]
                    ),
                },
                deep=True,
            )
            if scene.scene_id in shots_by_scene
            else scene
            for scene in scenes
        ]
    return script_plan.model_copy(
        update={
            "shots": normalized_shots,
            "scenes": scenes,
            "duration_seconds": sum(durations),
        },
        deep=True,
    )


def _default_shot_count(duration_seconds: int) -> int:
    return max(1, ceil(duration_seconds / V2_MAX_SHOT_DURATION_SECONDS))


def _ready_result(
    *,
    duration_seconds: int,
    requested_shot_count: int | None,
    applied_shot_count: int,
    shot_count_source: V2StoryboardShotCountSource,
) -> V2StoryboardPlanningResult:
    return V2StoryboardPlanningResult(
        status="ready",
        storyboard_config={
            "requested_shot_count": requested_shot_count,
            "applied_shot_count": applied_shot_count,
            "shot_count_source": shot_count_source,
            "cell_count_per_shot": V2_DEFAULT_SHOT_CELL_COUNT,
            "min_shot_duration_seconds": V2_MIN_SHOT_DURATION_SECONDS,
            "max_shot_duration_seconds": V2_MAX_SHOT_DURATION_SECONDS,
            "max_total_duration_seconds": V2_MAX_TOTAL_DURATION_SECONDS,
            "duration_planning_mode": "short_segments",
            "target_shot_duration_seconds": V2_TARGET_SHOT_DURATION_SECONDS,
            "shot_durations_seconds": _shot_durations(duration_seconds, applied_shot_count),
            "warnings": [],
        },
    )


def _shot_durations(duration_seconds: int, shot_count: int) -> list[int]:
    base = duration_seconds // shot_count
    remainder = duration_seconds % shot_count
    return [base + (1 if index < remainder else 0) for index in range(shot_count)]


def _duration_not_supported(duration_seconds: int) -> V2StoryboardPlanningResult:
    return V2StoryboardPlanningResult(
        status="needs_clarification",
        error_code="video_duration_not_supported",
        message=(
            "Long-form video is not supported yet. Please use a total duration of "
            f"{V2_MAX_TOTAL_DURATION_SECONDS} seconds or less."
        ),
        details={
            "requested_duration_seconds": duration_seconds,
            "max_total_duration_seconds": V2_MAX_TOTAL_DURATION_SECONDS,
        },
        suggested_actions=[
            {
                "action": "reduce_duration",
                "duration_seconds": V2_MAX_TOTAL_DURATION_SECONDS,
                "label": f"Make it {V2_MAX_TOTAL_DURATION_SECONDS} seconds",
            }
        ],
    )


def _shot_duration_not_supported(
    duration_seconds: int,
    requested_shot_count: int,
) -> V2StoryboardPlanningResult:
    suggested_min = ceil(duration_seconds / V2_MAX_SHOT_DURATION_SECONDS)
    return V2StoryboardPlanningResult(
        status="needs_clarification",
        error_code="storyboard_shot_duration_not_supported",
        message=(
            "A single storyboard video is a short segment. With the current provider, "
            "each storyboard shot can be up to 10 seconds. Please use more shots or "
            "reduce the total duration."
        ),
        details={
            "requested_duration_seconds": duration_seconds,
            "requested_shot_count": requested_shot_count,
            "max_shot_duration_seconds": V2_MAX_SHOT_DURATION_SECONDS,
            "suggested_min_shot_count": suggested_min,
        },
        suggested_actions=[
            {
                "action": "use_suggested_shot_count",
                "shot_count": suggested_min,
                "label": f"Use {suggested_min} shots",
            },
            {
                "action": "reduce_duration",
                "duration_seconds": requested_shot_count * V2_MAX_SHOT_DURATION_SECONDS,
                "label": f"Make it {requested_shot_count * V2_MAX_SHOT_DURATION_SECONDS} seconds",
            },
        ],
    )


def _shot_count_not_supported(
    duration_seconds: int,
    requested_shot_count: int,
) -> V2StoryboardPlanningResult:
    return V2StoryboardPlanningResult(
        status="needs_clarification",
        error_code="storyboard_shot_count_not_supported",
        message=(
            "Storyboard shot count must create short segments and stay within the "
            f"supported 1-{V2_MAX_STORYBOARD_SHOT_COUNT} shot range."
        ),
        details={
            "requested_duration_seconds": duration_seconds,
            "requested_shot_count": requested_shot_count,
            "min_shot_duration_seconds": V2_MIN_SHOT_DURATION_SECONDS,
            "max_storyboard_shot_count": V2_MAX_STORYBOARD_SHOT_COUNT,
        },
        suggested_actions=[
            {
                "action": "use_suggested_shot_count",
                "shot_count": _default_shot_count(duration_seconds),
                "label": f"Use {_default_shot_count(duration_seconds)} shots",
            }
        ],
    )


def _shot_count_from_prompt(prompt: str) -> int | None:
    normalized = prompt.lower()
    patterns = (
        r"\b(?:with|in|as)\s+(\d{1,2})\s+(?:storyboard\s+)?shots?\b",
        r"\b(\d{1,2})\s+(?:storyboard\s+)?shots?\b",
        r"(\d{1,2})\s*(?:个)?(?:镜头|分镜)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1))
    return None
