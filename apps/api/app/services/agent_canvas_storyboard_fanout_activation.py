"""Activate persisted Storyboard fan-out Drafts through declared Run authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable

from app.schemas.agent_canvas_guided_interactions import GuidanceAwaitingV2
from app.schemas.agent_canvas_progressive_authoring import StageAuthoringContextV1


@dataclass(frozen=True)
class StoryboardFanoutActivationResult:
    """Observable result of one idempotent fan-out activation pass."""

    prepared_node_ids: tuple[str, ...]
    manual_awaiting_id: str | None
    automatic_run_command_ids: tuple[str, ...]


class StoryboardFanoutActivationService:
    """Prepare fan-out Drafts and publish only the next dependency-ready Run."""

    def __init__(
        self,
        *,
        workflows,
        conversations,
        requirements,
        documents,
        receipts,
        prompt_preparation,
        progression,
        execution_settings: Callable[[str], object],
        awaiting,
        automatic_runs,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._requirements = requirements
        self._documents = documents
        self._receipts = receipts
        self._prompt_preparation = prompt_preparation
        self._progression = progression
        self._execution_settings = execution_settings
        self._awaiting = awaiting
        self._automatic_runs = automatic_runs
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def resume_confirmation(
        self,
        confirmation_id: str,
    ) -> StoryboardFanoutActivationResult:
        self._receipts.get_confirmation(confirmation_id)
        fanout = self._receipts.find_fanout_for_confirmation(confirmation_id)
        if fanout is None:
            return StoryboardFanoutActivationResult((), None, ())

        prepared_node_ids: list[str] = []
        for plan, operation_id in zip(
            fanout.nodes,
            fanout.prompt_preparation_keys,
            strict=True,
        ):
            current_node = self._workflows.get_node(fanout.workflow_id, plan.node_id)
            current_preparation = getattr(current_node, "prompt_preparation", None)
            if getattr(current_preparation, "status", None) in {"queued", "working"}:
                # A dependency wave may already own this node through the
                # durable prompt-preparation dispatch.  Calling prepare here
                # would race that owner and advance the node revision behind
                # the dispatch snapshot, so leave the existing worker/barrier
                # path in charge.
                prepared_node_ids.append(plan.node_id)
                continue
            current_operation_id = getattr(
                current_preparation,
                "operation_id",
                None,
            )
            if isinstance(current_operation_id, str) and current_operation_id:
                # A dependency wave may have superseded the plan's original
                # preparation identity.  Reuse the durable current owner;
                # never restart a stale operation during media confirmation.
                operation_id = current_operation_id
            self._prompt_preparation.prepare(
                fanout.workflow_id,
                plan.node_id,
                operation_id=operation_id,
                context=self._authoring_context(
                    fanout,
                    sequence_id=plan.sequence_id,
                    node_role=plan.node_role,
                ),
            )
            prepared_node_ids.append(plan.node_id)

        self._progression.record_storyboard_pipeline_prepared(
            fanout.workflow_id,
            source_id=fanout.fanout_plan_id,
        )
        workflow = self._workflows.get_workflow(fanout.workflow_id)
        next_node_id = self._next_runnable_node_id(
            workflow,
            tuple(plan.node_id for plan in fanout.nodes),
        )
        if next_node_id is None:
            return StoryboardFanoutActivationResult(
                tuple(prepared_node_ids),
                None,
                (),
            )
        return self._activate_runnable_node(
            workflow_id=fanout.workflow_id,
            node_id=next_node_id,
            source_action_id=_run_identity(fanout.fanout_plan_id, next_node_id),
            prepared_node_ids=tuple(prepared_node_ids),
        )

    def activate_prompt_ready_nodes(
        self,
        workflow_id: str,
        node_ids: tuple[str, ...],
        *,
        source_id: str,
    ) -> StoryboardFanoutActivationResult:
        """Publish Run authority for newly prompt-ready planned media."""

        workflow = self._workflows.get_workflow(workflow_id)
        execution_settings = self._execution_settings(workflow_id)
        if execution_settings.media_execution_mode == "automatic":
            # Recovery callbacks can reach this service without the endpoint
            # wrapper. Keep automatic admission Storyboard-only so a ready
            # Character/Scene/Product node cannot be mistaken for the current
            # Storyboard dependency wave. Manual mode remains unchanged for
            # existing non-Storyboard callers such as BGM.
            nodes_by_id = {node.node_id: node for node in workflow.nodes}
            if any(
                nodes_by_id.get(node_id) is None
                or nodes_by_id[node_id].creative_role
                not in {"storyboard_sequence", "storyboard_video"}
                for node_id in node_ids
            ):
                return StoryboardFanoutActivationResult(node_ids, None, ())
        next_node_id = self._next_runnable_node_id(workflow, node_ids)
        if next_node_id is None:
            return StoryboardFanoutActivationResult(node_ids, None, ())
        return self._activate_runnable_node(
            workflow_id=workflow_id,
            node_id=next_node_id,
            source_action_id=f"planned-media:{source_id}:{next_node_id}",
            prepared_node_ids=node_ids,
        )

    def _activate_runnable_node(
        self,
        *,
        workflow_id: str,
        node_id: str,
        source_action_id: str,
        prepared_node_ids: tuple[str, ...],
    ) -> StoryboardFanoutActivationResult:
        session = self._conversations.get_guidance_session(workflow_id)

        execution_settings = self._execution_settings(workflow_id)
        if execution_settings.media_execution_mode == "automatic":
            command = self._automatic_runs.enqueue(
                workflow_id=workflow_id,
                source_action_id=source_action_id,
                node_id=node_id,
                now=self._clock(),
            )
            return StoryboardFanoutActivationResult(
                prepared_node_ids,
                None,
                (command.command_id,),
            )

        current = self._awaiting.inspect(workflow_id)
        if current is not None:
            if current.kind == "manual_node_run" and current.node_ids == (node_id,):
                return StoryboardFanoutActivationResult(
                    prepared_node_ids,
                    current.awaiting_id,
                    (),
                )
            return StoryboardFanoutActivationResult(
                prepared_node_ids,
                None,
                (),
            )

        manual_wait = GuidanceAwaitingV2(
            awaiting_id=f"awaiting_{_digest(source_action_id)}",
            workflow_id=workflow_id,
            session_id=session.session_id,
            checkpoint_id=f"checkpoint_{_digest(source_action_id)}",
            kind="manual_node_run",
            requires_user_action=True,
            resume_policy="node_terminal",
            node_ids=(node_id,),
            stage=session.journey.stage,
            stage_revision=session.journey.stage_revision,
            created_at=self._clock(),
        )
        persisted = self._awaiting.enter_manual_node_run(
            manual_wait,
            expected_session_revision=session.revision,
            next_action_requires_ready_media=True,
            user_requested_pause=False,
        )
        return StoryboardFanoutActivationResult(
            prepared_node_ids,
            persisted.awaiting_id,
            (),
        )

    def _authoring_context(
        self,
        fanout,
        *,
        sequence_id: str,
        node_role: str,
    ) -> StageAuthoringContextV1:
        session = self._conversations.get_guidance_session(fanout.workflow_id)
        requirement_revision = self._requirements.get_current(fanout.workflow_id)
        controls = getattr(requirement_revision, "hard_controls", None)
        if controls is None:
            controls = getattr(requirement_revision.ledger, "hard_controls", ())
        requirement_facts = {
            item.control: item.value for item in controls if item.control != "duration_seconds"
        }
        if node_role == "video_segment":
            decision = getattr(requirement_revision, "identity_safety_decision", None)
            if decision is not None:
                requirement_facts["identity_safety_decision"] = decision.model_dump(mode="json")
        excerpts = ()
        build_context = getattr(self._documents, "build_bounded_context", None)
        if build_context is not None:
            excerpts = (
                build_context(
                    fanout.plan_document_id,
                    f"sequence:{sequence_id}",
                ),
            )
        anchor = self._workflows.get_node(
            fanout.workflow_id,
            fanout.visual_anchor_node_id,
        )
        style = anchor.structured_content.get("style")
        get_snapshot = getattr(
            self._conversations,
            "get_active_creative_direction_snapshot",
            None,
        )
        snapshot = get_snapshot(fanout.workflow_id) if get_snapshot is not None else None
        public_skill = snapshot.global_direction.get("public_skill") if snapshot else None
        representation_mode = (
            public_skill.get("video_representation_mode")
            if isinstance(public_skill, dict)
            else None
        )
        return StageAuthoringContextV1(
            workflow_id=fanout.workflow_id,
            session_id=session.session_id,
            session_revision=session.revision,
            stage=session.journey.stage,
            creative_goal=session.goal,
            requirement_facts=requirement_facts,
            internal_skill_ref=(
                "agent/skills/video_agent_storyboard_design/SKILL.md"
                if node_role == "storyboard_grid"
                else "agent/skills/video_agent_video_direction/SKILL.md"
            ),
            style_projection=str(style)[:8192] if style is not None else None,
            video_representation_mode=(
                representation_mode
                if representation_mode in {"illustrated", "illustration_to_live_action"}
                else None
            ),
            video_representation_source_id=(
                f"{snapshot.source_skill_id}:{snapshot.source_skill_version}"
                if snapshot
                and representation_mode in {"illustrated", "illustration_to_live_action"}
                else None
            ),
            working_document_excerpts=excerpts,
        )

    @staticmethod
    def _next_runnable_node_id(
        workflow,
        node_ids: tuple[str, ...],
    ) -> str | None:
        nodes = {node.node_id: node for node in workflow.nodes}
        for node_id in node_ids:
            node = nodes.get(node_id)
            if node is None or node.status != "draft":
                continue
            if node.prompt_preparation.status != "ready":
                continue
            return node.node_id
        return None


def _run_identity(fanout_plan_id: str, node_id: str) -> str:
    return f"storyboard-fanout:{fanout_plan_id}:{node_id}"


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()[:32]
