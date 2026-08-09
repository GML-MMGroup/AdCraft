"""Deterministic ownership and context isolation for V2 Pi agents."""

from __future__ import annotations

import json
from typing import Any, Protocol

from app.core.config import Settings
from app.schemas.agent_operation_contexts import (
    InteractionMessageSummary,
    InteractionTargetSummary,
    PlanningReferenceSummary,
    QuickMediaAgentContext,
    AssetRevisionAgentContext,
)
from app.schemas.agent_runtime import V2ResolvedAgentTarget
from app.schemas.workflow_v2 import WorkflowV2FreeNodeGenerateRequest
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_workflow_authoring import create_workflow_authoring_runtime

_FORBIDDEN_CONTEXT_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "credentials",
        "full_workflow",
        "local_path",
        "media_bytes",
        "provider_payload",
        "raw_media",
        "secret",
        "sibling_prompts",
        "sibling_provider_prompts",
        "token",
        "workflow_json",
    }
)

_HISTORY_UNSAFE_MARKERS = (
    ";base64,",
    "data:",
    "/private/",
    "\\\\",
)


class ConversationContextSource(Protocol):
    def load_context(
        self,
        conversation_id: str,
        *,
        limit: int,
    ) -> tuple[str, list[dict[str, object]]]: ...


class V2AgentContextBuilder:
    """Build bounded Pi inputs from one canonical target or free node."""

    def __init__(
        self,
        settings: Settings,
        *,
        conversation_context_source: ConversationContextSource | None = None,
        recent_message_limit: int = 12,
        recent_message_bytes: int = 8_192,
    ) -> None:
        self._read_model = create_workflow_authoring_runtime(settings.media_data_dir).read_model
        self._asset_store = V2AssetStoreService(settings.media_data_dir)
        self._conversation_context_source = conversation_context_source
        self._recent_message_limit = max(1, min(recent_message_limit, 32))
        self._recent_message_bytes = max(256, min(recent_message_bytes, 32_768))

    def build_asset_revision(
        self,
        *,
        workflow_id: str,
        conversation_id: str | None,
        target: V2ResolvedAgentTarget,
        user_instruction: str,
    ) -> AssetRevisionAgentContext:
        workflow = self._read_model.assemble(workflow_id)
        item = next(
            (
                item
                for node in workflow.nodes
                for item in node.items
                if item.item_id == target.item_id
            ),
            None,
        )
        slot = next(
            (
                slot
                for node in workflow.nodes
                for item in node.items
                for slot in item.slots
                if slot.slot_id == target.slot_id
            ),
            None,
        )
        if item is None or slot is None or workflow.state_version is None:
            raise ValueError("agent_target_not_found")
        conversation_summary, recent_messages = self._conversation_context(conversation_id)
        return AssetRevisionAgentContext(
            context_kind="asset_revision",
            user_input=user_instruction,
            workflow_id=workflow.workflow_id,
            conversation_id=conversation_id,
            target=InteractionTargetSummary(
                target_locator=target.target_locator,
                node_id=target.node_id,
                item_id=target.item_id,
                slot_id=target.slot_id,
                slot_type=target.slot_type,
                owner_type=target.owner_type,
                owner_display_name=target.display_name,
                current_prompt=slot.user_prompt or slot.slot_prompt or item.item_prompt,
                expected_revision=workflow.state_version,
                related_multiview_slot_id=target.related_multiview_slot_id,
                selected_version=self._asset_summary(
                    slot.selected_asset_id,
                    slot.selected_version_id,
                ),
                working_version=self._asset_summary(
                    slot.current_working_asset_id,
                    slot.current_working_version_id,
                ),
            ),
            conversation_summary=_bounded_text(conversation_summary, 16_384),
            recent_messages=tuple(recent_messages),
            screenplay_slice=self._screenplay_slice(workflow.metadata, item.item_id),
            style_scope=self._style_scope(workflow.metadata),
            continuity_slice=_bounded_json(
                {
                    "description": item.description,
                    "continuity": item.metadata.get("continuity"),
                },
                8_192,
            ),
            reference_summaries=tuple(
                self._reference_summaries(workflow.workflow_id, slot.slot_id)
            ),
        )

    def build_quick_media(
        self,
        *,
        workflow_id: str,
        node_id: str,
        request: WorkflowV2FreeNodeGenerateRequest,
    ) -> QuickMediaAgentContext:
        workflow = self._read_model.assemble(workflow_id)
        node = next(
            (
                candidate
                for candidate in workflow.nodes
                if candidate.node_id == node_id and candidate.node_type == "free-generation"
            ),
            None,
        )
        if node is None:
            raise ValueError("free_node_not_found")
        active_items = [item for item in node.items if item.lifecycle_state == "active"]
        if len(active_items) != 1:
            raise ValueError("free_node_not_found")
        item = active_items[0]
        slot = next(
            (candidate for candidate in item.slots if candidate.slot_type == "free_output"), None
        )
        if slot is None or request.output_media_type not in {"image", "video", "audio"}:
            raise ValueError("free_media_type_not_supported")
        prompt = slot.user_prompt or slot.slot_prompt or item.item_prompt
        if not prompt:
            raise ValueError("free_media_prompt_empty")
        return QuickMediaAgentContext(
            context_kind="quick_media",
            user_input=prompt,
            workflow_id=workflow.workflow_id,
            node_id=node.node_id,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            output_media_type=request.output_media_type,
            negative_prompt=slot.negative_prompt,
            style_scope=self._style_scope(workflow.metadata),
            reference_summaries=tuple(
                self._reference_summaries(workflow.workflow_id, slot.slot_id)
            ),
        )

    def _conversation_context(
        self,
        conversation_id: str | None,
    ) -> tuple[str, list[InteractionMessageSummary]]:
        if conversation_id is None or self._conversation_context_source is None:
            return "", []
        summary, raw_messages = self._conversation_context_source.load_context(
            conversation_id,
            limit=self._recent_message_limit,
        )
        messages: list[InteractionMessageSummary] = []
        used_bytes = 0
        for raw in raw_messages[-self._recent_message_limit :]:
            content = str(raw.get("content") or "").strip()
            if not content or _unsafe_visible_text(content):
                continue
            remaining = self._recent_message_bytes - used_bytes
            if remaining <= 0:
                break
            content = _truncate_utf8(content, min(remaining, 4_096))
            if not content:
                break
            role = str(raw.get("role") or "")
            if role not in {"user", "assistant", "system"}:
                continue
            messages.append(
                InteractionMessageSummary(
                    sequence_no=int(raw.get("sequence_no") or len(messages) + 1),
                    role=role,
                    content=content,
                )
            )
            used_bytes += len(content.encode("utf-8"))
        return summary, messages

    def _reference_summaries(
        self,
        workflow_id: str,
        slot_id: str,
    ) -> list[PlanningReferenceSummary]:
        summaries: list[PlanningReferenceSummary] = []
        for relation_type in (
            "reference_for_slot",
            "implicit_reference_for_slot",
        ):
            for relation in self._asset_store.list_relations(
                target_workflow_id=workflow_id,
                target_slot_id=slot_id,
                relation_type=relation_type,
            ):
                version_id = str(relation.metadata.get("version_id") or "")
                summary = self._asset_summary(relation.source_asset_id, version_id)
                if summary is not None:
                    summaries.append(summary)
        return summaries[:128]

    def _asset_summary(
        self,
        asset_id: str | None,
        version_id: str | None,
    ) -> PlanningReferenceSummary | None:
        if not asset_id or not version_id:
            return None
        record = self._asset_store.load_asset_version(asset_id, version_id)
        if record is None:
            return None
        return PlanningReferenceSummary(
            asset_id=record.asset_id,
            version_id=record.version_id,
            semantic_type=record.semantic_type or record.media_type,
            display_name=str(record.metadata.get("display_name") or ""),
            media_type=record.media_type,
            description=str(record.prompt_snapshot.get("summary_prompt") or ""),
        )

    @staticmethod
    def _screenplay_slice(metadata: dict[str, Any], item_id: str) -> str:
        plan = metadata.get("script_plan")
        if not isinstance(plan, dict):
            return ""
        relevant = {
            key: [
                entry
                for entry in value
                if isinstance(entry, dict)
                and item_id
                in {
                    str(entry.get("character_id") or ""),
                    str(entry.get("location_id") or ""),
                    str(entry.get("scene_id") or ""),
                }
            ]
            for key, value in plan.items()
            if key in {"characters", "locations", "scenes"} and isinstance(value, list)
        }
        return _bounded_json(relevant, 16_384)

    @staticmethod
    def _style_scope(metadata: dict[str, Any]) -> str:
        return _bounded_json(
            {
                key: metadata[key]
                for key in ("visual_style", "style_scope", "tone")
                if metadata.get(key) is not None
            },
            8_192,
        )


