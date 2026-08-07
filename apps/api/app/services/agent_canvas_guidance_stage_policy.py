"""Deterministic soft-stage policy for guided advertisement authoring."""

from __future__ import annotations

from app.schemas.agent_canvas_creative_session import (
    GuidanceStageKindV2,
    GuidanceStagePolicyResultV2,
    GuidedSessionStateV2,
)


_FOUNDATION_ORDER: tuple[GuidanceStageKindV2, ...] = (
    "product",
    "character",
    "scene",
    "prop",
)
ALL_GUIDANCE_STAGES: tuple[GuidanceStageKindV2, ...] = (
    "world_setting",
    "narrative_direction",
    "product",
    "prop",
    "character",
    "scene",
    "script",
    "storyboard",
    "video",
    "bgm",
    "editing",
)


class GuidanceStagePolicyV2:
    """Recommend one coherent next stage without persisting a future queue."""

    def unrestricted(self) -> GuidanceStagePolicyResultV2:
        return _result(ALL_GUIDANCE_STAGES, completion_allowed=True)

    def evaluate(
        self,
        *,
        session: GuidedSessionStateV2,
        existing_stage_kinds: tuple[GuidanceStageKindV2, ...],
        direct_stage_override: GuidanceStageKindV2 | None = None,
    ) -> GuidanceStagePolicyResultV2:
        if direct_stage_override is not None:
            return _result((direct_stage_override,), completion_allowed=False)
        existing = set(existing_stage_kinds)
        if "world_setting" not in existing:
            return _result(
                ("world_setting",),
                blocking_facts=("world_setting_required",),
            )
        if not session.narrative_direction:
            return _result(
                ("narrative_direction",),
                blocking_facts=("narrative_direction_unresolved",),
            )
        presence = {item.element_kind: item.presence for item in session.element_decisions}
        unresolved_foundations = tuple(
            stage
            for stage in _FOUNDATION_ORDER
            if presence.get(stage) == "include" and stage not in existing
        )
        if unresolved_foundations:
            return _result(
                unresolved_foundations,
                unresolved=unresolved_foundations,
                blocking_facts=tuple(
                    f"{stage}_foundation_unresolved" for stage in unresolved_foundations
                ),
            )
        if "script" not in existing:
            return _result(("script",), blocking_facts=("script_unresolved",))
        if "storyboard" not in existing:
            return _result(("storyboard",), blocking_facts=("storyboard_unresolved",))
        if "video" not in existing:
            return _result(("video",), blocking_facts=("video_unresolved",))
        if presence.get("audio") == "include" and "bgm" not in existing:
            return _result(("bgm",), blocking_facts=("bgm_unresolved",))
        if "editing" not in existing:
            return _result(("editing",), completion_allowed=True)
        return GuidanceStagePolicyResultV2(
            allowed_stage_kinds=(),
            recommended_stage_kinds=(),
            completion_allowed=True,
        )


def _result(
    stages: tuple[GuidanceStageKindV2, ...],
    *,
    unresolved: tuple[GuidanceStageKindV2, ...] = (),
    blocking_facts: tuple[str, ...] = (),
    completion_allowed: bool = False,
) -> GuidanceStagePolicyResultV2:
    return GuidanceStagePolicyResultV2(
        allowed_stage_kinds=stages,
        recommended_stage_kinds=stages,
        unresolved_element_kinds=tuple(
            stage for stage in unresolved if stage in {"product", "prop", "character", "scene"}
        ),
        blocking_facts=blocking_facts,
        completion_allowed=completion_allowed,
    )
