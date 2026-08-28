"""Pure authoring validators shared by public services and command transactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.persistence.errors import V2PersistenceError


@dataclass(frozen=True, slots=True)
class BindingValidationState:
    source_node_id: str | None
    target_node_id: str
    binding_kind: str


def require_node_runnable(node: object) -> None:
    """Reject imported source-only nodes at every generation boundary."""

    if getattr(node, "execution_mode", "generative") == "source_only":
        raise V2PersistenceError(
            "source_only_node_not_runnable",
            "Source-only nodes are previewable inputs and cannot be generated.",
            stage="agent_canvas_authoring_validation",
        )


def validate_node_patch(
    *,
    status: str,
    node_type: str,
    current: Mapping[str, object],
    changes: Mapping[str, object],
) -> str:
    immutable_fields = {
        "generation_prompt",
        "model_selection_mode",
        "model_ref",
        "parameters",
        "structured_content",
    }
    if status == "ready" and node_type in {"image", "video", "audio", "editing"}:
        if any(
            field in changes and changes[field] != current.get(field) for field in immutable_fields
        ):
            raise V2PersistenceError(
                "ready_node_immutable",
                "Create a sibling variation to change generated media.",
                stage="agent_canvas_authoring_validation",
            )
    if node_type not in {"text", "script"}:
        return status
    content = changes.get("structured_content", current.get("structured_content", {}))
    return "ready" if content else "draft"


def validate_ready_node_input_history(*, status: str, node_type: str) -> None:
    if status == "ready" and node_type in {"image", "video", "audio"}:
        raise V2PersistenceError(
            "ready_node_inputs_immutable",
            "Create a sibling variation to change generated media inputs.",
            stage="agent_canvas_authoring_validation",
        )


def validate_node_binding(
    *,
    bindings: tuple[BindingValidationState, ...],
    source_node_id: str,
    source_node_type: str,
    source_semantic_role: str,
    target_node_id: str,
    target_node_type: str,
    binding_kind: str,
) -> None:
    if any(
        binding.source_node_id == source_node_id and binding.target_node_id == target_node_id
        for binding in bindings
    ):
        raise V2PersistenceError(
            "canvas_connection_duplicate",
            "A source-target binding already exists.",
            stage="agent_canvas_authoring_validation",
        )
    _assert_acyclic(
        bindings,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
    )
    compatible = {
        "text": {"text_context"},
        "script": {"text_context"},
        "image": {"image_reference"},
        "video": {"video_reference"},
        "audio": {"audio_reference"},
    }
    if target_node_type != "editing":
        if binding_kind not in compatible.get(source_node_type, set()):
            raise _media_incompatible_error()
        return
    if source_node_type == "video" and binding_kind == "video_reference":
        return
    if source_node_type == "audio" and binding_kind == "audio_reference":
        if source_semantic_role != "bgm":
            raise V2PersistenceError(
                "editing_audio_role_invalid",
                "Editing audio input must use the bgm semantic role.",
                stage="agent_canvas_authoring_validation",
            )
        if any(
            binding.target_node_id == target_node_id and binding.binding_kind == "audio_reference"
            for binding in bindings
        ):
            raise V2PersistenceError(
                "editing_duplicate_bgm",
                "Editing accepts at most one BGM audio binding.",
                stage="agent_canvas_authoring_validation",
            )
        return
    raise _media_incompatible_error()


def _assert_acyclic(
    bindings: tuple[BindingValidationState, ...],
    *,
    source_node_id: str,
    target_node_id: str,
) -> None:
    if source_node_id == target_node_id:
        raise _cycle_error()
    outgoing: dict[str, set[str]] = {}
    for binding in bindings:
        if binding.source_node_id is not None:
            outgoing.setdefault(binding.source_node_id, set()).add(binding.target_node_id)
    pending = [target_node_id]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == source_node_id:
            raise _cycle_error()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(outgoing.get(current, ()))


def _cycle_error() -> V2PersistenceError:
    return V2PersistenceError(
        "binding_cycle_detected",
        "The binding would create a cycle.",
        stage="agent_canvas_authoring_validation",
    )


def _media_incompatible_error() -> V2PersistenceError:
    return V2PersistenceError(
        "binding_media_incompatible",
        "Binding kind is incompatible with the source media.",
        stage="agent_canvas_authoring_validation",
    )