def isolate_agent_input_payload(payload: dict[str, Any]) -> dict[str, Any]:
    isolated = _isolate_value(payload)
    return isolated if isinstance(isolated, dict) else {}


def _isolate_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): isolated
            for key, child in value.items()
            if str(key).casefold() not in _FORBIDDEN_CONTEXT_KEYS
            and (isolated := _isolate_value(child)) is not None
        }
    if isinstance(value, (list, tuple)):
        return [isolated for child in value if (isolated := _isolate_value(child)) is not None]
    if isinstance(value, bytes):
        return None
    if isinstance(value, str):
        lowered = value.casefold()
        if ";base64," in lowered or lowered.startswith(("data:", "/", "\\\\")):
            return None
    return value


def _bounded_json(value: Any, max_bytes: int) -> str:
    safe = isolate_agent_input_payload(value if isinstance(value, dict) else {"value": value})
    return _truncate_utf8(
        json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        max_bytes,
    )


def _bounded_text(value: str, max_bytes: int) -> str:
    return "" if _unsafe_visible_text(value) else _truncate_utf8(value, max_bytes)


def _unsafe_visible_text(value: str) -> bool:
    lowered = value.casefold()
    return any(marker in lowered for marker in _HISTORY_UNSAFE_MARKERS)


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")
