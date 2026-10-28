"""Structured method-identity validation for the exact supplied catalog."""

from collections.abc import Mapping
from typing import Any

from app.schemas.agent_runtime import StructuredViolation


def creative_method_option_violations(
    context: Mapping[str, Any], value: Mapping[str, Any]
) -> tuple[StructuredViolation, ...]:
    catalog = context.get("creative_method_catalog")
    supplied = (
        catalog is not None
        and context.get("capability_id") == "world_setting"
        and context.get("brand_decisions") is None
        and context.get("capability_context", {}).get("brand_decisions") is None
    )
    allowed = {item["skill_id"] for item in catalog} if supplied else set()
    seen: set[str] = set()
    violations: list[StructuredViolation] = []
    for index, option in enumerate(value.get("options", ())):
        method_id = option.get("creative_method_id")
        message = None
        if not supplied and "creative_method_id" in option:
            message = "Omit creative_method_id when no creative method catalog was supplied."
        elif supplied and (not isinstance(method_id, str) or method_id not in allowed):
            message = "Set creative_method_id to an exact skill_id in the supplied catalog."
        elif supplied and method_id in seen:
            message = "Each direction must use a different creative_method_id."
        if message is not None:
            violations.append(
                StructuredViolation(
                    code="creative_method_id_invalid",
                    message=message,
                    field_path=f"options.{index}.creative_method_id",
                )
            )
        if isinstance(method_id, str):
            seen.add(method_id)
    return tuple(violations)
