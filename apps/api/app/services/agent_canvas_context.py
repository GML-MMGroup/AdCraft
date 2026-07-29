"""Bounded local context assembly for Agent Canvas Director turns."""

from __future__ import annotations

import json
from collections.abc import Callable

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import ProjectAssetSummaryV2
from app.schemas.agent_operation_contexts import (
    DirectorTurnContextV2,
    InteractionMessageSummary,
)


class AgentLocalContextAssembler:
    """Build local mention context without exposing the complete canvas."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        *,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2],
        recent_message_limit: int = 16,
    ) -> None:
        self._workflows = workflows
        self._asset_resolver = asset_resolver
        self._recent_message_limit = recent_message_limit

    def assemble_director_turn(
        self,
        workflow_id: str,
        *,
        conversation_id: str,
        user_input: str,
        mentioned_node_ids: tuple[str, ...] = (),
        mentioned_image_asset_ids: tuple[str, ...] = (),
        recent_messages: tuple[InteractionMessageSummary, ...] = (),
        video_skill_excerpt: str = "",
    ) -> DirectorTurnContextV2:
        workflow = self._workflows.get_workflow(workflow_id)
        nodes = {node.node_id: node for node in workflow.nodes}
        summaries: list[str] = []
        script_summaries: list[str] = []

        for node_id in mentioned_node_ids:
            node = nodes.get(node_id)
            if node is None:
                raise _context_error("mentioned_node_not_found", "Mentioned node was not found.")
            summaries.append(_node_summary(node))
            for binding in workflow.bindings:
                if binding.target_node_id != node_id or binding.source.kind != "node":
                    continue
                source = nodes.get(binding.source.node_id)
                if source is None:
                    continue
                summaries.append(
                    f"Input {binding.binding_kind}: {_node_summary(source, include_prompt=False)}"
                )
                if source.node_type == "script":
                    content = str(source.structured_content.get("content") or "")
                    if content:
                        script_summaries.append(content)

        for asset_id in mentioned_image_asset_ids:
            try:
                asset = self._asset_resolver(asset_id)
            except (KeyError, V2PersistenceError) as error:
                raise _context_error(
                    "mentioned_asset_not_found",
                    "Mentioned image asset was not found.",
                ) from error
            if asset.media_type != "image":
                raise _context_error(
                    "mentioned_asset_media_type_unsupported",
                    "Only image assets can be mentioned directly.",
                )
            summaries.append(
                f"Image asset {asset.asset_id}: {asset.display_name}; checksum={asset.checksum}"
            )

        return DirectorTurnContextV2(
            context_kind="director_turn",
            workflow_id=workflow_id,
            workflow_revision=workflow.revision,
            conversation_id=conversation_id,
            user_input=user_input,
            mentioned_node_ids=mentioned_node_ids,
            mentioned_image_asset_ids=mentioned_image_asset_ids,
            recent_messages=recent_messages[-self._recent_message_limit :],
            script_summary="\n".join(script_summaries),
            video_skill_excerpt=video_skill_excerpt,
            explicit_input_summaries=tuple(summaries),
        )


def _node_summary(node, *, include_prompt: bool = True) -> str:
    summary = {
        "node_id": node.node_id,
        "node_type": node.node_type,
        "semantic_role": node.semantic_role,
        "title": node.title,
        "status": node.status,
    }
    if include_prompt:
        summary["generation_prompt"] = node.generation_prompt or ""
        summary["content"] = str(node.structured_content.get("content") or "")
    return json.dumps(summary, ensure_ascii=False, sort_keys=True)


def _context_error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_local_context_assembler")
