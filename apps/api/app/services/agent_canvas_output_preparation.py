"""Prepare Agent Canvas node results without publishing runtime state."""

from __future__ import annotations

import hashlib
import json

from app.schemas.agent_canvas_runtime_authority import (
    PreparedNodeResultV2,
    PreparedPostReadyEffectV2,
)
from app.services.agent_canvas_assets import AgentCanvasAssetService
from app.services.agent_canvas_node_execution import (
    NodeExecutionContext,
    NodeExecutionOutcome,
    generated_asset_publication_metadata,
)


class AgentCanvasOutputPreparationService:
    def __init__(self, assets: AgentCanvasAssetService) -> None:
        self._assets = assets

    def prepare(
        self,
        context: NodeExecutionContext,
        outcome: NodeExecutionOutcome,
        *,
        fingerprint: str,
    ) -> PreparedNodeResultV2:
        effects = _effects(context)
        if outcome.media is not None:
            prepared = self._assets.prepare_generated_bytes(
                context.node.workflow_id,
                node_id=context.node.node_id,
                execution_id=context.execution_id,
                filename=outcome.media.filename,
                mime_type=outcome.media.mime_type,
                content=outcome.media.content,
                fingerprint=fingerprint,
                source_semantic_role=context.node.semantic_role,
                publication_metadata={
                    **generated_asset_publication_metadata(context),
                    **outcome.media.metadata,
                },
            )
            return prepared.model_copy(
                update={
                    "provider_task_id": outcome.provider_task_id,
                    "post_ready_effects": effects,
                }
            )
        structured = outcome.structured_content or {}
        digest = _digest(structured)
        return PreparedNodeResultV2(
            logical_result_key=fingerprint,
            payload_digest=digest,
            structured_content=structured,
            provider_task_id=outcome.provider_task_id,
            post_ready_effects=effects,
        )


def _effects(
    context: NodeExecutionContext,
) -> tuple[PreparedPostReadyEffectV2, ...]:
    if context.node.node_type == "script":
        return (
            PreparedPostReadyEffectV2(
                effect_type="persist_script_document",
                payload={"node_id": context.node.node_id},
            ),
        )
    if context.node.node_type == "text":
        return (
            PreparedPostReadyEffectV2(
                effect_type="persist_text_document",
                payload={"node_id": context.node.node_id},
            ),
        )
    if context.node.node_type in {"image", "video", "audio"}:
        return (
            PreparedPostReadyEffectV2(
                effect_type="advance_storyboard_progression",
                payload={"node_id": context.node.node_id},
            ),
        )
    return ()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
