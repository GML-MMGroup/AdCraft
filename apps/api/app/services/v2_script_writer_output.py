from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.schemas.workflow_v2_screenplay import V2ScriptPlanV2
from app.services.llm_context_sanitizer import (
    sanitize_context_for_llm_text,
    sanitize_context_for_llm_text_with_warnings,
)
from app.services.v2_high_risk_prompt_renderer import V2HighRiskPromptRenderer

SCRIPT_WRITER_REQUIRED_TOP_LEVEL_FIELDS = [
    "script_plan_version",
    "script_brief_id",
    "script_version_id",
    "language",
    "script_title",
    "script_text",
    "scenes",
    "shots",
    "characters",
    "locations",
    "product_beats",
    "tone",
    "visual_style",
    "duration_seconds",
    "aspect_ratio",
]

SCRIPT_WRITER_CANONICAL_ID_FIELDS = [
    "characters[].character_id",
    "locations[].location_id",
    "scenes[].scene_id",
    "shots[].shot_id",
    "shots[].scene_id",
    "shots[].product_ids",
    "shots[].character_ids",
    "shots[].scene_ids",
    "shots[].reference_item_ids",
    "shots[].dialogue[].dialogue_id",
    "shots[].dialogue[].character_id",
]

SCRIPT_WRITER_FORBIDDEN_ALIAS_ONLY_FIELDS = [
    "characters[].id",
    "locations[].id",
    "scenes[].id",
    "shots[].id",
]

_ENVELOPE_KEYS = ("script_plan", "plan", "data", "result", "output")
_ALIASES = (
    ("characters", "character_id"),
    ("locations", "location_id"),
    ("scenes", "scene_id"),
    ("shots", "shot_id"),
)


def script_writer_output_schema() -> dict[str, Any]:
    return V2ScriptPlanV2.model_json_schema()


def script_writer_json_schema_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "V2ScriptPlanV2",
            "schema": script_writer_output_schema(),
            "strict": True,
        },
    }


def script_writer_json_object_response_format() -> dict[str, Any]:
    return {"type": "json_object"}


def script_writer_system_prompt() -> str:
    return (
        V2HighRiskPromptRenderer()
        .render(
            prompt_id="v2.script_writer.plan.v1",
            context={
                "required_top_level_fields": SCRIPT_WRITER_REQUIRED_TOP_LEVEL_FIELDS,
                "canonical_id_fields": SCRIPT_WRITER_CANONICAL_ID_FIELDS,
                "forbidden_alias_only_fields": SCRIPT_WRITER_FORBIDDEN_ALIAS_ONLY_FIELDS,
            },
            identity={"path_kind": "normal"},
        )
        .prompt_text
    )


def normalize_script_writer_output(payload: Any, *, model_id: str | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("Script Writer output must be a JSON object.")

    normalized = _strip_strings(deepcopy(_unwrap_envelope(payload)))
    if not isinstance(normalized, dict):
        raise TypeError("Script Writer output must be a JSON object.")

    for list_key, canonical_id in _ALIASES:
        _map_id_alias(normalized.get(list_key), canonical_id)

    normalized.setdefault("script_plan_version", 2)
    normalized["materializer_mode"] = "real"
    normalized["model_id"] = model_id
    return normalized


def validation_error_paths(errors: list[dict[str, Any]], *, limit: int = 8) -> list[str]:
    paths: list[str] = []
    for error in errors:
        loc = error.get("loc")
        if isinstance(loc, (list, tuple)) and loc:
            paths.append(".".join(str(part) for part in loc))
        elif loc:
            paths.append(str(loc))
    return paths[:limit]


def script_writer_schema_error_message(errors: list[dict[str, Any]]) -> str:
    paths = validation_error_paths(errors)
    path_text = ", ".join(paths) if paths else "unknown"
    return f"Script Writer output did not match V2ScriptPlanV2. Invalid fields: {path_text}."


def build_script_writer_repair_payload(
    *,
    original_payload: dict[str, Any],
    invalid_output: Any,
    validation_errors: list[dict[str, Any]] | None = None,
    quality_error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation_errors = validation_errors or []
    sanitized_invalid_output, trim_warnings = sanitize_context_for_llm_text_with_warnings(
        invalid_output,
        max_chars=12_000,
    )
    payload = {
        "task": "Repair the previous Script Writer output to match V2ScriptPlanV2.",
        "repair_request": {
            "instructions": [
                "Do not explain.",
                "Do not wrap the answer in markdown.",
                "Do not return a partial patch.",
                "Return one complete JSON object matching V2ScriptPlanV2.",
                "Keep the original advertising intent, product, audience, duration, aspect ratio, language, and asset references.",
            ],
            "validation_error_paths": validation_error_paths(validation_errors),
            "validation_errors": validation_errors,
            "quality_error": quality_error or {},
        },
        "original_script_writer_input": original_payload,
        "output_schema": script_writer_output_schema(),
        "invalid_model_output": sanitized_invalid_output,
        "warnings": trim_warnings,
    }
    return sanitize_context_for_llm_text(payload)


def _unwrap_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    current = payload
    for key in _ENVELOPE_KEYS:
        value = current.get(key)
        if isinstance(value, dict):
            current = value
            break
    return current


def _map_id_alias(value: Any, canonical_id: str) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        if not isinstance(item, dict):
            continue
        alias_value = item.get("id")
        if canonical_id not in item and isinstance(alias_value, str) and alias_value.strip():
            item[canonical_id] = alias_value.strip()
        item.pop("id", None)


def _strip_strings(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_strip_strings(item) for item in value]
    if isinstance(value, str):
        return value.strip()
    return value
