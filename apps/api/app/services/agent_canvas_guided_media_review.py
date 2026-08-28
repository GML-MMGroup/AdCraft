"""Typed media-review orchestration for guided production."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256

from app.persistence.errors import V2PersistenceError
from app.persistence.agent_canvas_guided_media_resume_repository import (
    queued_guided_media_resume_delivery,
)
from app.schemas.agent_canvas_guided_interactions import (
    GuidanceAwaitingResumeProofV2,
    GuidedInteractionAcceptedV1,
    GuidedInteractionV1,
    GuidedMediaReviewSubmitV1,
    GuidedMediaReviewV1,
    GuidanceAwaitingV2,
)
from app.schemas.agent_canvas_media_review_authority import (
    CanvasPostReadyEffectDispositionV1,
    CanvasExecutionResultLineageV2,
    GuidedMediaReviewPublicationCommandV1,
)
from app.schemas.agent_canvas_runtime_authority import CanvasPostReadyEffectV2
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
        result_commits=None,
        receipts=None,
        events=None,
        resume_media_confirmation: Callable[[str], None] | None = None,
        node_resolver: Callable[[str, str], object] | None = None,
        execution_settings: Callable[[str], object] | None = None,
    ) -> None:
        self._interactions = interactions
        self._conversations = conversations
        self._plans = plans
        self._assets = assets
        self._confirmations = confirmations
        self._result_commits = result_commits
        self._receipts = receipts
        self._events = events
        self._resume_media_confirmation = resume_media_confirmation
        self._node_resolver = node_resolver
        self._execution_settings = execution_settings

    def on_node_ready(self, node) -> tuple[str, ...]:
        return self._on_node_ready(
            node,
            reconcile_current=True,
            require_terminal_wait=True,
        )

    def publish_from_effect(
        self,
        effect: CanvasPostReadyEffectV2,
    ) -> CanvasPostReadyEffectDispositionV1:
        """Publish review authority from one immutable terminal result effect."""

        if self._result_commits is None:
            raise _error(
                "guided_media_result_lineage_invalid",
                "Result lineage repository is not configured.",
            )
        lineage = self._result_commits.get_lineage(effect.source_commit_id)
        if (
            lineage.workflow_id != effect.workflow_id
            or lineage.node_id != effect.node_id
            or lineage.outcome != "succeeded"
            or lineage.asset_id is None
            or lineage.asset_version_id is None
        ):
            raise _error(
                "guided_media_result_lineage_invalid",
                "Post-Ready result lineage does not match the effect.",
            )
        node = (
            self._node_resolver(effect.workflow_id, effect.node_id) if self._node_resolver else None
        )
        session = self._conversations.get_guidance_session_or_none(effect.workflow_id)
        plan, record = _find_plan_record(self._plans, effect.workflow_id, effect.node_id)
        if node is None or session is None or plan is None or record is None:
            return CanvasPostReadyEffectDispositionV1(
                outcome="superseded",
                reason_code="not_current_guided_media",
            )
        awaiting = getattr(session, "awaiting", None)
        if (
            awaiting is None
            or awaiting.kind != "manual_node_run"
            or awaiting.resume_policy != "node_terminal"
            or effect.node_id not in awaiting.node_ids
        ):
            if (
                awaiting is not None
                and awaiting.kind == "media_review"
                and awaiting.interaction_id
                == _review_identity(
                    effect.source_commit_id,
                    plan.document_id,
                    plan.revision,
                    node.node_id,
                    lineage.asset_version_id,
                )[0]
            ):
                return CanvasPostReadyEffectDispositionV1(
                    outcome="already_applied",
                    reason_code="media_review_already_published",
                    interaction_id=awaiting.interaction_id,
                )
            if awaiting is None and self._is_automatic_mode(effect.workflow_id):
                if node.output_asset_id != lineage.asset_id or node.status != "ready":
                    return CanvasPostReadyEffectDispositionV1(
                        outcome="superseded",
                        reason_code="current_output_replaced",
                    )
                return self._delegate_result_confirmation(
                    effect=effect,
                    lineage=lineage,
                    node=node,
                    session=session,
                    plan=plan,
                    record=record,
                )
            return CanvasPostReadyEffectDispositionV1(
                outcome="superseded",
                reason_code="current_wait_replaced",
            )
        if node.output_asset_id != lineage.asset_id or node.status != "ready":
            return CanvasPostReadyEffectDispositionV1(
                outcome="superseded",
                reason_code="current_output_replaced",
            )
        review_id, checkpoint_id, awaiting_id = _review_identity(
            effect.source_commit_id,
            plan.document_id,
            plan.revision,
            node.node_id,
            lineage.asset_version_id,
        )
        actions = (
            ("accept", "retry", "replace")
            if record.node_role == "storyboard_grid"
            else ("accept", "retry", "replace", "exclude")
        )
        command = GuidedMediaReviewPublicationCommandV1(
            lineage=lineage,
            session_id=session.session_id,
            plan_document_id=plan.document_id,
            plan_revision=plan.revision,
            planned_node_role=record.node_role,
            planned_sequence_id=record.sequence_id,
            planned_node_revision=record.node_revision,
            current_node_revision=node.revision,
            asset_id=lineage.asset_id,
            asset_version_id=lineage.asset_version_id,
            expected_awaiting_id=awaiting.awaiting_id,
            expected_awaiting_node_ids=awaiting.node_ids,
            expected_session_revision=session.revision,
            expected_stage=session.journey.stage,
            expected_stage_revision=session.journey.stage_revision,
            interaction_id=review_id,
            checkpoint_id=checkpoint_id,
            review_awaiting_id=awaiting_id,
            response_locale=session.response_locale,
            title=node.title,
            summary=node.title,
            allowed_actions=actions,
        )
        try:
            return self._interactions.publish_media_review_from_result(command)
        except V2PersistenceError as error:
            if error.code == "guidance_revision_conflict":
                return CanvasPostReadyEffectDispositionV1(
                    outcome="deferred",
                    reason_code="guided_interaction_conflict",
                )
            if error.code in {
                "execution_result_lineage_not_found",
                "execution_result_lineage_unavailable",
            }:
                raise _error(
                    "guided_media_result_lineage_invalid",
                    "Current Guided media result lineage could not be resolved.",
                ) from error
            raise

    def _is_automatic_mode(self, workflow_id: str) -> bool:
        if self._execution_settings is None:
            return False
        setting = self._execution_settings(workflow_id)
        return getattr(setting, "media_execution_mode", None) == "automatic"

    def _delegate_result_confirmation(
        self,
        *,
        effect: CanvasPostReadyEffectV2,
        lineage: CanvasExecutionResultLineageV2,
        node,
        session,
        plan,
        record,
    ) -> CanvasPostReadyEffectDispositionV1:
        review_id, _checkpoint_id, _awaiting_id = _review_identity(
            effect.source_commit_id,
            plan.document_id,
            plan.revision,
            node.node_id,
            lineage.asset_version_id,
        )
        result = self._confirmations.confirm_result(
            workflow_id=effect.workflow_id,
            plan_document_id=plan.document_id,
            expected_plan_revision=plan.revision,
            node_id=node.node_id,
            expected_node_revision=node.revision,
            asset_id=lineage.asset_id,
            asset_version_id=lineage.asset_version_id,
            accepted_by="agent",
            action_id=f"delegated-media-review:{review_id}",
            decision_id="accept",
        )
        if self._resume_media_confirmation is not None:
            self._resume_media_confirmation(result.confirmation.confirmation_id)
        return CanvasPostReadyEffectDispositionV1(
            outcome="applied",
            reason_code="automatic_media_result_confirmed",
        )

    def _on_node_ready(
        self,
        node,
        *,
        reconcile_current: bool,
        require_terminal_wait: bool,
        allow_result_revision_advance: bool = False,
    ) -> tuple[str, ...]:
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
        review_revision = getattr(node, "metadata", {}).get("guided_review_node_revision")
        if allow_result_revision_advance:
            review_revision = node.revision
        elif review_revision is None:
            if record.node_revision != node.revision:
                return ()
        elif review_revision != node.revision:
            return ()
        current_awaiting = getattr(session, "awaiting", None)
        if require_terminal_wait:
            if (
                current_awaiting is None
                or current_awaiting.kind != "manual_node_run"
                or current_awaiting.resume_policy != "node_terminal"
                or node.node_id not in current_awaiting.node_ids
                or not self._manual_wait_is_ready(
                    node.workflow_id,
                    current_awaiting.node_ids,
                )
            ):
                return ()
            self._interactions.resume_awaiting(
                node.workflow_id,
                GuidanceAwaitingResumeProofV2(
                    awaiting_id=current_awaiting.awaiting_id,
                    expected_session_revision=session.revision,
                    evidence_kind="node_terminal",
                    node_ids=current_awaiting.node_ids,
                ),
            )
            session = self._conversations.get_guidance_session(node.workflow_id)
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
            if self._resume_media_confirmation is not None:
                self._resume_media_confirmation(result.confirmation.confirmation_id)
            created_node_ids = result.created_node_ids
            if reconcile_current:
                created_node_ids = tuple(
                    dict.fromkeys(
                        (
                            *created_node_ids,
                            *self.reconcile_current_plan(node.workflow_id),
                        )
                    )
                )
            return created_node_ids

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
            title=node.title,
            context=node.title,
            content=GuidedMediaReviewV1(
                node_id=node.node_id,
                node_revision=node.revision,
                asset_id=asset.asset_id,
                asset_version_id=asset.version_id or "",
                summary=node.title,
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
            GuidanceAwaitingV2(
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

    def reconcile_current_plan(self, workflow_id: str) -> tuple[str, ...]:
        """Publish the next exact review missing from the current Plan revision."""

        if self._receipts is None or self._node_resolver is None:
            return ()
        session = self._conversations.get_guidance_session_or_none(workflow_id)
        if session is None or getattr(session, "awaiting", None) is not None:
            return ()
        confirmations = self._receipts.list_confirmations(workflow_id)
        created_node_ids: list[str] = []
        for plan in self._plans.list_plans(workflow_id).items:
            records = tuple(
                getattr(plan.content, "planned_nodes", None)
                or getattr(plan.content, "node_records", ())
            )
            for record in records:
                if record.node_role not in {"video_segment", "bgm"}:
                    continue
                node = self._node_resolver(workflow_id, record.node_id)
                if node.status != "ready" or node.output_asset_id is None:
                    continue
                asset = self._assets(node.output_asset_id)
                if _has_current_confirmation(
                    confirmations,
                    plan=plan,
                    record=record,
                    node=node,
                    asset=asset,
                ):
                    continue
                if self._result_commits is not None:
                    effect = self._result_commits.find_latest_post_ready_effect(
                        workflow_id=workflow_id,
                        node_id=record.node_id,
                    )
                    if (
                        effect is not None
                        and self._is_automatic_mode(workflow_id)
                        and record.node_role in {"video_segment", "bgm"}
                    ):
                        self._confirmations.confirm_result(
                            workflow_id=workflow_id,
                            plan_document_id=plan.document_id,
                            expected_plan_revision=plan.revision,
                            node_id=node.node_id,
                            expected_node_revision=node.revision,
                            asset_id=asset.asset_id,
                            asset_version_id=asset.version_id or "",
                            accepted_by="agent",
                            action_id=(
                                "automatic-media-reconciliation:"
                                f"{plan.document_id}:{plan.revision}:"
                                f"{node.node_id}:{asset.version_id}"
                            ),
                            decision_id="accept",
                        )
                        confirmations = self._receipts.list_confirmations(workflow_id)
                        continue
                    if effect is not None and session.awaiting is not None:
                        self.publish_from_effect(effect)
                    elif effect is not None:
                        created_node_ids.extend(
                            self._on_node_ready(
                                node,
                                reconcile_current=False,
                                require_terminal_wait=False,
                                allow_result_revision_advance=True,
                            )
                        )
                if not (
                    session.creative_authority is not None
                    and session.creative_authority.authority == "director"
                ):
                    return tuple(dict.fromkeys(created_node_ids))
                session = self._conversations.get_guidance_session_or_none(workflow_id)
                if session is None or getattr(session, "awaiting", None) is not None:
                    return tuple(dict.fromkeys(created_node_ids))
        return tuple(dict.fromkeys(created_node_ids))

    def _manual_wait_is_ready(
        self,
        workflow_id: str,
        node_ids: tuple[str, ...],
    ) -> bool:
        if node_ids == ():
            return False
        if self._node_resolver is None:
            return len(node_ids) == 1
        return all(
            getattr(self._node_resolver(workflow_id, node_id), "status", None) == "ready"
            for node_id in node_ids
        )


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
        accepted = self._interactions.submit_media_review(
            interaction,
            request,
            submission_id=submission_id,
            idempotency_key=idempotency_key,
            receipt_id=outcome.receipt_id,
            post_action_session_revision=session.revision,
            created_node_ids=outcome.created_node_ids,
            created_binding_ids=outcome.created_binding_ids,
            automatic_run_command_ids=outcome.automatic_run_command_ids,
            resume_delivery=(
                queued_guided_media_resume_delivery(
                    workflow_id=interaction.workflow_id,
                    submission_id=submission_id,
                    confirmation_id=outcome.receipt_id,
                    now=datetime.now(timezone.utc),
                )
                if request.action == "accept"
                else None
            ),
        )
        return accepted

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


def _review_identity(
    source_commit_id: str,
    plan_document_id: str,
    plan_revision: int,
    node_id: str,
    version_id: str,
) -> tuple[str, str, str]:
    logical_identity = ":".join(
        (plan_document_id, str(plan_revision), node_id, version_id, source_commit_id)
    )
    digest = sha256(logical_identity.encode()).hexdigest()[:32]
    return (
        f"interaction_media_{digest}",
        f"checkpoint_media_{digest}",
        f"awaiting_media_{digest}",
    )


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


def _has_current_confirmation(confirmations, *, plan, record, node, asset) -> bool:
    media_role = "audio" if record.node_role == "bgm" else "video"
    return any(
        confirmation.plan_document_id == plan.document_id
        and confirmation.plan_revision == plan.revision
        and confirmation.media_role == media_role
        and confirmation.sequence_id == record.sequence_id
        and confirmation.node_id == node.node_id
        and confirmation.node_revision == node.revision
        and confirmation.asset_id == asset.asset_id
        and confirmation.asset_version_id == asset.version_id
        and confirmation.asset_digest == asset.checksum
        for confirmation in confirmations
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_media_review")
