from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.workflow_v2_specialist_ownership import (
    V2ProviderPromptCompilationResult,
    V2PromptContaminationCheckResult,
    V2PromptIsolationAudit,
    V2SlotPromptContext,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_provider_prompt_contracts import V2ProviderPromptContractService
from app.services.v2_prompt_registry import V2PromptRegistry
from app.services.v2_reference_audit import fingerprint_payload, slot_context_id


PROMPT_ISOLATION_ERROR_CODE = "v2_provider_prompt_context_contamination"


class V2ProviderPromptCompilerError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        audit: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.audit = audit
        self.payload = payload


class V2ProviderPromptCompiler:
    def __init__(
        self,
        *,
        contract_service: V2ProviderPromptContractService | None = None,
        prompt_registry: V2PromptRegistry | None = None,
    ) -> None:
        self._contract_service = contract_service or V2ProviderPromptContractService()
        self._prompt_registry = prompt_registry or V2PromptRegistry()

    def compile(
        self,
        context: V2SlotPromptContext,
        *,
        sibling_provider_prompts: list[str] | None = None,
        sibling_detail_prompts: list[str] | None = None,
    ) -> V2ProviderPromptCompilationResult:
        if not isinstance(context, V2SlotPromptContext):
            raise TypeError("V2ProviderPromptCompiler requires V2SlotPromptContext input.")

        contract_result = self._contract_service.compile_contract_prompt(
            slot_type=context.slot_type,
            media_type=_media_type_for_slot(context.slot_type),
            slot_prompt=context.own_provider_prompt,
            reference_asset_ids=list(context.reference_asset_ids),
        )
        contract_prompt = contract_result.provider_prompt
        contract_context = context.model_copy(update={"own_provider_prompt": contract_prompt})
        check = check_prompt_contamination(
            contract_context,
            sibling_provider_prompts=sibling_provider_prompts or [],
            sibling_detail_prompts=sibling_detail_prompts or [],
        )
        if not check.valid:
            audit = _audit_from_check(context, check, stage="slot_context")
            raise V2ProviderPromptCompilerError(
                check.error_code or PROMPT_ISOLATION_ERROR_CODE,
                _contamination_message(check),
                audit=audit,
            )

        slot_context_fingerprint = fingerprint_payload(_slot_context_fingerprint_payload(context))
        provider_prompt_fingerprint = fingerprint_payload(
            {
                "provider_prompt": contract_prompt,
                "negative_prompt": context.negative_prompt,
                "negative_constraints": context.negative_constraints,
                "reference_asset_ids": context.reference_asset_ids,
                "reference_version_ids": context.reference_version_ids,
            }
        )
        lineage = {
            "slot_context_id": slot_context_id(context),
            "slot_context_fingerprint": slot_context_fingerprint,
            "provider_prompt_fingerprint": provider_prompt_fingerprint,
            "allowed_reference_asset_ids": list(context.reference_asset_ids),
            "reference_version_ids": list(context.reference_version_ids),
            "dependency_asset_count": len(context.dependency_asset_summaries),
            "provider_prompt_contract_id": contract_result.provider_prompt_contract.get(
                "contract_id"
            ),
        }
        render_result = self._prompt_registry.render_result_for_provider_slot(
            slot_type=context.slot_type,
            provider_prompt=contract_prompt,
            render_context={
                "slot_context": context.model_dump(mode="json"),
                "provider_prompt_contract": contract_result.provider_prompt_contract,
            },
            workflow_id=context.workflow_id,
            node_id=context.node_id,
            item_id=context.item_id,
            slot_id=context.slot_id,
            media_type=_media_type_for_slot(context.slot_type),
            specialist=context.specialist,
            path_kind="normal",
        )
        prompt_registry_ref = render_result.prompt_registry_ref.model_dump(mode="json")
        prompt_lineage = self._prompt_registry.lineage_for_render(render_result).model_dump(
            mode="json"
        )
        prompt_content_profile = contract_result.provider_prompt_contract.get(
            "prompt_content_profile"
        )
        lineage.update(
            {
                "prompt_registry_ref": prompt_registry_ref,
                "prompt_lineage": prompt_lineage,
                "prompt_content_profile": prompt_content_profile,
            }
        )
        isolation_audit = _audit_from_check(
            context,
            check,
            stage="slot_context",
            own_prompt_fingerprint=provider_prompt_fingerprint,
        )
        return V2ProviderPromptCompilationResult(
            provider_prompt=contract_prompt,
            negative_prompt=context.negative_prompt,
            negative_constraints=context.negative_constraints,
            reference_asset_ids=list(context.reference_asset_ids),
            reference_version_ids=list(context.reference_version_ids),
            provider_payload_metadata={
                "slot_context_lineage": lineage,
                "slot_context_id": lineage["slot_context_id"],
                "slot_context_fingerprint": slot_context_fingerprint,
                "provider_prompt_fingerprint": provider_prompt_fingerprint,
                "prompt_registry_ref": prompt_registry_ref,
                "prompt_lineage": prompt_lineage,
                "prompt_content_profile": prompt_content_profile,
                "allowed_reference_asset_ids": list(context.reference_asset_ids),
                "forbidden_reference_asset_ids": [],
                "prompt_isolation_audit": isolation_audit,
                "prompt_contamination_check": check.model_dump(mode="json"),
                "provider_prompt_contract": contract_result.provider_prompt_contract,
                "continuity_sources": {
                    "campaign_summary": bool(context.campaign_summary),
                    "item_summary": bool(context.item_summary),
                    "reference_asset_ids": list(context.reference_asset_ids),
                    "reference_version_ids": list(context.reference_version_ids),
                    "dependency_asset_summaries": len(context.dependency_asset_summaries),
                },
            },
        )

    def validate_provider_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            audit = _audit_from_payload({}, valid=False, stage="provider_payload")
            audit["forbidden_evidence"] = ["provider_payload_not_dict"]
            raise V2ProviderPromptCompilerError(
                PROMPT_ISOLATION_ERROR_CODE,
                "V2 provider payload must be a dictionary.",
                audit=audit,
            )

        audit = _audit_from_payload(payload, valid=True, stage="provider_payload")
        existing_audit = payload.get("prompt_isolation_audit")
        evidence: list[str] = []
        if not isinstance(existing_audit, dict) or existing_audit.get("valid") is not True:
            evidence.append("missing_prompt_isolation_audit")
        evidence.extend(_forbidden_evidence_from_payload(payload))
        sanitized_payload = sanitize_context_for_llm_text(payload)
        evidence.extend(_forbidden_evidence_from_payload(sanitized_payload))
        evidence.extend(_sibling_slot_evidence_from_payload(sanitized_payload))
        evidence = _ordered_unique(evidence)
        if evidence:
            audit["valid"] = False
            audit["error_code"] = PROMPT_ISOLATION_ERROR_CODE
            audit["error_message"] = (
                "Provider prompt payload contains forbidden or missing isolation metadata."
            )
            audit["forbidden_evidence"] = evidence
            raise V2ProviderPromptCompilerError(
                PROMPT_ISOLATION_ERROR_CODE,
                _contamination_message(
                    V2PromptContaminationCheckResult(
                        valid=False,
                        error_code=PROMPT_ISOLATION_ERROR_CODE,
                        error_message=str(audit["error_message"]),
                        evidence=evidence,
                        forbidden_evidence=evidence,
                    )
                ),
                audit=audit,
                payload=sanitized_payload,
            )

        merged_audit = {
            **audit,
            **{
                key: value
                for key, value in existing_audit.items()
                if key not in {"valid", "stage", "serialized_payload_fingerprint"}
            },
            "valid": True,
            "stage": "provider_payload",
            "serialized_payload_fingerprint": fingerprint_payload(sanitized_payload),
            "forbidden_evidence": [],
        }
        return {
            **sanitized_payload,
            "prompt_isolation_audit": sanitize_context_for_llm_text(merged_audit),
        }


def check_prompt_contamination(
    context: V2SlotPromptContext,
    *,
    sibling_provider_prompts: list[str] | None = None,
    sibling_detail_prompts: list[str] | None = None,
) -> V2PromptContaminationCheckResult:
    serialized = json.dumps(context.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    prompt_source_text = _prompt_source_text(context)
    normalized = _normalize(serialized)
    evidence: list[str] = []

    evidence.extend(_forbidden_evidence_from_serialized(normalized))
    sibling_evidence: list[dict[str, Any]] = []
    for sibling in [*(sibling_provider_prompts or []), *(sibling_detail_prompts or [])]:
        snippet = _significant_snippet(sibling)
        if snippet and _normalize(snippet) in normalized:
            evidence.append(f"sibling_prompt:{snippet[:80]}")
            sibling_evidence.append(
                {
                    "fingerprint": fingerprint_payload({"prompt": sibling}),
                    "snippet": snippet[:80],
                }
            )

    sibling_slot_markers = _sibling_slot_markers(context.slot_type)
    for marker in sibling_slot_markers:
        if re.search(rf"\b{re.escape(marker)}\b", prompt_source_text):
            evidence.append(f"sibling_slot_id:{marker}")

    if evidence:
        evidence = _ordered_unique(evidence)
        return V2PromptContaminationCheckResult(
            valid=False,
            error_code=PROMPT_ISOLATION_ERROR_CODE,
            error_message="Provider prompt context contains forbidden or sibling prompt content.",
            evidence=evidence,
            forbidden_evidence=[
                item
                for item in evidence
                if not item.startswith("sibling_prompt:")
                and not item.startswith("sibling_slot_id:")
            ],
            sibling_prompt_fingerprint_evidence=sibling_evidence,
            own_prompt_fingerprint=fingerprint_payload(
                {
                    "provider_prompt": context.own_provider_prompt,
                    "negative_prompt": context.negative_prompt,
                    "negative_constraints": context.negative_constraints,
                }
            ),
            reference_asset_ids=list(context.reference_asset_ids),
        )
    return V2PromptContaminationCheckResult(
        valid=True,
        own_prompt_fingerprint=fingerprint_payload(
            {
                "provider_prompt": context.own_provider_prompt,
                "negative_prompt": context.negative_prompt,
                "negative_constraints": context.negative_constraints,
            }
        ),
        reference_asset_ids=list(context.reference_asset_ids),
    )


def _contamination_message(check: V2PromptContaminationCheckResult) -> str:
    message = check.error_message or "Provider prompt context contains forbidden content."
    if check.evidence:
        return f"{message} Evidence: {', '.join(check.evidence[:8])}"
    return message


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in (str(raw).strip() for raw in values) if value))


