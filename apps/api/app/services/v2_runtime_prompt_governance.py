from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.workflow_v2 import WorkflowItemV2, WorkflowSlotV2, WorkflowV2
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text


LEGACY_PROMPT_FIELD_ALIASES: dict[str, str] = {
    "node.prompt": "node_prompt",
    "content.prompt": "content_prompt",
    "override_prompt": "override_prompt",
    "input_context.materialized_prompt": "input_context_materialized_prompt",
    "scene_prompts": "scene_prompts",
    "final_video_prompt": "final_video_prompt",
    "legacy_scene_prompts": "legacy_scene_prompts",
    "legacy_final_video_prompt": "legacy_final_video_prompt",
    "legacy_materialized_prompt": "legacy_materialized_prompt",
}

SUPPORTED_V2_PROMPT_SLOT_TYPES: set[str] = {
    "product_main_image",
    "product_multi_view_grid",
    "character_main_image",
    "character_three_view",
    "scene_main_image",
    "scene_multi_view_grid",
    "shot_cell_1",
    "shot_cell_2",
    "shot_cell_3",
    "shot_cell_4",
    "shot_video_segment",
    "bgm_audio",
    "free_output",
}


class V2PromptProvenance(BaseModel):
    compiler: str
    source_fields: list[str] = Field(default_factory=list)
    legacy_fields_ignored: list[str] = Field(default_factory=list)
    legacy_fields_adapted: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    reference_item_ids: list[str] = Field(default_factory=list)
    reference_asset_ids: list[str] = Field(default_factory=list)


class V2CompiledPrompt(BaseModel):
    slot_id: str
    node_id: str
    item_id: str
    slot_type: str
    media_type: str
    system_prompt: str | None = None
    provider_prompt: str
    negative_prompt: str | None = None
    negative_constraints: str | None = None
    reference_item_ids: list[str] = Field(default_factory=list)
    reference_asset_ids: list[str] = Field(default_factory=list)
    source_fields: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    provenance: V2PromptProvenance


class V2PromptGovernanceError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.metadata = metadata or {}


Compiler = Callable[[WorkflowV2, WorkflowItemV2, WorkflowSlotV2, dict[str, Any]], V2CompiledPrompt]


def compiler_name_for_slot(slot_type: str) -> str:
    if slot_type.startswith("shot_cell_"):
        return "storyboard_cell_prompt_compiler"
    return f"{slot_type}_prompt_compiler"


def compile_v2_provider_prompt(
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    *,
    provider_payload: dict[str, Any],
) -> V2CompiledPrompt:
    compiler = _compiler_for_slot(slot.slot_type)
    return compiler(workflow, item, slot, provider_payload)


def apply_compiled_prompt_to_payload(
    payload: dict[str, Any],
    compiled: V2CompiledPrompt,
) -> dict[str, Any]:
    prompt_payload = compiled.model_dump(mode="json", exclude={"provenance"})
    provenance = compiled.provenance.model_dump(mode="json")
    return {
        **payload,
        "provider_prompt": compiled.provider_prompt,
        "negative_prompt": compiled.negative_prompt,
        "negative_constraints": compiled.negative_constraints,
        "reference_asset_ids": list(compiled.reference_asset_ids),
        "compiled_prompt": prompt_payload,
        "prompt_provenance": provenance,
    }


def _compiler_for_slot(slot_type: str) -> Compiler:
    if slot_type in SUPPORTED_V2_PROMPT_SLOT_TYPES:
        return _compile_supported_slot
    return _compile_generic_slot


def _compile_supported_slot(
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    payload: dict[str, Any],
) -> V2CompiledPrompt:
    return _compile_slot(
        workflow,
        item,
        slot,
        payload,
        compiler=compiler_name_for_slot(slot.slot_type),
        generic=False,
    )


def _compile_generic_slot(
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    payload: dict[str, Any],
) -> V2CompiledPrompt:
    return _compile_slot(
        workflow,
        item,
        slot,
        payload,
        compiler="v2_generic_prompt_compiler",
        generic=True,
    )


