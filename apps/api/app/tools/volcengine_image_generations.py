from __future__ import annotations

from typing import Any

from app.services.v2_provider_reference_input_delivery import (
    V2ProviderReferenceWireAudit,
    is_provider_compatible_model_input,
)


class V2ProviderRequestContractError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        stage: str,
        message: str,
        audit: V2ProviderReferenceWireAudit,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.audit = audit


def serialize_volcengine_image_generation_request(
    *,
    model: str,
    canonical_prompt: str,
    size: str,
    references: list[dict[str, Any]],
    required_reference_asset_ids: list[str],
    response_format: str = "url",
    watermark: bool = False,
) -> tuple[dict[str, Any], V2ProviderReferenceWireAudit]:
    required_asset_ids = _ordered_unique(required_reference_asset_ids)
    audit = V2ProviderReferenceWireAudit(
        requested_reference_asset_ids=required_asset_ids,
        request_schema="volcengine-image-generations",
    )
    body: dict[str, Any] = {
        "model": model,
        "prompt": canonical_prompt,
        "response_format": response_format,
        "size": size,
        "watermark": watermark,
        "sequential_image_generation": "disabled",
    }
    _validate_base_body(body, canonical_prompt=canonical_prompt, audit=audit)

    serialized_values: list[str] = []
    serialized_asset_ids: list[str] = []
    seen_asset_ids: set[str] = set()
    for reference in references:
        asset_id = str(reference.get("asset_id") or "").strip()
        if not asset_id or asset_id in seen_asset_ids:
            if asset_id:
                audit.warnings.append("duplicate_reference_asset_id_deduplicated")
            continue
        seen_asset_ids.add(asset_id)
        value = _reference_input_value(reference)
        if not value or not is_provider_compatible_model_input(value):
            audit.warnings.append(
                "required_reference_value_invalid"
                if asset_id in required_asset_ids
                else "optional_reference_value_invalid"
            )
            continue
        serialized_asset_ids.append(asset_id)
        serialized_values.append(value)

    audit = audit.model_copy(update={"delivered_reference_asset_ids": list(serialized_asset_ids)})
    missing_required = [
        asset_id for asset_id in required_asset_ids if asset_id not in serialized_asset_ids
    ]
    if missing_required:
        raise _reference_error(
            "A required prepared reference is missing from the provider request.",
            audit,
        )

    audit = audit.model_copy(
        update={
            "serialized_reference_asset_ids": list(serialized_asset_ids),
            "provider_request_field": "image" if serialized_values else None,
            "provider_request_reference_count": len(serialized_values),
        }
    )
    if len(serialized_values) == 1:
        body["image"] = serialized_values[0]
    elif serialized_values:
        body["image"] = serialized_values
    _validate_final_body(
        body,
        canonical_prompt=canonical_prompt,
        required_reference_asset_ids=required_asset_ids,
        audit=audit,
    )
    return body, audit


def _validate_base_body(
    body: dict[str, Any],
    *,
    canonical_prompt: str,
    audit: V2ProviderReferenceWireAudit,
) -> None:
    if not all(isinstance(body.get(key), str) and body[key].strip() for key in ("model", "size")):
        raise _contract_error("Volcengine image request requires model and size.", audit)
    if not canonical_prompt.strip() or body.get("prompt") != canonical_prompt:
        raise _contract_error(
            "Volcengine image request prompt must match the canonical prompt.", audit
        )
    if body.get("sequential_image_generation") != "disabled":
        raise _contract_error("V2 image slots must disable sequential image generation.", audit)


def _validate_final_body(
    body: dict[str, Any],
    *,
    canonical_prompt: str,
    required_reference_asset_ids: list[str],
    audit: V2ProviderReferenceWireAudit,
) -> None:
    _validate_base_body(body, canonical_prompt=canonical_prompt, audit=audit)
    if "references" in body or "context" in body:
        raise _contract_error("Volcengine image request leaked an internal field.", audit)
    image = body.get("image")
    if image is None:
        if required_reference_asset_ids:
            raise _reference_error(
                "A required prepared reference is missing from the provider request.", audit
            )
        return
    values = [image] if isinstance(image, str) else image if isinstance(image, list) else []
    if not values or any(
        not isinstance(value, str) or not is_provider_compatible_model_input(value)
        for value in values
    ):
        raise _contract_error("Volcengine image request contains an invalid image value.", audit)
    if len(values) != audit.provider_request_reference_count:
        raise _reference_error(
            "Volcengine image request did not serialize every prepared reference exactly once.",
            audit,
        )


def _reference_input_value(reference: dict[str, Any]) -> str:
    for key in ("provider_input_value", "model_input_value"):
        value = reference.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _reference_error(
    message: str,
    audit: V2ProviderReferenceWireAudit,
) -> V2ProviderRequestContractError:
    return V2ProviderRequestContractError(
        code="v2_provider_reference_serialization_failed",
        stage="provider_request_serialization",
        message=message,
        audit=audit,
    )


def _contract_error(
    message: str,
    audit: V2ProviderReferenceWireAudit,
) -> V2ProviderRequestContractError:
    return V2ProviderRequestContractError(
        code="v2_provider_request_contract_invalid",
        stage="provider_request_validation",
        message=message,
        audit=audit,
    )


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in (str(raw).strip() for raw in values) if value))