def _forbidden_patterns() -> dict[str, str]:
    return {
        "data:image/": "data:image/",
        "data:video/": "data:video/",
        "data:audio/": "data:audio/",
        ";base64,": ";base64,",
        "workflow_schema_version": "workflow_schema_version",
        '"nodes"': '"nodes"',
        '\\"nodes\\"': '"nodes"',
        '"edges"': '"edges"',
        '\\"edges\\"': '"edges"',
        '"runtime"': '"runtime"',
        '\\"runtime\\"': '"runtime"',
        "file_content": "file_content",
        "raw_bytes": "raw_bytes",
        "local file content": "local file content",
    }


def _forbidden_evidence_from_serialized(normalized_serialized: str) -> list[str]:
    evidence: list[str] = []
    for marker, label in _forbidden_patterns().items():
        if _normalize(marker) in normalized_serialized:
            evidence.append(label)
    return evidence


def _forbidden_evidence_from_payload(payload: dict[str, Any]) -> list[str]:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return _forbidden_evidence_from_serialized(_normalize(serialized))


def _sibling_slot_evidence_from_payload(payload: dict[str, Any]) -> list[str]:
    slot_type = str(payload.get("slot_type") or "")
    prompt_source_text = json.dumps(
        {
            "provider_prompt": payload.get("provider_prompt"),
            "summary_prompt": payload.get("summary_prompt"),
            "slot_prompt": payload.get("slot_prompt"),
            "detail_prompts": payload.get("detail_prompts"),
            "canonical_provider_payload": payload.get("canonical_provider_payload"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    evidence: list[str] = []
    for marker in _sibling_slot_markers(slot_type):
        if re.search(rf"\b{re.escape(marker)}\b", prompt_source_text):
            evidence.append(f"sibling_slot_id:{marker}")
    return evidence


def _audit_from_check(
    context: V2SlotPromptContext,
    check: V2PromptContaminationCheckResult,
    *,
    stage: str,
    own_prompt_fingerprint: str | None = None,
) -> dict[str, Any]:
    audit = V2PromptIsolationAudit(
        valid=check.valid,
        slot_id=context.slot_id,
        slot_type=context.slot_type,
        stage=stage,
        error_code=check.error_code,
        error_message=check.error_message,
        own_prompt_fingerprint=own_prompt_fingerprint or check.own_prompt_fingerprint,
        reference_asset_ids=list(context.reference_asset_ids),
        allowed_reference_asset_ids=list(context.reference_asset_ids),
        forbidden_evidence=list(check.forbidden_evidence or check.evidence),
        sibling_prompt_fingerprint_evidence=list(check.sibling_prompt_fingerprint_evidence),
    )
    return audit.model_dump(mode="json")


def _audit_from_payload(
    payload: dict[str, Any],
    *,
    valid: bool,
    stage: str,
) -> dict[str, Any]:
    audit = V2PromptIsolationAudit(
        valid=valid,
        slot_id=str(payload.get("slot_id") or "") or None,
        slot_type=str(payload.get("slot_type") or "") or None,
        stage=stage,
        own_prompt_fingerprint=str(payload.get("provider_prompt_fingerprint") or "")
        or fingerprint_payload(payload.get("provider_prompt")),
        serialized_payload_fingerprint=fingerprint_payload(payload),
        reference_asset_ids=[
            str(asset_id) for asset_id in payload.get("reference_asset_ids", []) if str(asset_id)
        ],
        allowed_reference_asset_ids=[
            str(asset_id)
            for asset_id in payload.get("allowed_reference_asset_ids", [])
            if str(asset_id)
        ],
        forbidden_evidence=[],
        sibling_prompt_fingerprint_evidence=[],
    )
    return audit.model_dump(mode="json")


def _significant_snippet(value: str) -> str | None:
    value = " ".join(str(value).split())
    if len(value) < 16:
        return None
    return value[:240]


def _prompt_source_text(context: V2SlotPromptContext) -> str:
    return json.dumps(
        {
            "own_summary_prompt": context.own_summary_prompt,
            "own_specialist_prompt": context.own_specialist_prompt,
            "own_provider_prompt": context.own_provider_prompt,
            "own_detail_prompts": context.own_detail_prompts,
            "negative_prompt": context.negative_prompt,
            "negative_constraints": context.negative_constraints,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _sibling_slot_markers(slot_type: str) -> list[str]:
    if slot_type.startswith("shot_cell_"):
        return [f"shot_cell_{index}" for index in range(1, 5) if f"shot_cell_{index}" != slot_type]
    return {
        "character_main_image": ["character_three_view"],
        "scene_main_image": ["scene_multi_view_grid"],
        "product_main_image": ["product_multi_view_grid"],
        "shot_video_segment": ["shot_cell_provider_prompt", "shot_cell_detail_prompt"],
        "bgm_audio": ["image provider prompt", "video provider prompt"],
    }.get(slot_type, [])


def _media_type_for_slot(slot_type: str) -> str:
    if slot_type == "bgm_audio":
        return "audio"
    if slot_type in {"shot_video_segment", "final_video"}:
        return "video"
    if slot_type == "free_output":
        return "image"
    return "image"


def _slot_context_fingerprint_payload(context: V2SlotPromptContext) -> dict[str, Any]:
    payload = context.model_dump(mode="json")
    return {
        "workflow_id": payload.get("workflow_id"),
        "node_id": payload.get("node_id"),
        "item_id": payload.get("item_id"),
        "slot_id": payload.get("slot_id"),
        "slot_type": payload.get("slot_type"),
        "specialist": payload.get("specialist"),
        "campaign_summary": payload.get("campaign_summary"),
        "item_summary": payload.get("item_summary"),
        "own_prompt_fingerprints": {
            "summary": fingerprint_payload(payload.get("own_summary_prompt")),
            "specialist": fingerprint_payload(payload.get("own_specialist_prompt")),
            "provider": fingerprint_payload(payload.get("own_provider_prompt")),
            "detail": fingerprint_payload(payload.get("own_detail_prompts")),
        },
        "negative_prompt_fingerprint": fingerprint_payload(payload.get("negative_prompt")),
        "negative_constraints_fingerprint": fingerprint_payload(
            payload.get("negative_constraints")
        ),
        "reference_asset_ids": payload.get("reference_asset_ids") or [],
        "reference_version_ids": payload.get("reference_version_ids") or [],
        "dependency_asset_summaries": payload.get("dependency_asset_summaries") or [],
        "lightweight_owner_labels": payload.get("lightweight_owner_labels") or {},
    }