def _compile_slot(
    workflow: WorkflowV2,
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    payload: dict[str, Any],
    *,
    compiler: str,
    generic: bool,
) -> V2CompiledPrompt:
    payload_slot_type = payload.get("slot_type")
    if (
        isinstance(payload_slot_type, str)
        and payload_slot_type
        and payload_slot_type != slot.slot_type
    ):
        raise V2PromptGovernanceError(
            "v2_provider_prompt_wrong_slot_type",
            f"Compiled prompt slot_type {payload_slot_type!r} does not match slot {slot.slot_type!r}.",
            metadata=_error_metadata(slot, payload),
        )
    prompt, source_fields = _provider_prompt_and_sources(item, slot, payload)
    legacy_fields = _legacy_fields_present(payload)
    _raise_if_legacy_overrode_prompt(slot, prompt, legacy_fields, payload)
    warnings = _warnings_from_payload(payload)
    if generic:
        warnings.append(
            {
                "code": "v2_generic_prompt_compiler_used",
                "message": f"No dedicated V2 prompt compiler route for slot_type={slot.slot_type}.",
            }
        )
    warnings.extend(_contamination_warnings(item, slot, payload))
    _validate_prompt_not_empty(slot, prompt, payload)
    _validate_required_references(slot, payload)
    _validate_shot_video_cell_scope(item, slot, payload)
    reference_item_ids = _string_list(
        payload.get("selected_reference_item_ids") or item.reference_item_ids
    )
    reference_asset_ids = _string_list(payload.get("reference_asset_ids"))
    provenance = V2PromptProvenance(
        compiler=compiler,
        source_fields=source_fields,
        legacy_fields_ignored=legacy_fields,
        warnings=warnings,
        reference_item_ids=reference_item_ids,
        reference_asset_ids=reference_asset_ids,
    )
    return V2CompiledPrompt(
        slot_id=slot.slot_id,
        node_id=slot.node_id,
        item_id=item.item_id,
        slot_type=slot.slot_type,
        media_type=str(slot.media_type),
        system_prompt=_system_prompt_for_slot(slot),
        provider_prompt=prompt,
        negative_prompt=_optional_text(payload.get("negative_prompt") or slot.negative_prompt),
        negative_constraints=_optional_text(
            payload.get("negative_constraints") or slot.negative_constraints
        ),
        reference_item_ids=reference_item_ids,
        reference_asset_ids=reference_asset_ids,
        source_fields=source_fields,
        warnings=warnings,
        provenance=provenance,
    )


def _provider_prompt_and_sources(
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    payload: dict[str, Any],
) -> tuple[str, list[str]]:
    provider_prompt_is_explicit = "provider_prompt" in payload
    prompt = _optional_text(payload.get("provider_prompt"))
    sources: list[str] = []
    if prompt:
        sources.append("provider_payload.provider_prompt")
    canonical_slot_prompt = _optional_text(slot.slot_prompt)
    if canonical_slot_prompt and canonical_slot_prompt in prompt:
        sources.append("slot.slot_prompt")
    if provider_prompt_is_explicit and not prompt:
        return "", sources
    if not prompt and canonical_slot_prompt:
        prompt = canonical_slot_prompt
        sources.append("slot.slot_prompt")
    if not prompt and item.item_prompt:
        prompt = item.item_prompt
        sources.append("item.item_prompt")
    if not prompt and item.shot_summary_prompt:
        prompt = item.shot_summary_prompt
        sources.append("item.shot_summary_prompt")
    if not prompt:
        prompt = ""
    sources.extend(_slot_specific_source_fields(item, slot, payload))
    return prompt, _ordered_unique(sources)


def _slot_specific_source_fields(
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    payload: dict[str, Any],
) -> list[str]:
    if slot.slot_type.startswith("shot_cell_"):
        sequence_index = payload.get("sequence_index")
        if isinstance(sequence_index, int) and sequence_index > 0:
            return [f"item.cell_prompts[{sequence_index - 1}].provider_prompt"]
        return ["item.cell_prompts.provider_prompt"]
    if slot.slot_type == "shot_video_segment":
        sources = ["slot.slot_prompt"]
        if payload.get("cell_prompts"):
            sources.append("item.cell_prompts[].provider_prompt")
        if item.summary_prompt or item.shot_summary_prompt:
            sources.append("item.summary_prompt")
        return sources
    if slot.slot_type in {
        "product_multi_view_grid",
        "character_three_view",
        "scene_multi_view_grid",
    }:
        return ["selected_main_reference"]
    if slot.slot_type == "bgm_audio":
        return ["slot.slot_prompt"]
    return []


