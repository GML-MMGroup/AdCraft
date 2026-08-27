"""Isolated deterministic preparation for one visible Agent Canvas Draft."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2, ProjectAssetSummaryV2
from app.schemas.agent_canvas_errors import CanvasNodeErrorV2
from app.schemas.agent_canvas_progressive_authoring import StageAuthoringContextV1
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.schemas.agent_canvas_prompt_assertion import safe_prompt_assertion_metadata
from app.schemas.agent_canvas_role_prompt_preparation import (
    RoleBindingSnapshotV2,
    RoleBoundTextControlV2,
    RoleCreativeBriefV2,
    RolePromptPreparationContextV2,
)
from app.services.agent_canvas_role_prompt_compiler import AgentCanvasRolePromptCompiler
from app.services.agent_canvas_role_prompt_authoring import deterministic_role_brief
from app.services.agent_canvas_role_prompt_context import (
    ROLE_PARAMETER_CONTROL_NAMES,
    RolePromptContextProjector,
    RolePromptParameterResolver,
)
from app.services.agent_canvas_role_prompt_recipes import RolePromptRecipeRegistry
from app.services.agent_canvas_authoring_validation import require_node_runnable
from app.services.agent_trace import V2AgentTraceWriter


RoleBriefAuthor = Callable[[RolePromptPreparationContextV2, str], RoleCreativeBriefV2]
_GUIDED_REVIEW_ROLES = frozenset({"storyboard_sequence", "storyboard_video", "bgm"})


class NodePromptPreparationService:
    """Prepare one Draft without invoking media execution or copying sibling prompts."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        *,
        role_brief_author: RoleBriefAuthor | None = None,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
    ) -> None:
        self._workflows = workflows
        self._role_brief_author = role_brief_author
        self._asset_resolver = asset_resolver
        self._projector = RolePromptContextProjector()
        self._recipes = RolePromptRecipeRegistry()
        self._parameter_resolver = RolePromptParameterResolver()
        self._compiler = AgentCanvasRolePromptCompiler(self._recipes)

    def prepare(
        self,
        workflow_id: str,
        node_id: str,
        *,
        operation_id: str,
        context: StageAuthoringContextV1,
    ) -> CanvasNodeV2:
        started_at = _now()
        started_monotonic = monotonic()
        current = self._workflows.get_node(workflow_id, node_id)
        require_node_runnable(current)
        if (
            current.prompt_preparation.status == "ready"
            and current.prompt_preparation.operation_id == operation_id
        ):
            return current
        snapshot_digest = context_digest(context)
        working = self._transition(
            current,
            NodePromptPreparationV1(
                status="working",
                operation_id=operation_id,
                attempt_no=current.prompt_preparation.attempt_no + 1,
                context_snapshot_id=snapshot_digest,
                occurrence_id=(
                    str(current.metadata["occurrence_id"])
                    if current.metadata.get("occurrence_id")
                    else None
                ),
                character_phase=current.metadata.get("character_phase"),
                updated_at=_now(),
            ),
        )
        role_context: RolePromptPreparationContextV2 | None = None
        try:
            role_context = self._project_context(working, context)
            if self._role_brief_author is not None:
                brief = self._role_brief_author(role_context, operation_id)
                compiled_prompt = self._compiler.compile(
                    brief,
                    role_context,
                    parameters=self._parameter_resolver.resolve(
                        role_context,
                        self._recipes.resolve(role_context.role_variant),
                    ),
                )
                prompt = compiled_prompt.prompt
                structured_content = compiled_prompt.structured_content
            else:
                compiled_prompt = self._compiler.compile(
                    deterministic_role_brief(role_context),
                    role_context,
                    parameters=self._parameter_resolver.resolve(
                        role_context,
                        self._recipes.resolve(role_context.role_variant),
                    ),
                )
                prompt = compiled_prompt.prompt
                structured_content = compiled_prompt.structured_content
            if role_context.role_variant == "world_view":
                provenance = dict(structured_content.get("authoring_provenance", {}))
                provenance.update(
                    {
                        "source_proposal_id": str(
                            working.parameters.get("source_proposal_id")
                            or provenance.get("source_proposal_id")
                        ),
                        "source_option_id": str(
                            working.parameters.get("source_option_id")
                            or provenance.get("source_option_id")
                        ),
                    }
                )
                structured_content = {
                    **structured_content,
                    "authoring_provenance": provenance,
                }
            digest = sha256(prompt.encode("utf-8")).hexdigest()
            recipe = self._recipes.resolve(role_context.role_variant)
            ready = working.model_copy(
                update={
                    "generation_prompt": prompt,
                    "structured_content": structured_content,
                    "status": "ready" if working.node_type == "text" else working.status,
                    "metadata": {
                        **working.metadata,
                        **(
                            {"guided_review_node_revision": working.revision + 1}
                            if working.creative_role in _GUIDED_REVIEW_ROLES
                            else {}
                        ),
                        "prompt_context_digest": snapshot_digest,
                        "prompt_digest": digest,
                        "prompt_recipe_id": recipe.recipe_id,
                        "prompt_recipe_version": recipe.recipe_version,
                        "prompt_recipe_digest": recipe.recipe_digest,
                        "prompt_reference_bundle_digest": (compiled_prompt.reference_bundle_digest),
                        "role_reference_policy_version": (
                            compiled_prompt.role_reference_policy_version
                        ),
                        "prompt_style_projection_digest": (compiled_prompt.style_projection_digest),
                        "prompt_assertion_policy_ref": (
                            compiled_prompt.assertion_evidence.policy_ref
                        ),
                        "prompt_assertion_policy_digest": (
                            compiled_prompt.assertion_evidence.policy_digest
                        ),
                        "prompt_assertion_evidence_digest": (
                            compiled_prompt.assertion_evidence.evidence_digest
                        ),
                        "prepared_reference_snapshots": [
                            item.model_dump(mode="json") for item in role_context.bindings
                        ],
                        **(
                            {
                                "prompt_occurrence_id": role_context.occurrence_id,
                                "prompt_character_phase": role_context.character_phase,
                                "prompt_requirement_revision_id": (
                                    role_context.requirement_revision_id
                                ),
                                "prompt_requirement_revision_no": (
                                    role_context.requirement_revision_no
                                ),
                            }
                            if role_context.occurrence_id is not None
                            else {}
                        ),
                    },
                    "revision": working.revision + 1,
                    "updated_at": _now(),
                    "prompt_preparation": NodePromptPreparationV1(
                        status="ready",
                        operation_id=operation_id,
                        attempt_no=working.prompt_preparation.attempt_no,
                        context_snapshot_id=snapshot_digest,
                        prompt_digest=digest,
                        role_variant=role_context.role_variant,
                        recipe_id=recipe.recipe_id,
                        recipe_version=recipe.recipe_version,
                        recipe_digest=recipe.recipe_digest,
                        requirement_revision_id=role_context.requirement_revision_id,
                        requirement_revision_no=role_context.requirement_revision_no,
                        occurrence_id=role_context.occurrence_id,
                        character_phase=role_context.character_phase,
                        document_revisions=role_context.document_revisions,
                        binding_digest=compiled_prompt.reference_bundle_digest,
                        style_projection_digest=compiled_prompt.style_projection_digest,
                        brief_digest=compiled_prompt.brief_digest,
                        parameter_origins=compiled_prompt.parameters,
                        assertion_evidence=compiled_prompt.assertion_evidence,
                        attempt_stage="completed",
                        updated_at=_now(),
                    ),
                }
            )
            persisted = self._persist(working, ready)
            self._append_trace(
                persisted,
                prompt=prompt,
                output=structured_content,
                error=None,
                started_at=started_at,
                duration_ms=round((monotonic() - started_monotonic) * 1000),
            )
            return persisted
        except Exception as error:
            error_code = (
                error.code if isinstance(error, V2PersistenceError) else "prompt_preparation_failed"
            )
            failed_recipe = (
                self._recipes.resolve(role_context.role_variant)
                if role_context is not None
                else None
            )
            failed = working.model_copy(
                update={
                    "revision": working.revision + 1,
                    "updated_at": _now(),
                    "prompt_preparation": NodePromptPreparationV1(
                        status="failed",
                        operation_id=operation_id,
                        attempt_no=working.prompt_preparation.attempt_no,
                        context_snapshot_id=snapshot_digest,
                        occurrence_id=working.prompt_preparation.occurrence_id,
                        character_phase=working.prompt_preparation.character_phase,
                        role_variant=(role_context.role_variant if role_context else None),
                        recipe_id=(failed_recipe.recipe_id if failed_recipe else None),
                        recipe_version=(failed_recipe.recipe_version if failed_recipe else None),
                        recipe_digest=(failed_recipe.recipe_digest if failed_recipe else None),
                        requirement_revision_id=(
                            role_context.requirement_revision_id if role_context else None
                        ),
                        requirement_revision_no=(
                            role_context.requirement_revision_no if role_context else None
                        ),
                        document_revisions=(
                            role_context.document_revisions if role_context else {}
                        ),
                        binding_digest=(
                            _role_binding_digest(role_context.bindings)
                            if role_context is not None
                            else None
                        ),
                        error=CanvasNodeErrorV2(
                            code=error_code,
                            message="Node prompt preparation failed.",
                            retryable=not isinstance(error, V2PersistenceError),
                        ),
                        attempt_stage="failed",
                        updated_at=_now(),
                    ),
                }
            )
            persisted = self._persist(working, failed)
            self._append_trace(
                persisted,
                prompt=current.summary_prompt or current.generation_prompt or "",
                output=None,
                error=error_code,
                started_at=started_at,
                duration_ms=round((monotonic() - started_monotonic) * 1000),
            )
            raise error

    def invalidate_for_dependency_change(
        self,
        workflow_id: str,
        node_id: str,
        *,
        operation_id: str,
    ) -> CanvasNodeV2:
        """Invalidate one prepared Draft without changing its operation identity."""

        current = self._workflows.get_node(workflow_id, node_id)
        if current.prompt_preparation.operation_id != operation_id:
            raise V2PersistenceError(
                "node_prompt_preparation_conflict",
                "Prompt preparation operation identity changed before invalidation.",
                stage="node_prompt_preparation",
            )
        if current.prompt_preparation.status != "ready":
            return current
        return self._transition(
            current,
            current.prompt_preparation.model_copy(
                update={
                    "status": "queued",
                    "error": None,
                    "attempt_stage": "queued",
                    "updated_at": _now(),
                }
            ),
        )

    def _append_trace(
        self,
        node: CanvasNodeV2,
        *,
        prompt: str,
        output: object,
        error: str | None,
        started_at: datetime,
        duration_ms: int,
    ) -> None:
        database_path = self._workflows.database.engine.url.database
        if database_path is None:
            return
        preparation = node.prompt_preparation
        V2AgentTraceWriter(Path(database_path).parent.parent, node.workflow_id).append(
            agent="video_agent_role_prompt_authoring",
            model=node.model_ref,
            prompt=prompt,
            output=output,
            error=error,
            started_at=started_at,
            finished_at=_now(),
            duration_ms=duration_ms,
            metadata={
                "trace_role": "node_prompt_preparation",
                "node_id": node.node_id,
                "node_revision": node.revision,
                "creative_role": node.creative_role,
                "operation_id": preparation.operation_id,
                "attempt_no": preparation.attempt_no,
                "attempt_stage": preparation.attempt_stage,
                "occurrence_id": preparation.occurrence_id,
                "character_phase": preparation.character_phase,
                "recipe_id": preparation.recipe_id,
                "recipe_version": preparation.recipe_version,
                "recipe_digest": preparation.recipe_digest,
                "requirement_revision_id": preparation.requirement_revision_id,
                "requirement_revision_no": preparation.requirement_revision_no,
                "document_revisions": preparation.document_revisions,
                "binding_digest": preparation.binding_digest,
                "style_projection_digest": preparation.style_projection_digest,
                "brief_digest": preparation.brief_digest,
                "prompt_digest": preparation.prompt_digest,
                "parameter_origins": [
                    item.model_dump(mode="json") for item in preparation.parameter_origins
                ],
                **(
                    safe_prompt_assertion_metadata(preparation.assertion_evidence)
                    if preparation.assertion_evidence is not None
                    else {}
                ),
                "error_code": error,
            },
        )

    def _project_context(
        self,
        node: CanvasNodeV2,
        context: StageAuthoringContextV1,
    ) -> RolePromptPreparationContextV2:
        is_character = node.creative_role == "character"
        requirement_revision_id = (
            str(node.metadata.get("requirement_revision_id"))
            if is_character and node.metadata.get("requirement_revision_id")
            else f"requirements:{context.session_id}:{context.session_revision}"
        )
        requirement_revision_no = (
            int(node.metadata["requirement_revision_no"])
            if is_character and isinstance(node.metadata.get("requirement_revision_no"), int)
            else context.session_revision
        )
        bindings = self._binding_snapshots(node)
        controls = {
            key: value
            for key, value in context.requirement_facts.items()
            if key
            in {
                "aspect_ratio",
                "audio_mode",
                "duration_seconds",
                "output_resolution",
                "resolution",
                "size",
            }
        }
        return self._projector.project(
            node,
            context,
            requirement_revision_id=requirement_revision_id,
            requirement_revision_no=requirement_revision_no,
            document_revisions={
                item.document_kind: item.revision for item in context.working_document_excerpts
            },
            bindings=bindings,
            model_policy_revision=(
                node.model_summary.catalog_revision if node.model_summary else 1
            ),
            explicit_controls=controls,
            bound_text_controls=self._bound_text_controls(node),
            storyboard_parameters={
                "sequence_id": node.metadata.get("source_sequence_id"),
                "storyboard_production_plan_id": node.metadata.get("source_agent_document_id"),
            }
            if node.metadata.get("source_sequence_id")
            else {},
            world_view_projection=self._world_view_projection(node),
        )

    def _world_view_projection(self, node: CanvasNodeV2) -> str | None:
        workflow = self._workflows.get_workflow(node.workflow_id)
        nodes = {item.node_id: item for item in workflow.nodes}
        projections: list[str] = []
        for binding in workflow.bindings:
            if (
                binding.target_node_id != node.node_id
                or not binding.enabled
                or binding.source.kind != "node_output"
            ):
                continue
            source = nodes.get(binding.source.source_node_id)
            if source is None or source.creative_role != "world_setting":
                continue
            content = source.structured_content.get("content")
            projection = content if isinstance(content, str) else source.generation_prompt
            if projection:
                projections.append(projection)
        if len(projections) > 1:
            raise V2PersistenceError(
                "node_prompt_context_stale",
                "Prompt context contains ambiguous WorldView authority.",
                stage="node_prompt_preparation",
            )
        return projections[0] if projections else None

    def _bound_text_controls(
        self,
        node: CanvasNodeV2,
    ) -> tuple[RoleBoundTextControlV2, ...]:
        workflow = self._workflows.get_workflow(node.workflow_id)
        nodes = {item.node_id: item for item in workflow.nodes}
        resolved: dict[str, RoleBoundTextControlV2] = {}
        for binding in sorted(
            workflow.bindings,
            key=lambda item: (item.order, item.binding_id),
        ):
            if (
                binding.target_node_id != node.node_id
                or not binding.enabled
                or binding.input_role != "text_context"
                or binding.source.kind != "node_output"
            ):
                continue
            source = nodes.get(binding.source.source_node_id)
            if source is None or source.node_type not in {"text", "script"}:
                continue
            for name, value in _structured_parameter_controls(source.structured_content).items():
                candidate = RoleBoundTextControlV2(
                    name=name,
                    value=value,
                    binding_id=binding.binding_id,
                    source_node_id=source.node_id,
                    source_node_revision=source.revision,
                )
                existing = resolved.get(name)
                if existing is not None and existing.value != candidate.value:
                    raise V2PersistenceError(
                        "node_prompt_parameter_conflict",
                        "Bound Text controls contain conflicting canonical values.",
                        stage="node_prompt_preparation",
                    )
                resolved.setdefault(name, candidate)
        return tuple(resolved[name] for name in sorted(resolved))

    def _binding_snapshots(self, node: CanvasNodeV2) -> tuple[RoleBindingSnapshotV2, ...]:
        workflow = self._workflows.get_workflow(node.workflow_id)
        nodes = {item.node_id: item for item in workflow.nodes}
        snapshots: list[RoleBindingSnapshotV2] = []
        for binding in workflow.bindings:
            if binding.target_node_id != node.node_id or not binding.enabled:
                continue
            source_node_id = getattr(binding.source, "source_node_id", None)
            source_node = nodes.get(source_node_id) if source_node_id else None
            if (
                node.creative_role == "storyboard_video"
                and source_node is not None
                and source_node.creative_role == "character"
            ):
                if (
                    binding.metadata.get("explicit_occurrence_mapping") is not True
                    or binding.metadata.get("occurrence_id")
                    != source_node.metadata.get("occurrence_id")
                    or binding.metadata.get("character_phase") != "turnaround"
                    or source_node.metadata.get("character_phase") != "turnaround"
                ):
                    raise V2PersistenceError(
                        "character_reference_mapping_invalid",
                        "Video Character Binding provenance is ambiguous or stale.",
                        stage="node_prompt_preparation",
                    )
            asset_id = (
                source_node.output_asset_id
                if source_node is not None
                else getattr(binding.source, "source_asset_id", None)
            )
            version_id = None
            if asset_id and self._asset_resolver is not None:
                asset = self._asset_resolver(asset_id)
                version_id = asset.version_id
            snapshots.append(
                RoleBindingSnapshotV2(
                    binding_id=binding.binding_id,
                    binding_revision=int(binding.metadata.get("revision") or 1),
                    source_node_id=source_node_id,
                    source_node_revision=source_node.revision if source_node is not None else None,
                    source_role=(source_node.creative_role if source_node is not None else None),
                    asset_id=asset_id,
                    asset_version_id=version_id,
                    reference_purpose=_reference_purpose(node, source_node),
                    occurrence_id=(
                        str(source_node.metadata["occurrence_id"])
                        if source_node is not None
                        and source_node.creative_role == "character"
                        and source_node.metadata.get("occurrence_id")
                        else None
                    ),
                    character_phase=(
                        source_node.metadata.get("character_phase")
                        if source_node is not None and source_node.creative_role == "character"
                        else None
                    ),
                    requirement_revision_id=(
                        str(source_node.metadata["requirement_revision_id"])
                        if source_node is not None
                        and source_node.creative_role == "character"
                        and source_node.metadata.get("requirement_revision_id")
                        else None
                    ),
                    requirement_revision_no=(
                        int(source_node.metadata["requirement_revision_no"])
                        if source_node is not None
                        and source_node.creative_role == "character"
                        and isinstance(source_node.metadata.get("requirement_revision_no"), int)
                        else None
                    ),
                    source_sequence_id=(
                        str(source_node.metadata["source_sequence_id"])
                        if source_node is not None
                        and source_node.metadata.get("source_sequence_id")
                        else None
                    ),
                    display_order=binding.order,
                )
            )
        return tuple(sorted(snapshots, key=lambda item: (item.display_order, item.binding_id)))

    def _transition(
        self,
        current: CanvasNodeV2,
        preparation: NodePromptPreparationV1,
    ) -> CanvasNodeV2:
        next_node = current.model_copy(
            update={
                "revision": current.revision + 1,
                "updated_at": _now(),
                "prompt_preparation": preparation,
            }
        )
        return self._persist(current, next_node)

    def _persist(self, current: CanvasNodeV2, next_node: CanvasNodeV2) -> CanvasNodeV2:
        workflow = self._workflows.get_workflow(current.workflow_id)
        return self._workflows.update_node_prompt_preparation(
            next_node,
            expected_node_revision=current.revision,
            expected_workflow_revision=workflow.revision,
        )


