"""Freeze immutable Agent Canvas run intent before execution claims begin."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_runtime_repository import AgentCanvasRuntimeRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasBindingSourceNodeV2, CanvasNodeV2
from app.schemas.agent_canvas import ResolvedNodeInputManifestV2
from app.schemas.agent_canvas_runtime import NodeRunBindingSnapshotV2, NodeRunIntentSnapshotV2
from app.services.agent_canvas_resolved_inputs import AgentCanvasResolvedInputCompiler


class AgentCanvasRunIntentSnapshotService:
    """Persist the accepted Node and Binding identities for each execution member."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        runtime: AgentCanvasRuntimeRepository,
    ) -> None:
        self._workflows = workflows
        self._runtime = runtime

    def freeze_members(
        self,
        execution_id: str,
        *,
        now: datetime,
        node_ids: tuple[str, ...] | None = None,
    ) -> tuple[CanvasNodeV2, ...]:
        """Freeze queued members once; later authoring edits cannot alter the run."""

        members = self._runtime.list_members(execution_id)
        selected_ids = set(node_ids) if node_ids is not None else None
        frozen: list[CanvasNodeV2] = []
        for member in members:
            if selected_ids is not None and member.node_id not in selected_ids:
                continue
            if member.run_intent_snapshot is not None:
                frozen_node = member.prompt_metadata.get("frozen_node")
                if isinstance(frozen_node, dict):
                    frozen.append(CanvasNodeV2.model_validate(frozen_node))
                continue
            workflow = self._workflows.get_workflow(member.workflow_id)
            node = next((item for item in workflow.nodes if item.node_id == member.node_id), None)
            if node is None:
                raise V2PersistenceError(
                    "node_not_found",
                    "Execution member references a missing Node.",
                    stage="agent_canvas_run_snapshots",
                )
            bindings = tuple(
                sorted(
                    (
                        item
                        for item in workflow.bindings
                        if item.target_node_id == node.node_id and item.enabled
                    ),
                    key=lambda item: (item.order, item.binding_id),
                )
            )
            binding_snapshots = tuple(
                NodeRunBindingSnapshotV2(
                    binding_id=binding.binding_id,
                    input_role=binding.input_role,
                    order=binding.order,
                    required=binding.required,
                    source_kind=binding.source.kind,
                    source_id=(
                        binding.source.source_node_id
                        if isinstance(binding.source, CanvasBindingSourceNodeV2)
                        else binding.source.source_asset_id
                    ),
                    source_node_revision=(
                        next(
                            (
                                source.revision
                                for source in workflow.nodes
                                if source.node_id == binding.source.source_node_id
                            ),
                            None,
                        )
                        if isinstance(binding.source, CanvasBindingSourceNodeV2)
                        else None
                    ),
                )
                for binding in bindings
            )
            structured_content_digest = _digest(node.structured_content)
            identity = {
                "workflow_id": node.workflow_id,
                "execution_id": execution_id,
                "member_id": member.member_id,
                "node_id": node.node_id,
                "node_revision": node.revision,
                "node_type": node.node_type,
                "creative_role": node.creative_role,
                "role_contract_version": node.role_contract_version,
                "summary_prompt": node.summary_prompt,
                "generation_prompt": node.generation_prompt,
                "structured_content_digest": structured_content_digest,
                "model_selection_mode": node.model_selection_mode,
                "model_ref": node.model_ref,
                "requested_parameters": node.parameters,
                "binding_snapshots": [item.model_dump(mode="json") for item in binding_snapshots],
            }
            snapshot = NodeRunIntentSnapshotV2(
                snapshot_id=f"run_intent_{_digest(identity)[:24]}",
                snapshot_digest=_digest(identity),
                created_at=now,
                **identity,
            )
            self._runtime.update_member(
                execution_id,
                node.node_id,
                state=member.state,
                phase=member.phase,
                provider_task_id=member.provider_task_id,
                waiting_for_node_ids=member.waiting_for_node_ids,
                now=now,
                prompt_metadata={
                    **member.prompt_metadata,
                    "frozen_node": node.model_dump(mode="json"),
                },
                run_intent_snapshot=snapshot,
                event_type="run_intent_frozen",
                event_payload={
                    "run_intent_snapshot_id": snapshot.snapshot_id,
                    "node_id": node.node_id,
                    "node_revision": node.revision,
                    "binding_ids": [item.binding_id for item in binding_snapshots],
                },
            )
            frozen.append(node)
        return tuple(frozen)

    def resolve_inputs(
        self,
        execution_id: str,
        node_id: str,
        *,
        compiler: AgentCanvasResolvedInputCompiler,
    ) -> ResolvedNodeInputManifestV2:
        """Resolve one member exclusively from its immutable intent snapshot."""

        member = next(
            (item for item in self._runtime.list_members(execution_id) if item.node_id == node_id),
            None,
        )
        if member is None:
            raise V2PersistenceError(
                "execution_member_not_found",
                "Execution member was not found.",
                stage="agent_canvas_run_snapshots",
            )
        if member.run_intent_snapshot is None:
            raise V2PersistenceError(
                "run_intent_snapshot_not_found",
                "Execution member has no frozen run intent.",
                stage="agent_canvas_run_snapshots",
            )
        return compiler.compile(
            workflow_id=member.workflow_id,
            target_node_id=node_id,
            execution_id=execution_id,
            node_run_id=f"node_run_{execution_id}_{node_id}",
            run_intent_snapshot_id=member.run_intent_snapshot.snapshot_id,
            binding_snapshots=member.run_intent_snapshot.binding_snapshots,
        )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
