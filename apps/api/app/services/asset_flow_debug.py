from __future__ import annotations

from typing import Any


USER_EXPLAINABLE_REASONS = {
    "prompt_optimizer_not_supported": (
        "Prompt optimizer is not configured or supported for this node, so media generation did not start."
    ),
    "strict_reference_not_supported": (
        "The selected model cannot use this reference image as a strict reference. "
        "Use prompt-only mode or switch provider."
    ),
    "product_reference_provider_unsupported": (
        "The selected model cannot use the product reference as a strict provider reference."
    ),
    "provider_reference_type_unsupported": (
        "The reference asset type is not directly supported by this provider, but it can remain prompt context."
    ),
    "provider_attempts_empty": "No provider satisfied the current constraints, so no model was called.",
    "provider_attempts_failed": "Provider was called but returned a failure.",
    "output_assets_empty": "Provider returned success but no media asset could be registered.",
    "persistence_failed": "Media was generated but the node result could not be persisted.",
}


def build_asset_flow_debug(
    *,
    input_references: list[dict[str, Any]] | None = None,
    display_assets: list[dict[str, Any]] | None = None,
    prompt_context_assets: list[dict[str, Any]] | None = None,
    provider_reference_assets: list[dict[str, Any]] | None = None,
    prompt_only_assets: list[dict[str, Any]] | None = None,
    rejected_assets: list[dict[str, Any]] | None = None,
    provider_attempts: list[dict[str, Any]] | None = None,
    selected_provider: str | None = None,
    failure_stage: str = "none",
    user_explainable_reason: str | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "input_reference_count": len(input_references or []),
        "display_asset_count": len(display_assets or []),
        "prompt_context_asset_count": len(prompt_context_assets or []),
        "provider_reference_asset_count": len(provider_reference_assets or []),
        "prompt_only_asset_count": len(prompt_only_assets or []),
        "rejected_reference_count": len(rejected_assets or []),
        "provider_attempt_count": len(provider_attempts or []),
        "selected_provider": selected_provider,
        "failure_stage": failure_stage,
        "user_explainable_reason": user_explainable_reason
        or explain_asset_flow_failure(_reason_code_from_stage(failure_stage)),
        "warnings": warnings or [],
    }


def explain_asset_flow_failure(code: str | None) -> str:
    if not code:
        return ""
    return USER_EXPLAINABLE_REASONS.get(str(code), str(code))


def debug_from_reference_policy(
    *,
    input_references: list[dict[str, Any]],
    policy: dict[str, Any],
    selected_provider: str | None = None,
    provider_attempts: list[dict[str, Any]] | None = None,
    failure_stage: str = "none",
) -> dict[str, Any]:
    reason_code = _first_issue_code(policy) or _reason_code_from_stage(failure_stage)
    return build_asset_flow_debug(
        input_references=input_references,
        display_assets=input_references,
        prompt_context_assets=policy.get("prompt_only_assets") or [],
        provider_reference_assets=policy.get("accepted_assets") or [],
        prompt_only_assets=policy.get("prompt_only_assets") or [],
        rejected_assets=policy.get("rejected_assets") or [],
        provider_attempts=provider_attempts or [],
        selected_provider=selected_provider or policy.get("provider"),
        failure_stage=failure_stage,
        user_explainable_reason=explain_asset_flow_failure(reason_code),
        warnings=policy.get("warnings") or [],
    )


def _first_issue_code(policy: dict[str, Any]) -> str:
    for key in ("errors", "warnings"):
        issues = policy.get(key)
        if isinstance(issues, list):
            for issue in issues:
                if isinstance(issue, dict) and issue.get("code"):
                    return str(issue["code"])
    return ""


def _reason_code_from_stage(stage: str) -> str:
    return {
        "prompt_optimizer": "prompt_optimizer_not_supported",
        "provider_selection": "provider_attempts_empty",
        "provider_call": "provider_attempts_failed",
        "output_contract": "output_assets_empty",
        "persistence": "persistence_failed",
    }.get(stage, "")