def context_digest(context: StageAuthoringContextV1) -> str:
    payload = json.dumps(
        context.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _role_binding_digest(bindings: tuple[RoleBindingSnapshotV2, ...]) -> str:
    payload = json.dumps(
        [item.model_dump(mode="json") for item in bindings],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"sha256:{sha256(payload.encode('utf-8')).hexdigest()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _reference_purpose(
    target: CanvasNodeV2,
    source: CanvasNodeV2 | None,
) -> str:
    if (
        target.creative_role == "product"
        and target.structured_content.get("asset_kind") == "multi_view"
        and source is not None
        and source.creative_role == "product"
        and source.structured_content.get("asset_kind") == "main"
    ):
        return "product_main_identity"
    if (
        target.creative_role == "character"
        and target.structured_content.get("character_asset_kind") == "turnaround"
        and source is not None
        and source.creative_role == "character"
        and source.structured_content.get("character_asset_kind") == "identity_master"
    ):
        return "character_main_identity"
    if target.creative_role == "storyboard_video" and (
        source is not None and source.creative_role == "storyboard_sequence"
    ):
        return "storyboard_grid"
    if target.creative_role == "storyboard_sequence" and (
        source is not None and source.creative_role == "storyboard_sequence"
    ):
        return "storyboard_grid_anchor"
    return "identity_reference"


def _structured_parameter_controls(
    content: dict[str, object],
) -> dict[str, object]:
    candidates: list[dict[str, object]] = [content]
    for container_name in (
        "controls",
        "required_video_parameters",
        "required_image_parameters",
        "bgm_parameters",
    ):
        container = content.get(container_name)
        if isinstance(container, dict):
            candidates.append(container)
    return {
        name: value
        for candidate in candidates
        for name, value in candidate.items()
        if name in ROLE_PARAMETER_CONTROL_NAMES
        and value is not None
        and isinstance(value, (str, int, float, bool))
    }
