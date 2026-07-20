from __future__ import annotations

from typing import Any

from app.schemas.workflow_revisions import WorkflowRevisionRequest, WorkflowRevisionState


PROMPT_TARGET_CANONICAL_FIELDS = {
    "prompt_scope",
    "source_item_id",
    "source_item_prompt",
    "source_asset_id",
    "source_asset_prompt",
    "asset_slot_id",
}

PROMPT_TARGET_ALIASES = {
    "item_id": "source_item_id",
    "item_prompt": "source_item_prompt",
    "asset_id": "source_asset_id",
    "asset_prompt": "source_asset_prompt",
}

ALLOWED_PROMPT_SCOPES = {"item", "asset", "node", "unknown"}


class PromptTargetMetadataConflict(ValueError):
    def __init__(
        self,
        *,
        canonical_field: str,
        alias_field: str,
        canonical_value: Any,
        alias_value: Any,
    ) -> None:
        self.detail = {
            "code": "prompt_target_field_conflict",
            "canonical_field": canonical_field,
            "alias_field": alias_field,
            "canonical_value": canonical_value,
            "alias_value": alias_value,
        }
        super().__init__("prompt target metadata has conflicting alias fields")


def normalize_prompt_target_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(metadata or {})
    for alias_field, canonical_field in PROMPT_TARGET_ALIASES.items():
        alias_value = normalized.get(alias_field)
        canonical_value = normalized.get(canonical_field)
        if _has_value(alias_value) and _has_value(canonical_value):
            if str(alias_value) != str(canonical_value):
                raise PromptTargetMetadataConflict(
                    canonical_field=canonical_field,
                    alias_field=alias_field,
                    canonical_value=canonical_value,
                    alias_value=alias_value,
                )
        elif _has_value(alias_value):
            normalized[canonical_field] = alias_value
        normalized.pop(alias_field, None)

    scope = str(normalized.get("prompt_scope") or "").strip()
    if not scope:
        scope = _infer_prompt_scope(normalized)
    if scope not in ALLOWED_PROMPT_SCOPES:
        scope = "unknown"
    normalized["prompt_scope"] = scope
    return normalized


def revision_request_with_normalized_metadata(
    request: WorkflowRevisionRequest,
) -> WorkflowRevisionRequest:
    return request.model_copy(
        update={"metadata": normalize_prompt_target_metadata(request.metadata)}
    )


def revision_provider_prompt_value(
    request: WorkflowRevisionRequest,
    state: WorkflowRevisionState,
    target: dict[str, Any],
) -> str:
    metadata = normalize_prompt_target_metadata(request.metadata)
    prompt_scope = str(metadata.get("prompt_scope") or "unknown")
    if prompt_scope == "asset":
        source_asset_prompt = _string(metadata.get("source_asset_prompt"))
        if source_asset_prompt:
            return source_asset_prompt
    if prompt_scope == "item":
        source_item_prompt = _string(metadata.get("source_item_prompt"))
        if source_item_prompt:
            return source_item_prompt

    target_asset_prompt = _target_asset_prompt(target)
    if target_asset_prompt:
        return target_asset_prompt
    target_item_prompt = _target_item_prompt(target)
    if target_item_prompt:
        return target_item_prompt
    if prompt_scope in {"unknown", "node"}:
        return (
            _string(state.providerRevisionPrompt)
            or _string(state.optimizedRevisionPrompt)
            or _string(request.instruction)
            or ""
        )
    return (
        _string(request.instruction)
        or _string(state.providerRevisionPrompt)
        or _string(state.optimizedRevisionPrompt)
        or ""
    )


def _infer_prompt_scope(metadata: dict[str, Any]) -> str:
    if _has_value(metadata.get("source_asset_id")) or _has_value(
        metadata.get("source_asset_prompt")
    ):
        return "asset"
    if _has_value(metadata.get("source_item_id")) or _has_value(metadata.get("source_item_prompt")):
        return "item"
    return "unknown"


def _target_asset_prompt(target: dict[str, Any]) -> str:
    asset = target.get("asset") if isinstance(target.get("asset"), dict) else {}
    metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    for value in (
        asset.get("prompt"),
        asset.get("asset_prompt"),
        asset.get("generation_prompt"),
        asset.get("provider_prompt"),
        metadata.get("source_asset_prompt"),
        metadata.get("asset_prompt"),
        metadata.get("generation_prompt"),
        metadata.get("provider_prompt"),
    ):
        prompt = _string(value)
        if prompt:
            return prompt
    return ""


def _target_item_prompt(target: dict[str, Any]) -> str:
    item = target.get("item") if isinstance(target.get("item"), dict) else {}
    for value in (
        target.get("prompt"),
        item.get("prompt"),
        item.get("scenePrompt"),
        item.get("rolePrompt"),
        item.get("productPrompt"),
        item.get("storyboardImagePrompt"),
        item.get("storyboardVideoPrompt"),
    ):
        prompt = _string(value)
        if prompt:
            return prompt
    return ""


def _has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""