def _legacy_fields_present(payload: dict[str, Any]) -> list[str]:
    ignored: list[str] = []
    for display, key in LEGACY_PROMPT_FIELD_ALIASES.items():
        if key in payload and payload.get(key) not in (None, "", [], {}):
            ignored.append(key)
        if display in payload and payload.get(display) not in (None, "", [], {}):
            ignored.append(display)
    legacy_present = payload.get("legacy_prompt_fields_present")
    if isinstance(legacy_present, list):
        ignored.extend(str(field) for field in legacy_present if str(field).strip())
    return _ordered_unique(ignored)


def _raise_if_legacy_overrode_prompt(
    slot: WorkflowSlotV2,
    prompt: str,
    legacy_fields: list[str],
    payload: dict[str, Any],
) -> None:
    slot_prompt = _optional_text(slot.slot_prompt)
    if not slot_prompt:
        return
    for field in legacy_fields:
        value = _optional_text(payload.get(field))
        if value and prompt == value and value != slot_prompt:
            raise V2PromptGovernanceError(
                "v2_provider_prompt_legacy_field_override",
                f"Legacy prompt field {field!r} attempted to override canonical slot prompt.",
                metadata=_error_metadata(slot, payload, legacy_field=field),
            )


def _validate_prompt_not_empty(
    slot: WorkflowSlotV2,
    prompt: str,
    payload: dict[str, Any],
) -> None:
    if prompt.strip():
        return
    raise V2PromptGovernanceError(
        "v2_provider_prompt_empty",
        "V2 provider prompt is empty after compilation.",
        metadata=_error_metadata(slot, payload),
    )


def _validate_required_references(slot: WorkflowSlotV2, payload: dict[str, Any]) -> None:
    required = set(_string_list(payload.get("required_reference_asset_ids")))
    if not required:
        return
    provided = set(_string_list(payload.get("reference_asset_ids")))
    missing = sorted(required - provided)
    if not missing:
        return
    raise V2PromptGovernanceError(
        "v2_provider_prompt_missing_required_reference",
        "V2 prompt is missing required reference assets: " + ", ".join(missing),
        metadata=_error_metadata(slot, payload, missing_reference_asset_ids=missing),
    )


def _validate_shot_video_cell_scope(
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    payload: dict[str, Any],
) -> None:
    if slot.slot_type != "shot_video_segment":
        return
    own_shot_id = item.shot_id or item.item_id
    cell_prompts = payload.get("cell_prompts") or payload.get("shot_cell_prompt_details")
    if not isinstance(cell_prompts, list):
        return
    foreign = [
        str(record.get("shot_id"))
        for record in cell_prompts
        if isinstance(record, dict)
        and record.get("shot_id")
        and str(record.get("shot_id")) != own_shot_id
    ]
    if not foreign:
        return
    raise V2PromptGovernanceError(
        "v2_provider_prompt_contaminated_by_sibling",
        "Shot video prompt includes cell prompts from another shot.",
        metadata=_error_metadata(slot, payload, foreign_shot_ids=_ordered_unique(foreign)),
    )


def _contamination_warnings(
    item: WorkflowItemV2,
    slot: WorkflowSlotV2,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    del item
    bodies = payload.get("unrelated_sibling_prompt_bodies")
    if not isinstance(bodies, list) or not bodies:
        return []
    if slot.slot_type in {"scene_main_image", "character_main_image"}:
        return [
            {
                "code": "v2_provider_prompt_contaminated_by_sibling",
                "message": "Provider payload contained unrelated sibling prompt bodies.",
                "severity": "warning",
            }
        ]
    return []


def _warnings_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    warnings = payload.get("materializer_warnings") or payload.get("warnings") or []
    if not isinstance(warnings, list):
        return []
    return [warning for warning in warnings if isinstance(warning, dict)]


def _system_prompt_for_slot(slot: WorkflowSlotV2) -> str | None:
    if slot.slot_type.startswith("shot_cell_"):
        return "Compile one isolated storyboard cell prompt."
    if slot.slot_type == "shot_video_segment":
        return "Compile one storyboard shot video segment prompt."
    if slot.media_type:
        return f"Compile a provider-ready {slot.media_type} prompt for {slot.slot_type}."
    return None


def _error_metadata(
    slot: WorkflowSlotV2,
    payload: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    return sanitize_context_for_llm_text(
        {
            "node_id": slot.node_id,
            "item_id": slot.item_id,
            "slot_id": slot.slot_id,
            "slot_type": slot.slot_type,
            "media_type": slot.media_type,
            "provider_prompt_present": bool(_optional_text(payload.get("provider_prompt"))),
            **extra,
        }
    )


def _optional_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
