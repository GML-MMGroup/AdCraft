"""Explicit-only reference resolution for Agent Canvas provider runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasNodeV2,
    ProjectAssetSummaryV2,
    StorageAccessDescriptorV2,
)
from app.schemas.agent_canvas_ad_media import (
    AdMediaRoleContractV2,
    AdReferenceBundleV2,
    ResolvedAdReferenceV2,
)


class AdReferenceBundleResolver:
    """Resolve only persisted bindings attached to the target node."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        *,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2],
        max_references: int = 8,
    ) -> None:
        self._workflows = workflows
        self._asset_resolver = asset_resolver
        self._max_references = max_references

    def resolve(
        self,
        workflow_id: str,
        node_id: str,
        role_contract: AdMediaRoleContractV2,
    ) -> AdReferenceBundleV2:
        workflow = self._workflows.get_workflow(workflow_id)
        nodes = {node.node_id: node for node in workflow.nodes}
        if node_id not in nodes:
            raise _error("node_not_found", "Canvas node was not found.")
        references: list[ResolvedAdReferenceV2] = []
        binding_kinds: dict[str, list[ResolvedAdReferenceV2]] = {}
        for binding in workflow.bindings:
            if binding.target_node_id != node_id:
                continue
            if not binding.enabled:
                continue
            if binding.binding_kind not in {
                "image_reference",
                "video_reference",
                "audio_reference",
            }:
                continue
            if binding.source.kind == "node_output":
                source = nodes.get(binding.source.source_node_id)
                if source is None or source.status != "ready" or not source.output_asset_id:
                    if not binding.required:
                        continue
                    raise _error(
                        "role_reference_bundle_invalid",
                        "Bound source node does not have a Ready media output.",
                    )
                asset_id = source.output_asset_id
                source_node_id = source.node_id
                source_role = source.creative_role
                source_identity_facts = canonical_node_reference_facts(source)
            else:
                asset_id = binding.source.asset_id
                source_node_id = None
                source_role = None
                source_identity_facts = {}
            try:
                asset = self._asset_resolver(asset_id)
            except (KeyError, V2PersistenceError) as error:
                if not binding.required:
                    continue
                raise _error(
                    "role_reference_bundle_invalid",
                    "Bound media asset is unavailable.",
                ) from error
            if asset is None or asset.status != "ready" or asset.media_url is None:
                if not binding.required:
                    continue
                raise _error(
                    "role_reference_bundle_invalid",
                    "Bound media asset is not Ready.",
                )
            if source_role is None:
                source_role = asset.source_semantic_role
            resolved = ResolvedAdReferenceV2(
                binding_id=binding.binding_id,
                source_kind=binding.source.kind,
                source_node_id=source_node_id,
                source_semantic_role=source_role,
                semantic_reference_role=binding.metadata.get("semantic_reference_role"),
                asset_id=asset.asset_id,
                media_type=asset.media_type,
                display_order=binding.display_order,
                source_identity_facts=source_identity_facts,
                access_descriptor=StorageAccessDescriptorV2(
                    asset_id=asset.asset_id,
                    media_url=asset.media_url,
                    checksum=asset.checksum,
                ),
            )
            references.append(resolved)
            binding_kinds.setdefault(binding.binding_kind, []).append(resolved)
        if len(references) > self._max_references:
            raise _error(
                "reference_cardinality_exceeded",
                "Reference bundle exceeds the provider limit.",
            )
        for requirement in role_contract.reference_requirements:
            candidates = [
                item
                for item in binding_kinds.get(requirement.binding_kind, [])
                if requirement.required_role is None
                or item.source_semantic_role == requirement.required_role
            ]
            if len(candidates) < requirement.minimum:
                raise _error(
                    "role_required_reference_missing",
                    "A required explicit role reference is missing.",
                )
            if len(candidates) > requirement.maximum:
                raise _error(
                    "reference_cardinality_exceeded",
                    "Role reference cardinality is invalid.",
                )
        ordered = tuple(sorted(references, key=lambda item: (item.display_order, item.binding_id)))
        digest = hashlib.sha256(
            json.dumps(
                [item.model_dump(mode="json") for item in ordered],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return AdReferenceBundleV2(
            target_node_id=node_id,
            references=ordered,
            bundle_digest=digest,
        )


def canonical_node_reference_facts(node: CanvasNodeV2) -> dict[str, object]:
    """Project bounded typed facts for one explicitly bound source Node."""

    content = node.structured_content
    if node.creative_role in {"product", "prop", "character"}:
        return _selected_text_facts(content, ("subject_identity", "design_summary"))
    if node.creative_role == "scene":
        return _selected_text_facts(
            content,
            (
                "scene_identity",
                "environment_summary",
                "layout",
                "lighting",
                "materials",
                "time_of_day",
            ),
        )
    if node.creative_role == "storyboard_sequence":
        facts = _selected_text_facts(content, ("sequence_summary", "narrative_goal"))
        panels = content.get("panels")
        if isinstance(panels, list):
            facts["panels"] = [
                {
                    key: _bounded_text(panel.get(key))
                    for key in (
                        "panel_index",
                        "beat",
                        "composition",
                        "camera",
                        "subject_action",
                        "continuity_from_previous",
                    )
                    if _bounded_text(panel.get(key))
                }
                for panel in panels[:9]
                if isinstance(panel, dict)
            ]
        return facts
    return {}


def _selected_text_facts(
    content: dict[str, object],
    field_names: tuple[str, ...],
) -> dict[str, object]:
    return {
        field_name: bounded
        for field_name in field_names
        if (bounded := _bounded_text(content.get(field_name)))
    }


def _bounded_text(value: object) -> str:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value).strip()[:2_048]
    return ""


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="ad_reference_bundle_resolver")
