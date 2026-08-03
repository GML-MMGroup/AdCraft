"""Deterministic validation for adaptive Agent Canvas production recipes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_conversation import ConceptProposalCreateV2
from app.schemas.agent_canvas_creative_session import (
    AdaptiveProductionRecipeDraftV2,
    AdaptiveProductionRecipeV2,
    AdaptiveProductionStageV2,
    AgentCanvasSpecialistNameV2,
    CreationModeDecisionV2,
    CreationModeV2,
)


TOPIC_SPECIALIST: dict[str, AgentCanvasSpecialistNameV2] = {
    "creative_direction": "script_writer",
    "product": "product_designer",
    "prop": "prop_designer",
    "character": "character_designer",
    "scene": "scene_designer",
    "script": "script_writer",
    "storyboard": "storyboard_artist",
    "video": "video_director",
    "audio": "bgm_director",
}


class CreationModeGate:
    """Validate a Pi-authored creation-mode decision against explicit targets."""

    def resolve(
        self,
        decision: CreationModeDecisionV2,
        *,
        explicit_node_ids: tuple[str, ...] = (),
        explicit_asset_ids: tuple[str, ...] = (),
    ) -> CreationModeDecisionV2:
        node_targets = set(explicit_node_ids)
        asset_targets = set(explicit_asset_ids)
        if decision.target_node_id is not None:
            node_targets.add(decision.target_node_id)
        if decision.target_asset_id is not None:
            asset_targets.add(decision.target_asset_id)
        target_count = len(node_targets) + len(asset_targets)

        explicit_targets = set(explicit_node_ids) | set(explicit_asset_ids)
        if decision.mode == "targeted_authoring" and (
            target_count != 1 or len(explicit_targets) != 1
        ):
            raise _error(
                "creation_mode_invalid",
                "Targeted authoring requires exactly one explicit target.",
            )
        if decision.mode == "quick_media" and (target_count != 1 or len(explicit_targets) != 1):
            raise _error(
                "creation_mode_invalid",
                "Quick media requires exactly one explicit source or target.",
            )
        if decision.target_node_id is not None and explicit_node_ids:
            if decision.target_node_id not in explicit_node_ids:
                raise _error(
                    "creation_mode_invalid",
                    "The creation-mode node target does not match the explicit target.",
                )
        if decision.target_asset_id is not None and explicit_asset_ids:
            if decision.target_asset_id not in explicit_asset_ids:
                raise _error(
                    "creation_mode_invalid",
                    "The creation-mode asset target does not match the explicit target.",
                )
        return decision


class AdaptiveProductionRecipeValidator:
    """Convert an untrusted Pi recipe draft into a strict internal recipe."""

    def validate(
        self,
        draft: AdaptiveProductionRecipeDraftV2,
        *,
        workflow_id: str,
        conversation_id: str,
        skill_run_id: str | None,
        creation_mode: CreationModeV2,
        recipe_id: str,
        revision: int,
        expected_anchor_digest: str,
        now: datetime | None = None,
    ) -> AdaptiveProductionRecipeV2:
        if creation_mode != "guided_production":
            raise _error(
                "adaptive_recipe_invalid",
                "Adaptive production recipes require guided production mode.",
            )
        if draft.anchor_digest != expected_anchor_digest:
            raise _error(
                "creative_anchor_drift",
                "The production recipe does not preserve the approved creative anchors.",
            )
        topic_ids = tuple(stage.topic_id for stage in draft.stages)
        if len(topic_ids) != len(set(topic_ids)):
            raise _error(
                "adaptive_recipe_invalid",
                "Production recipe topic IDs must be unique.",
            )
        for stage in draft.stages:
            self._validate_stage(stage)
        next_topic_id = self.next_topic_id(draft.stages)
        if next_topic_id is None:
            raise _error(
                "adaptive_recipe_invalid",
                "A production recipe requires at least one applicable nonterminal stage.",
            )
        if draft.current_topic_id != next_topic_id:
            raise _error(
                "adaptive_recipe_invalid",
                "The current topic must be the first applicable nonterminal stage.",
            )
        timestamp = now or datetime.now(timezone.utc)
        return AdaptiveProductionRecipeV2(
            recipe_id=recipe_id,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            skill_run_id=skill_run_id,
            revision=revision,
            creation_mode=creation_mode,
            goal=draft.goal,
            current_topic_id=next_topic_id,
            stages=draft.stages,
            anchor_digest=draft.anchor_digest,
            deliverables=draft.deliverables,
            dependencies=draft.dependencies,
            recommended_next_topic_ids=draft.recommended_next_topic_ids,
            completion_criteria=draft.completion_criteria,
            created_at=timestamp,
            updated_at=timestamp,
        )

    @staticmethod
    def next_topic_id(stages: tuple[AdaptiveProductionStageV2, ...]) -> str | None:
        return next(
            (
                stage.topic_id
                for stage in stages
                if stage.applicability != "not_required"
                and stage.status in {"pending", "working", "reopened"}
            ),
            None,
        )

    @staticmethod
    def _validate_stage(stage: AdaptiveProductionStageV2) -> None:
        expected_specialist = TOPIC_SPECIALIST[stage.topic_kind]
        if stage.specialist_name != expected_specialist:
            raise _error(
                "adaptive_recipe_stage_invalid",
                "The production stage is assigned to the wrong Specialist.",
                details={
                    "topic_id": stage.topic_id,
                    "expected_specialist": expected_specialist,
                    "actual_specialist": stage.specialist_name,
                },
            )
        if stage.proposal_mode == "single_plan" and stage.candidate_count != 1:
            raise _error(
                "adaptive_recipe_stage_invalid",
                "A single-plan stage requires exactly one candidate.",
                details={"topic_id": stage.topic_id},
            )
        if stage.proposal_mode == "choice_set" and not 2 <= stage.candidate_count <= 4:
            raise _error(
                "adaptive_recipe_stage_invalid",
                "A choice-set stage requires two through four candidates.",
                details={"topic_id": stage.topic_id},
            )
        if stage.applicability == "not_required" and stage.status != "not_required":
            raise _error(
                "adaptive_recipe_stage_invalid",
                "A not-required stage must have not-required status.",
                details={"topic_id": stage.topic_id},
            )
        if stage.applicability != "not_required" and stage.status == "not_required":
            raise _error(
                "adaptive_recipe_stage_invalid",
                "An applicable stage cannot have not-required status.",
                details={"topic_id": stage.topic_id},
            )


class GuidedTopicRouter:
    """Enforce the Director-to-current-Specialist handoff boundary."""

    def validate_handoff(
        self,
        decision: CreationModeDecisionV2,
        recipe: AdaptiveProductionRecipeV2,
        *,
        actual_specialist: str,
        explicit_target: bool = False,
    ) -> None:
        if decision.mode == "targeted_authoring" and explicit_target:
            return
        if decision.mode != "guided_production":
            return
        current = _current_stage(recipe)
        if current.specialist_name == actual_specialist:
            return
        raise _error(
            "adaptive_recipe_handoff_invalid",
            "The selected Specialist does not own the current production topic.",
            details={
                "recipe_id": recipe.recipe_id,
                "recipe_revision": recipe.revision,
                "topic_id": current.topic_id,
                "expected_specialist": current.specialist_name,
                "actual_specialist": actual_specialist,
            },
        )


class SpecialistProposalValidator:
    """Validate Specialist result shape against the active stage policy."""

    def validate_cardinality(
        self,
        stage: AdaptiveProductionStageV2,
        proposal: ConceptProposalCreateV2,
    ) -> ConceptProposalCreateV2:
        if proposal.specialist_name != stage.specialist_name:
            raise _error(
                "adaptive_recipe_handoff_invalid",
                "The proposal Specialist does not own the current production topic.",
                details={
                    "topic_id": stage.topic_id,
                    "expected_specialist": stage.specialist_name,
                    "actual_specialist": proposal.specialist_name,
                },
            )
        if len(proposal.options) != stage.candidate_count:
            raise _error(
                "proposal_cardinality_invalid",
                "The proposal option count does not match the current stage policy.",
                details={
                    "topic_id": stage.topic_id,
                    "proposal_mode": stage.proposal_mode,
                    "expected_count": stage.candidate_count,
                    "actual_count": len(proposal.options),
                },
            )
        return proposal


def _current_stage(recipe: AdaptiveProductionRecipeV2) -> AdaptiveProductionStageV2:
    current = next(
        (stage for stage in recipe.stages if stage.topic_id == recipe.current_topic_id),
        None,
    )
    if current is None:
        raise _error(
            "adaptive_recipe_invalid",
            "The active production recipe has no valid current topic.",
            details={
                "recipe_id": recipe.recipe_id,
                "recipe_revision": recipe.revision,
            },
        )
    return current


def _error(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> V2PersistenceError:
    safe_details = (
        {key: str(value) for key, value in details.items()} if details is not None else None
    )
    return V2PersistenceError(
        code,
        message,
        stage="agent_canvas_adaptive_recipe",
        details=cast(dict[str, object] | None, safe_details),
    )
