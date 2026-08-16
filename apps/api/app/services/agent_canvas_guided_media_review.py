"""Typed media-review orchestration for guided production."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_guided_interactions import (
    GuidanceAwaitingResumeProofV1,
    GuidedInteractionAcceptedV1,
    GuidedInteractionV1,
    GuidedMediaReviewSubmitV1,
    GuidedMediaReviewV1,
    GuidanceAwaitingV1,
)
from app.schemas.agent_canvas import (
    CanvasVariationDraftUpsertV2,
    CanvasVariationMaterializeRequestV2,
)
from app.schemas.agent_working_documents import (
    StoryboardExcludedMediaV3,
    StoryboardPlannedNodeV3,
    StoryboardProductionPlanContentV3,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_guided_media_confirmation import (
    GuidedMediaConfirmationService,
)


@dataclass(frozen=True)
class GuidedMediaActionOutcome:
    receipt_id: str
    created_node_ids: tuple[str, ...] = ()
    created_binding_ids: tuple[str, ...] = ()
    automatic_run_command_ids: tuple[str, ...] = ()


MediaAction = Callable[
    [GuidedInteractionV1, GuidedMediaReviewSubmitV1, str],
    GuidedMediaActionOutcome,
]


class GuidedMediaReviewCoordinator:
    """Open user review or apply delegated structural acceptance for Ready media."""

    def __init__(
        self,
        *,
        interactions,
        conversations,
        plans,
        assets,
        confirmations: GuidedMediaConfirmationService,
        events=None,
    ) -> None:
        self._interactions = interactions
        self._conversations = conversations
        self._plans = plans
        self._assets = assets
        self._confirmations = confirmations
        self._events = events

    def on_node_ready(self, node) -> tuple[str, ...]:
        session = self._conversations.get_guidance_session_or_none(node.workflow_id)
        if session is None or node.output_asset_id is None:
            return ()
        plan, record = _find_plan_record(self._plans, node.workflow_id, node.node_id)
        if plan is None or record.node_role not in {
            "storyboard_grid",
            "video_segment",
            "bgm",
        }:
            return ()
        asset = self._assets(node.output_asset_id)
        logical_identity = ":".join(
            (
                plan.document_id,
                str(plan.revision),
                node.node_id,
                str(node.revision),
                asset.version_id or "",
            )
        )
        review_id = sha256(logical_identity.encode()).hexdigest()[:32]
        if (
            session.creative_authority is not None
            and session.creative_authority.authority == "director"
        ):
            result = self._confirmations.confirm_result(
                workflow_id=node.workflow_id,
                plan_document_id=plan.document_id,
                expected_plan_revision=plan.revision,
                node_id=node.node_id,
                expected_node_revision=node.revision,
                asset_id=asset.asset_id,
                asset_version_id=asset.version_id or "",
                accepted_by="agent",
                action_id=f"delegated-media-review:{review_id}",
                decision_id="accept",
            )
            return result.created_node_ids

        current_awaiting = getattr(session, "awaiting", None)
        if (
            current_awaiting is not None
            and current_awaiting.kind == "manual_node_run"
            and current_awaiting.node_ids == (node.node_id,)
        ):
            self._interactions.resume_awaiting(
                node.workflow_id,
                GuidanceAwaitingResumeProofV1(
                    awaiting_id=current_awaiting.awaiting_id,
                    expected_session_revision=session.revision,
                    evidence_kind="node_terminal",
                    node_ids=current_awaiting.node_ids,
                ),
            )
            session = self._conversations.get_guidance_session(node.workflow_id)

        interaction_id = f"interaction_media_{review_id}"
        now = datetime.now(timezone.utc)
        actions = (
            ("accept", "retry", "replace")
            if record.node_role == "storyboard_grid"
            else ("accept", "retry", "replace", "exclude")
        )
        interaction = GuidedInteractionV1(
            interaction_id=interaction_id,
            workflow_id=node.workflow_id,
            session_id=session.session_id,
            checkpoint_id=f"checkpoint_media_{review_id}",
            kind="media_review",
            status="open",
            response_locale=session.response_locale,
            expected_session_revision=session.revision,
            revision=1,
            title=f"Review {node.title}",
            context="Review the exact current media result before guided production continues.",
            content=GuidedMediaReviewV1(
                node_id=node.node_id,
                node_revision=node.revision,
                asset_id=asset.asset_id,
                asset_version_id=asset.version_id or "",
                summary=f"{node.title} is ready for review.",
            ),
            allowed_actions=actions,
            submit_path=(
                f"/api/v2/workflows/{node.workflow_id}/chat/interactions/{interaction_id}/submit"
            ),
            created_at=now,
            updated_at=now,
        )
        self._interactions.open_with_awaiting(
            interaction,
            GuidanceAwaitingV1(
                awaiting_id=f"awaiting_media_{review_id}",
                workflow_id=node.workflow_id,
                session_id=session.session_id,
                checkpoint_id=interaction.checkpoint_id,
                kind="media_review",
                requires_user_action=True,
                resume_policy="submit_interaction",
                interaction_id=interaction_id,
                stage=session.journey.stage,
                stage_revision=session.journey.stage_revision,
                created_at=now,
            ),
        )
        if self._events is not None:
            self._events.append(
                V2EventInsert(
                    workflow_id=node.workflow_id,
                    node_id=node.node_id,
                    event_type="guided_media_review_required",
                    transition_key=f"guided-media-review-required:{interaction_id}",
                    created_at=now.isoformat(),
                    payload={
                        "interaction_id": interaction_id,
                        "plan_document_id": plan.document_id,
                        "plan_revision": plan.revision,
                        "node_revision": node.revision,
                        "asset_id": asset.asset_id,
                        "asset_version_id": asset.version_id,
                        "allowed_actions": list(actions),
                    },
                )
            )
        return ()


class GuidedMediaReviewActionService:
    """Execute one declared media-review action without semantic reinterpretation."""

    def __init__(
        self,
        *,
        interactions,
        conversations,
        plans,
        confirmations: GuidedMediaConfirmationService,
        retry: MediaAction,
        replace: MediaAction,
        exclude: MediaAction,
    ) -> None:
        self._interactions = interactions
        self._conversations = conversations
        self._plans = plans
        self._confirmations = confirmations
        self._actions = {
            "retry": retry,
            "replace": replace,
            "exclude": exclude,
        }

    def submit(
        self,
        interaction: GuidedInteractionV1,
        request: GuidedMediaReviewSubmitV1,
        *,
        submission_id: str,
        idempotency_key: str,
    ) -> GuidedInteractionAcceptedV1:
        if not isinstance(interaction.content, GuidedMediaReviewV1) or (
            request.action not in interaction.allowed_actions
        ):
            raise _error(
                "guided_interaction_action_not_allowed",
                "This media review action is not available.",
            )
        if request.action == "accept":
            outcome = self._accept(interaction, submission_id)
        else:
            outcome = self._actions[request.action](interaction, request, idempotency_key)
        session = self._conversations.get_guidance_session(interaction.workflow_id)
        return self._interactions.submit_media_review(
            interaction,
            request,
            submission_id=submission_id,
            idempotency_key=idempotency_key,
            receipt_id=outcome.receipt_id,
            post_action_session_revision=session.revision,
            created_node_ids=outcome.created_node_ids,
            created_binding_ids=outcome.created_binding_ids,
            automatic_run_command_ids=outcome.automatic_run_command_ids,
        )

    def _accept(
        self,
        interaction: GuidedInteractionV1,
        submission_id: str,
    ) -> GuidedMediaActionOutcome:
        content = interaction.content
        plans = self._plans.list_plans(interaction.workflow_id).items
        plan = next(
            (
                item
                for item in plans
                if any(
                    record.node_id == content.node_id
                    for record in (
                        getattr(item.content, "planned_nodes", None)
                        or getattr(item.content, "node_records", ())
                    )
                )
            ),
            None,
        )
        if plan is None:
            raise _error(
                "guided_media_confirmation_stale",
                "Media review no longer belongs to the current Storyboard Plan.",
            )
        confirmation = self._confirmations.confirm_result(
            workflow_id=interaction.workflow_id,
            plan_document_id=plan.document_id,
            expected_plan_revision=plan.revision,
            node_id=content.node_id,
            expected_node_revision=content.node_revision,
            asset_id=content.asset_id,
            asset_version_id=content.asset_version_id,
            accepted_by="user",
            action_id=submission_id,
            decision_id="accept",
        )
        return GuidedMediaActionOutcome(
            receipt_id=confirmation.confirmation.confirmation_id,
            created_node_ids=confirmation.created_node_ids,
        )


class GuidedMediaPlanActionService:
    """Apply retry, replacement, and exclusion to current Plan authority."""

    def __init__(self, *, workflows, plan_reader, plan_writer, variations) -> None:
        self._workflows = workflows
        self._plan_reader = plan_reader
        self._plan_writer = plan_writer
        self._variations = variations

    def retry(
        self,
        interaction: GuidedInteractionV1,
        request: GuidedMediaReviewSubmitV1,
        idempotency_key: str,
    ) -> GuidedMediaActionOutcome:
        return self._replace(
            interaction,
            instruction="Regenerate this media while preserving the accepted direction.",
            idempotency_key=idempotency_key,
        )

    def replace(
        self,
        interaction: GuidedInteractionV1,
        request: GuidedMediaReviewSubmitV1,
        idempotency_key: str,
    ) -> GuidedMediaActionOutcome:
        if request.instruction is None:
            raise _error(
                "guided_media_replacement_instruction_required",
                "A sibling replacement requires an explicit instruction.",
            )
        return self._replace(
            interaction,
            instruction=request.instruction,
            idempotency_key=idempotency_key,
        )

    def exclude(
        self,
        interaction: GuidedInteractionV1,
        request: GuidedMediaReviewSubmitV1,
        idempotency_key: str,
    ) -> GuidedMediaActionOutcome:
        receipt_id = action_receipt_id("exclude", interaction.interaction_id, idempotency_key)
        replay = self._exclusion_replay(interaction.workflow_id, receipt_id)
        if replay is not None:
            return replay
        plan, record = self._current_plan_record(interaction)
        content = _v3_plan(plan.content)
        exclusion = StoryboardExcludedMediaV3(
            sequence_id=record.sequence_id,
            node_role=record.node_role,
            node_id=record.node_id,
            node_revision=record.node_revision,
            action_id=receipt_id,
        )
        next_content = content.model_copy(
            update={
                "planned_nodes": tuple(
                    item
                    for item in content.planned_nodes
                    if item.node_role != "editing"
                    and (item.sequence_id, item.node_role) != (record.sequence_id, record.node_role)
                ),
                "excluded_media": content.excluded_media + (exclusion,),
            }
        )
        updated = self._plan_writer.commit_content_mutation(
            workflow_id=interaction.workflow_id,
            agent_run_id=f"guided-media-review:{interaction.interaction_id}",
            document_id=plan.document_id,
            expected_revision=plan.revision,
            operation="exclude_planned_media",
            idempotency_key=idempotency_key,
            next_content=next_content,
        )
        return GuidedMediaActionOutcome(
            receipt_id=exclusion.action_id,
            automatic_run_command_ids=(f"plan-revision:{updated.revision}",),
        )

    def _replace(
        self,
        interaction: GuidedInteractionV1,
        *,
        instruction: str,
        idempotency_key: str,
    ) -> GuidedMediaActionOutcome:
        receipt_id = action_receipt_id("replace", interaction.interaction_id, idempotency_key)
        replay = self._replacement_replay(interaction.workflow_id, receipt_id)
        if replay is not None:
            return replay
        plan, record = self._current_plan_record(interaction)
        source = self._workflows.get_node(interaction.workflow_id, record.node_id)
        workflow = self._workflows.get_workflow(interaction.workflow_id)
        saved = self._variations.save(
            interaction.workflow_id,
            source.node_id,
            CanvasVariationDraftUpsertV2(
                title=f"{source.title} Alternative",
                generation_prompt=f"{source.generation_prompt}\n\nRevision direction: {instruction}",
                model_selection_mode=source.model_selection_mode,
                model_ref=source.model_ref,
                parameters=source.parameters,
            ),
            expected_revision=workflow.revision,
        )
        materialized = self._variations.materialize(
            interaction.workflow_id,
            source.node_id,
            CanvasVariationMaterializeRequestV2(action="generate"),
            expected_revision=saved.workflow_revision,
            idempotency_key=idempotency_key,
        )
        content = _v3_plan(plan.content)
        replacement = StoryboardPlannedNodeV3(
            sequence_id=record.sequence_id,
            node_role=record.node_role,
            node_id=materialized.sibling_node.node_id,
            node_revision=materialized.sibling_node.revision,
            materialization_id=receipt_id,
        )
        next_content = content.model_copy(
            update={
                "planned_nodes": tuple(
                    replacement
                    if (item.sequence_id, item.node_role) == (record.sequence_id, record.node_role)
                    else item
                    for item in content.planned_nodes
                    if item.node_role != "editing"
                ),
                "excluded_media": tuple(
                    item
                    for item in content.excluded_media
                    if (item.sequence_id, item.node_role) != (record.sequence_id, record.node_role)
                ),
            }
        )
        self._plan_writer.commit_content_mutation(
            workflow_id=interaction.workflow_id,
            agent_run_id=f"guided-media-review:{interaction.interaction_id}",
            document_id=plan.document_id,
            expected_revision=plan.revision,
            operation="replace_planned_media",
            idempotency_key=idempotency_key,
            next_content=next_content,
        )
        return GuidedMediaActionOutcome(
            receipt_id=replacement.materialization_id,
            created_node_ids=materialized.created_node_ids or (materialized.sibling_node.node_id,),
            created_binding_ids=materialized.created_binding_ids or materialized.copied_binding_ids,
            automatic_run_command_ids=(
                (str(materialized.run.get("execution_id")),)
                if materialized.run and materialized.run.get("execution_id")
                else ()
            ),
        )

    def _current_plan_record(self, interaction: GuidedInteractionV1):
        content = interaction.content
        plan, record = _find_plan_record(
            self._plan_reader, interaction.workflow_id, content.node_id
        )
        if plan is None:
            raise _error(
                "guided_media_confirmation_stale",
                "Media review no longer belongs to the current Storyboard Plan.",
            )
        return plan, record

    def _exclusion_replay(
        self,
        workflow_id: str,
        receipt_id: str,
    ) -> GuidedMediaActionOutcome | None:
        for plan in self._plan_reader.list_plans(workflow_id).items:
            exclusions = tuple(getattr(plan.content, "excluded_media", ()))
            if any(item.action_id == receipt_id for item in exclusions):
                return GuidedMediaActionOutcome(
                    receipt_id=receipt_id,
                    automatic_run_command_ids=(f"plan-revision:{plan.revision}",),
                )
        return None

    def _replacement_replay(
        self,
        workflow_id: str,
        receipt_id: str,
    ) -> GuidedMediaActionOutcome | None:
        for plan in self._plan_reader.list_plans(workflow_id).items:
            record = next(
                (
                    item
                    for item in getattr(plan.content, "planned_nodes", ())
                    if item.materialization_id == receipt_id
                ),
                None,
            )
            if record is not None:
                return GuidedMediaActionOutcome(
                    receipt_id=receipt_id,
                    created_node_ids=(record.node_id,),
                )
        return None


def action_receipt_id(action: str, interaction_id: str, idempotency_key: str) -> str:
    value = f"{action}:{interaction_id}:{idempotency_key}"
    return f"media_action_{sha256(value.encode()).hexdigest()[:32]}"


def _v3_plan(content) -> StoryboardProductionPlanContentV3:
    if not isinstance(content, StoryboardProductionPlanContentV3):
        raise _error(
            "guided_media_confirmation_stale",
            "Media review requires the current authoritative Storyboard Plan.",
        )
    return content


def _find_plan_record(plans, workflow_id: str, node_id: str):
    for plan in plans.list_plans(workflow_id).items:
        records = tuple(
            getattr(plan.content, "planned_nodes", None)
            or getattr(plan.content, "node_records", ())
        )
        record = next((item for item in records if item.node_id == node_id), None)
        if record is not None:
            return plan, record
    return None, None


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_media_review")
