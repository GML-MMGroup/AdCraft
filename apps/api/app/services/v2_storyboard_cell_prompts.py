from __future__ import annotations

from typing import Any

from app.services.v2_storyboard_defaults import shot_cell_role, shot_cell_slot_types

STORYBOARD_CELL_SEQUENCE_ROLES: tuple[str, ...] = (
    "establishing",
    "action",
    "detail",
    "payoff",
)

STORYBOARD_CELL_ROLE_ALIASES = {
    "opening": "establishing",
    "action_buildup": "action",
    "action_peak": "detail",
}


def storyboard_cell_prompt_records(
    *,
    shot_id: str,
    summary_prompt: str,
    detail_prompts: dict[str, Any] | None,
    reference_item_ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    details = detail_prompts or {}
    records: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    reference_ids = list(reference_item_ids or details.get("reference_item_ids") or [])
    source = details.get("cell_prompts") or details.get("cell_prompt_records")
    fallback_used = False
    for index, slot_type in enumerate(shot_cell_slot_types(), start=1):
        source_cell = _source_cell(source, slot_type, index)
        role = _sequence_role(source_cell, slot_type)
        prompt = _provider_prompt(source_cell)
        if not prompt:
            fallback_used = True
            prompt = _fallback_prompt(summary_prompt, slot_type, role, reference_ids)
        records.append(
            {
                "slot_id": f"{shot_id}:{slot_type}",
                "slot_type": slot_type,
                "cell_id": slot_type,
                "sequence_index": index,
                "sequence_role": role,
                "cell_index": index,
                "cell_role": role,
                "summary_prompt": summary_prompt,
                "provider_prompt": prompt,
                "negative_prompt": _string_value(source_cell, "negative_prompt"),
                "negative_constraints": _string_list(source_cell, "negative_constraints"),
                "continuity_notes": _string_value(source_cell, "continuity_notes")
                or "Maintain same-shot product, character, scene, style, lighting, and time continuity.",
                "reference_item_ids": reference_ids,
                "required_reference_asset_ids": _string_list(
                    source_cell,
                    "required_reference_asset_ids",
                ),
            }
        )
    duplicate_repaired = _repair_duplicate_prompts(records, summary_prompt, reference_ids)
    summary_repaired = _repair_summary_only_prompts(records, summary_prompt, reference_ids)
    if fallback_used:
        warnings.append(
            {
                "code": "storyboard_cell_detail_fallback_used",
                "message": "Storyboard cell detail prompts used deterministic fallback expansion.",
            }
        )
    if duplicate_repaired or summary_repaired:
        warnings.append(
            {
                "code": "storyboard_cell_prompt_duplicate_repaired",
                "message": "Duplicate or summary-only storyboard cell prompts were repaired deterministically.",
            }
        )
    if reference_ids and any(not record["reference_item_ids"] for record in records):
        warnings.append(
            {
                "code": "storyboard_cell_reference_coverage_repaired",
                "message": "Storyboard cell prompt records were repaired with the shot reference item ids.",
            }
        )
    return records, warnings


def cell_prompt_record_for_slot(
    *,
    shot_id: str,
    summary_prompt: str,
    detail_prompts: dict[str, Any] | None,
    slot_type: str,
    reference_item_ids: list[str] | None = None,
) -> dict[str, Any]:
    records, _warnings = storyboard_cell_prompt_records(
        shot_id=shot_id,
        summary_prompt=summary_prompt,
        detail_prompts=detail_prompts,
        reference_item_ids=reference_item_ids,
    )
    for record in records:
        if record["slot_type"] == slot_type:
            return record
    role = shot_cell_role(slot_type)
    return {
        "slot_id": f"{shot_id}:{slot_type}",
        "slot_type": slot_type,
        "cell_id": slot_type,
        "sequence_index": _slot_index(slot_type),
        "sequence_role": role,
        "cell_index": _slot_index(slot_type),
        "cell_role": role,
        "summary_prompt": summary_prompt,
        "provider_prompt": _fallback_prompt(
            summary_prompt,
            slot_type,
            role,
            list(reference_item_ids or []),
        ),
        "reference_item_ids": list(reference_item_ids or []),
    }


def cell_prompt_records_by_slot(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(record["slot_type"]): dict(record) for record in records if record.get("slot_type")}


def enrich_detail_prompts_with_cell_records(
    *,
    shot_id: str,
    summary_prompt: str,
    detail_prompts: dict[str, Any] | None,
    reference_item_ids: list[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    details = dict(detail_prompts or {})
    records, warnings = storyboard_cell_prompt_records(
        shot_id=shot_id,
        summary_prompt=summary_prompt,
        detail_prompts=details,
        reference_item_ids=reference_item_ids,
    )
    details["cell_prompt_records"] = [dict(record) for record in records]
    details["cell_prompts"] = cell_prompt_records_by_slot(records)
    if warnings:
        details["warnings"] = _dedupe_warnings([*list(details.get("warnings") or []), *warnings])
    return details, records, warnings


def _source_cell(source: Any, slot_type: str, index: int) -> dict[str, Any]:
    if isinstance(source, dict):
        value = source.get(slot_type) or source.get(str(index))
        return dict(value) if isinstance(value, dict) else {}
    if isinstance(source, list):
        for value in source:
            if not isinstance(value, dict):
                continue
            if value.get("slot_type") == slot_type or value.get("sequence_index") == index:
                return dict(value)
    return {}


def _sequence_role(source_cell: dict[str, Any], slot_type: str) -> str:
    role = str(
        source_cell.get("sequence_role")
        or source_cell.get("cell_role")
        or shot_cell_role(slot_type)
    ).strip()
    return STORYBOARD_CELL_ROLE_ALIASES.get(role, role)


def _provider_prompt(source_cell: dict[str, Any]) -> str:
    for key in ("provider_prompt", "visual_prompt", "prompt", "cell_prompt", "image_prompt"):
        value = source_cell.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _string_value(source_cell: dict[str, Any], key: str) -> str | None:
    value = source_cell.get(key)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _string_list(source_cell: dict[str, Any], key: str) -> list[str]:
    value = source_cell.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in (str(raw).strip() for raw in value) if item]


def _repair_duplicate_prompts(
    records: list[dict[str, Any]],
    summary_prompt: str,
    reference_item_ids: list[str],
) -> bool:
    seen: set[str] = set()
    repaired = False
    for record in records:
        normalized = _normalize_prompt(str(record["provider_prompt"]))
        if normalized in seen:
            record["provider_prompt"] = _fallback_prompt(
                summary_prompt,
                str(record["slot_type"]),
                str(record["sequence_role"]),
                reference_item_ids,
            )
            repaired = True
        seen.add(_normalize_prompt(str(record["provider_prompt"])))
    return repaired


def _repair_summary_only_prompts(
    records: list[dict[str, Any]],
    summary_prompt: str,
    reference_item_ids: list[str],
) -> bool:
    summary_normalized = _normalize_prompt(summary_prompt)
    if not summary_normalized:
        return False
    repaired = False
    for record in records:
        prompt = str(record["provider_prompt"])
        normalized = _normalize_prompt(prompt)
        if normalized == summary_normalized or normalized in {
            f"{summary_normalized} cell {record['sequence_index']}",
            f"cell {record['sequence_index']} {summary_normalized}",
        }:
            record["provider_prompt"] = _fallback_prompt(
                summary_prompt,
                str(record["slot_type"]),
                str(record["sequence_role"]),
                reference_item_ids,
            )
            repaired = True
    return repaired


def _fallback_prompt(
    summary_prompt: str,
    slot_type: str,
    sequence_role: str,
    reference_item_ids: list[str],
) -> str:
    reference_text = (
        ", ".join(reference_item_ids) if reference_item_ids else "the shot reference bundle"
    )
    role_details = {
        "establishing": "wide establishing frame that clearly shows the scene layout, product position, and referenced characters before the action begins",
        "action": "medium action frame showing the main character movement and product interaction progressing from the established setup",
        "detail": "close detail frame emphasizing the product use, gesture, interface, expression, or branded interaction while preserving the same scene",
        "payoff": "hero payoff frame resolving the beat with a readable product result, character reaction, and transition-ready composition",
    }
    role_detail = role_details.get(sequence_role, f"{sequence_role} frame")
    return (
        f"{sequence_role.title()} full-frame keyframe for {slot_type}: {role_detail}. "
        f"Shot summary: {summary_prompt}. Use reference items {reference_text}. "
        "Preserve product identity, character identity, scene identity, style, lighting, and same-shot time continuity. "
        "Generate exactly one standalone full-frame keyframe with no layout annotations."
    )


def _slot_index(slot_type: str) -> int:
    try:
        return int(slot_type.removeprefix("shot_cell_"))
    except ValueError:
        return 1


def _normalize_prompt(value: str) -> str:
    return " ".join(value.lower().split())


def _dedupe_warnings(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        key = repr(sorted(value.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
