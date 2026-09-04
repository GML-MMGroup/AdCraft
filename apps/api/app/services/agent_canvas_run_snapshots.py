"""Freeze immutable Agent Canvas run intent before execution claims begin."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Protocol

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_runtime_repository import AgentCanvasRuntimeRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    CanvasBindingSourceImageAssetV2,
    CanvasBindingSourceNodeV2,
    CanvasNodeV2,
    ProjectAssetSummaryV2,
)
from app.schemas.agent_canvas import ResolvedNodeInputManifestV2
from app.schemas.agent_canvas_runtime import NodeRunBindingSnapshotV2, NodeRunIntentSnapshotV2
from app.schemas.agent_canvas_runtime_authority import CanvasExecutionMemberIntentV2
from app.services.agent_canvas_execution_parameters import (
    AgentCanvasExecutionParameterResolver,
)
from app.services.agent_canvas_bindings import AgentCanvasBindingService
from app.services.agent_canvas_resolved_inputs import AgentCanvasResolvedInputCompiler
from app.services.agent_canvas_execution_mode import classify_canvas_execution_mode


class BoundAssetVersionResolver(Protocol):
    """Resolve one exact immutable Binding asset for a Workflow."""

    def resolve_bound_asset_version(
        self,
        workflow_id: str,
        asset_id: str,
        version_id: str,
    ) -> ProjectAssetSummaryV2: ...

    def resolve_bound_asset_versions(
        self,
        workflow_id: str,
        pairs: tuple[tuple[str, str], ...],
    ) -> dict[tuple[str, str], ProjectAssetSummaryV2]: ...


class AgentCanvasRunIntentSnapshotService:
    """Persist the accepted Node and Binding identities for each execution member."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        runtime: AgentCanvasRuntimeRepository,
        execution_parameters: AgentCanvasExecutionParameterResolver | None = None,
        *,
        bindings: AgentCanvasBindingService | None = None,
        bound_assets: BoundAssetVersionResolver | None = None,
    ) -> None:
        self._workflows = workflows
        self._runtime = runtime
        self._execution_parameters = execution_parameters or AgentCanvasExecutionParameterResolver()
        self._bindings = bindings
        self._bound_assets = bound_assets or bindings

    def prepare_member_intents(
        self,
        workflow: AgentCanvasWorkflowV2,
        nodes: tuple[CanvasNodeV2, ...],
    ) -> tuple[CanvasExecutionMemberIntentV2, ...]:
        """Build immutable snapshot bodies before the admission transaction."""

        workflow_nodes = {node.node_id: node for node in workflow.nodes}
        binding_snapshots_by_node = {
            node.node_id: _binding_snapshots(workflow, node, workflow_nodes) for node in nodes
        }
        exact_asset_pairs = tuple(
            dict.fromkeys(
                (binding.source_id, binding.source_asset_version_id)
                for snapshots in binding_snapshots_by_node.values()
                for binding in snapshots
                if binding.source_kind == "image_asset"
                and binding.source_asset_version_id is not None
            )
        )
        if exact_asset_pairs and self._bound_assets is None:
            raise V2PersistenceError(
                "run_intent_asset_resolver_unavailable",
                "Run-bound asset resolution is unavailable.",
                stage="agent_canvas_run_snapshots",
            )
        resolved_assets = (
            self._bound_assets.resolve_bound_asset_versions(
                workflow.workflow_id,
                exact_asset_pairs,
            )
            if self._bound_assets is not None and exact_asset_pairs
            else {}
        )
        intents: list[CanvasExecutionMemberIntentV2] = []
        for member_order, node in enumerate(nodes):
            frozen_node, normalizations = self._execution_parameters.freeze_node(node)
            binding_snapshots = binding_snapshots_by_node[node.node_id]
            mode = classify_canvas_execution_mode(
                frozen_node,
                has_usable_reference_only_input=_has_available_media_input(binding_snapshots),
            )
            source_asset_digests: dict[str, str] = {}
            for binding in binding_snapshots:
                if binding.source_kind != "image_asset":
                    continue
                if binding.source_asset_version_id is None:
                    raise V2PersistenceError(
                        "canvas_asset_reference_version_required",
                        "Direct asset bindings require an immutable asset version.",
                        stage="agent_canvas_run_snapshots",
                    )
                asset = resolved_assets.get((binding.source_id, binding.source_asset_version_id))
                if asset is None:
                    raise V2PersistenceError(
                        "asset_version_not_found",
                        "Asset version was not found.",
                        stage="agent_canvas_run_snapshots",
                    )
                source_asset_digests[asset.asset_id] = asset.checksum
            semantic = {
                "workflow_id": workflow.workflow_id,
                "workflow_revision": workflow.revision,
                "node": frozen_node.model_dump(mode="json"),
                "bindings": [item.model_dump(mode="json") for item in binding_snapshots],
                "source_asset_digests": source_asset_digests,
            }
            digest = _digest(semantic)
            intents.append(
                CanvasExecutionMemberIntentV2(
                    node_id=frozen_node.node_id,
                    node_revision=frozen_node.revision,
                    member_order=member_order,
                    frozen_node=frozen_node.model_dump(mode="json"),
                    binding_snapshots=binding_snapshots,
                    snapshot_id=f"run_intent_{digest[:24]}",
                    snapshot_digest=digest,
                    expected_source_asset_digests=source_asset_digests,
                    parameter_normalizations=tuple(str(item) for item in normalizations),
                    execution_mode=mode.execution_mode,
                    semantic_extraction=mode.semantic_extraction,
                )
            )
        return tuple(intents)

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
            frozen_node, normalizations = self._execution_parameters.freeze_node(node)
            if self._bindings is not None:
                self._bindings.capture_prompt_context_snapshot(
                    member.workflow_id,
                    frozen_node.node_id,
                    node_run_id=f"node_run_{execution_id}_{frozen_node.node_id}",
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
                    source_kind=binding.source.kind,
                    source_id=(
                        binding.source.source_node_id
                        if isinstance(binding.source, CanvasBindingSourceNodeV2)
                        else binding.source.source_asset_id
                    ),
                    source_asset_id=(
                        binding.source.source_asset_id
                        if isinstance(binding.source, CanvasBindingSourceImageAssetV2)
                        else next(
                            (
                                source.output_asset_id
                                for source in workflow.nodes
                                if source.node_id == binding.source.source_node_id
                            ),
                            None,
                        )
                    ),
                    source_asset_version_id=(
                        binding.source.source_asset_version_id
                        if isinstance(binding.source, CanvasBindingSourceImageAssetV2)
                        else next(
                            (
                                source.output_asset_version_id
                                for source in workflow.nodes
                                if source.node_id == binding.source.source_node_id
                            ),
                            None,
                        )
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
                    source_semantic_role=(
                        next(
                            (
                                source.semantic_role
                                for source in workflow.nodes
                                if source.node_id == binding.source.source_node_id
                            ),
                            None,
                        )
                        if isinstance(binding.source, CanvasBindingSourceNodeV2)
                        else None
                    ),
                    binding_metadata=binding.metadata,
                    source_structured_content=(
                        next(
                            (
                                source.structured_content
                                for source in workflow.nodes
                                if source.node_id == binding.source.source_node_id
                            ),
                            {},
                        )
                        if isinstance(binding.source, CanvasBindingSourceNodeV2)
                        else {}
                    ),
                )
                for binding in bindings
            )
            structured_content_digest = _digest(frozen_node.structured_content)
            mode = classify_canvas_execution_mode(
                frozen_node,
                has_usable_reference_only_input=_has_available_media_input(binding_snapshots),
            )
            identity = {
                "workflow_id": frozen_node.workflow_id,
                "execution_id": execution_id,
                "member_id": member.member_id,
                "node_id": frozen_node.node_id,
                "node_revision": frozen_node.revision,
                "node_type": frozen_node.node_type,
                "creative_role": frozen_node.creative_role,
                "role_contract_version": frozen_node.role_contract_version,
                "summary_prompt": frozen_node.summary_prompt,
                "generation_prompt": frozen_node.generation_prompt,
                "prompt_presentation": (
                    frozen_node.prompt_presentation.model_dump(mode="json")
                    if frozen_node.prompt_presentation is not None
                    else None
                ),
                "structured_content_digest": structured_content_digest,
                "model_selection_mode": frozen_node.model_selection_mode,
                "model_ref": frozen_node.model_ref,
                "requested_parameters": frozen_node.parameters,
                "binding_snapshots": [item.model_dump(mode="json") for item in binding_snapshots],
                "execution_mode": mode.execution_mode,
                "semantic_extraction": mode.semantic_extraction,
            }
            snapshot = NodeRunIntentSnapshotV2(
                snapshot_id=f"run_intent_{_digest(identity)[:24]}",
                snapshot_digest=_digest(identity),
                created_at=now,
                **identity,
            )
            self._runtime.update_member(
                execution_id,
                frozen_node.node_id,
                state=member.state,
                phase=member.phase,
                provider_task_id=member.provider_task_id,
                waiting_for_node_ids=member.waiting_for_node_ids,
                now=now,
                prompt_metadata={
                    **member.prompt_metadata,
                    "frozen_node": frozen_node.model_dump(mode="json"),
                    **(
                        {"execution_parameter_normalizations": list(normalizations)}
                        if normalizations
                        else {}
                    ),
                },
                run_intent_snapshot=snapshot,
                event_type="run_intent_frozen",
                event_payload={
                    "run_intent_snapshot_id": snapshot.snapshot_id,
                    "node_id": frozen_node.node_id,
                    "node_revision": frozen_node.revision,
                    "binding_ids": [item.binding_id for item in binding_snapshots],
                },
            )
            frozen.append(frozen_node)
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

    def refresh_member_intent(
        self,
        execution_id: str,
        node_id: str,
        *,
        now: datetime,
    ) -> NodeRunIntentSnapshotV2:
        """Replace a queued member snapshot after a dependency wave changes.

        A run intent is immutable while its member is being dispatched.  Once
        an upstream terminal publication advances a dependency, a queued
        downstream member must receive a new snapshot before it can be claimed
        again; retaining the old frozen Node or binding revisions would admit
        stale prompt/reference evidence.
        """

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
        workflow = self._workflows.get_workflow(member.workflow_id)
        node = next((item for item in workflow.nodes if item.node_id == node_id), None)
        if node is None:
            raise V2PersistenceError(
                "node_not_found",
                "Execution member references a missing Node.",
                stage="agent_canvas_run_snapshots",
            )
        intent = self.prepare_member_intents(workflow, (node,))[0]
        frozen = intent.frozen_node
        snapshot = NodeRunIntentSnapshotV2(
            snapshot_id=f"run_intent_{intent.snapshot_digest[:24]}",
            workflow_id=workflow.workflow_id,
            execution_id=execution_id,
            member_id=member.member_id,
            node_id=node_id,
            node_revision=intent.node_revision,
            node_type=node.node_type,
            creative_role=node.creative_role,
            role_contract_version=node.role_contract_version,
            summary_prompt=node.summary_prompt,
            generation_prompt=node.generation_prompt,
            prompt_presentation=node.prompt_presentation,
            structured_content_digest=_digest(node.structured_content),
            model_selection_mode=node.model_selection_mode,
            model_ref=node.model_ref,
            requested_parameters=node.parameters,
            binding_snapshots=intent.binding_snapshots,
            snapshot_digest=intent.snapshot_digest,
            created_at=now,
            execution_mode=intent.execution_mode,
            semantic_extraction=intent.semantic_extraction,
        )
        self._runtime.update_member(
            execution_id,
            node_id,
            state=member.state,
            phase=member.phase,
            waiting_for_node_ids=member.waiting_for_node_ids,
            now=now,
            prompt_metadata={
                **member.prompt_metadata,
                "frozen_node": frozen,
                "run_intent_refresh_reason": "dependency_wave_changed",
            },
            run_intent_snapshot=snapshot,
            event_type="execution_member_intent_refreshed",
            event_payload={
                "node_id": node_id,
                "node_revision": node.revision,
                "run_intent_snapshot_id": snapshot.snapshot_id,
                "binding_ids": [item.binding_id for item in intent.binding_snapshots],
            },
        )
        return snapshot


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _has_available_media_input(bindings: tuple[NodeRunBindingSnapshotV2, ...]) -> bool:
    return any(
        binding.input_role in {"image_reference", "video_reference", "audio_reference"}
        and binding.source_asset_version_id is not None
        for binding in bindings
    )


def _binding_snapshots(
    workflow: AgentCanvasWorkflowV2,
    node: CanvasNodeV2,
    workflow_nodes: dict[str, CanvasNodeV2],
) -> tuple[NodeRunBindingSnapshotV2, ...]:
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
    return tuple(
        NodeRunBindingSnapshotV2(
            binding_id=binding.binding_id,
            input_role=binding.input_role,
            order=binding.order,
            source_kind=binding.source.kind,
            source_id=(
                binding.source.source_node_id
                if isinstance(binding.source, CanvasBindingSourceNodeV2)
                else binding.source.source_asset_id
            ),
            source_asset_id=(
                binding.source.source_asset_id
                if isinstance(binding.source, CanvasBindingSourceImageAssetV2)
                else (
                    workflow_nodes[binding.source.source_node_id].output_asset_id
                    if binding.source.source_node_id in workflow_nodes
                    else None
                )
            ),
            source_asset_version_id=(
                binding.source.source_asset_version_id
                if isinstance(binding.source, CanvasBindingSourceImageAssetV2)
                else (
                    workflow_nodes[binding.source.source_node_id].output_asset_version_id
                    if binding.source.source_node_id in workflow_nodes
                    else None
                )
            ),
            source_node_revision=(
                workflow_nodes[binding.source.source_node_id].revision
                if isinstance(binding.source, CanvasBindingSourceNodeV2)
                and binding.source.source_node_id in workflow_nodes
                else None
            ),
            source_semantic_role=(
                workflow_nodes[binding.source.source_node_id].semantic_role
                if isinstance(binding.source, CanvasBindingSourceNodeV2)
                and binding.source.source_node_id in workflow_nodes
                else None
            ),
            binding_metadata=binding.metadata,
            source_structured_content=(
                workflow_nodes[binding.source.source_node_id].structured_content
                if isinstance(binding.source, CanvasBindingSourceNodeV2)
                and binding.source.source_node_id in workflow_nodes
                else {}
            ),
        )
        for binding in bindings
        if isinstance(
            binding.source,
            (CanvasBindingSourceNodeV2, CanvasBindingSourceImageAssetV2),
        )
    )
