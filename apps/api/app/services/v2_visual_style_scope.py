from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2 import WorkflowV2
from app.schemas.workflow_v2_style import (
    VisualStyleScopeRepairMode,
    VisualStyleScopeSource,
    VisualStyleScopeStatus,
    V2VisualStyleContract,
    V2VisualStyleResolution,
    V2VisualStyleScopeAudit,
    V2VisualStyleScopeRepairOutput,
)
from app.services.v2_high_risk_prompt_renderer import V2HighRiskPromptRenderer
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationRuntimeError,
    StructuredGenerationSpec,
)
from app.services.v2_visual_style import DEFAULT_V2_VISUAL_STYLE, V2VisualStyleService


_PRODUCT_SCOPE_SEMANTIC_PHRASES = (
    "recognizable",
    "recognisable",
    "recognizability",
    "recognisability",
    "packaging",
    "package design",
    "retail package",
    "retail box",
    "selling point",
    "selling points",
    "value proposition",
    "camera system",
    "camera module",
    "product feature",
    "product features",
    "product identity",
    "brand identity",
    "product interaction",
    "hold the product",
    "holding the product",
    "use the product",
    "using the product",
    "demonstrate the product",
    "demonstrating the product",
    "interact with the product",
    "interacting with the product",
    "product in use",
)


@dataclass(frozen=True)
class V2VisualStylePreflightResult:
    workflow: WorkflowV2
    changed: bool
    contract_repaired: bool
    audit: V2VisualStyleScopeAudit


class V2VisualStyleScopeService:
    """Separate reusable rendering direction from product identity evidence."""

    def __init__(
        self,
        visual_style_service: V2VisualStyleService | None = None,
        *,
        settings: Settings | None = None,
        structured_runtime: StructuredGenerationRuntime | None = None,
    ) -> None:
        self._visual_style_service = visual_style_service or V2VisualStyleService()
        self._settings = settings or get_settings()
        self._structured_runtime = structured_runtime

    def resolve_for_planning(
        self,
        *,
        raw_visual_style: str | None,
        product_name: str | None,
        product_identity_terms: Iterable[str] = (),
        inferred_visual_style: str | None = None,
    ) -> V2VisualStyleResolution:
        original_contract = self._contract_from_raw_style(
            raw_visual_style,
            inferred_visual_style=inferred_visual_style,
        )
        terms = _identity_terms(product_name, product_identity_terms)
        return self._resolve_contract_scope(
            original_contract=original_contract,
            product_name=product_name,
            terms=terms,
            source="planning",
            allow_structured_repair=True,
        )

    def repair_persisted_contract(
        self,
        workflow: WorkflowV2,
        *,
        source: VisualStyleScopeSource,
    ) -> V2VisualStylePreflightResult:
        """Repair workflow-level style metadata without model execution."""
        metadata = dict(workflow.metadata)
        original_contract = _workflow_style_contract(metadata)
        if original_contract is None:
            request = metadata.get("request")
            request_style = request.get("visual_style") if isinstance(request, dict) else None
            original_contract = self._contract_from_raw_style(request_style)
        resolution = self._resolve_contract_scope(
            original_contract=original_contract,
            product_name=_workflow_product_name(workflow),
            terms=_workflow_product_identity_terms(workflow),
            source=source,
            allow_structured_repair=False,
        )
        original_payload = metadata.get("visual_style_contract")
        contract_payload = resolution.contract.model_dump(mode="json")
        audit_payload = resolution.audit.model_dump(mode="json")
        contract_changed = original_payload != contract_payload
        existing_audit = _workflow_scope_audit(metadata)
        if (
            not contract_changed
            and existing_audit is not None
            and existing_audit.effective_contract_hash == resolution.contract.contract_hash()
        ):
            return V2VisualStylePreflightResult(
                workflow=workflow,
                changed=False,
                contract_repaired=False,
                audit=existing_audit,
            )
        audit_changed = metadata.get("visual_style_scope_audit") != audit_payload
        if not contract_changed and not audit_changed:
            return V2VisualStylePreflightResult(
                workflow=workflow,
                changed=False,
                contract_repaired=False,
                audit=resolution.audit,
            )
        repaired = workflow.model_copy(
            update={
                "metadata": {
                    **metadata,
                    "visual_style_contract": contract_payload,
                    "visual_style_scope_audit": audit_payload,
                }
            },
            deep=True,
        )
        return V2VisualStylePreflightResult(
            workflow=repaired,
            changed=True,
            contract_repaired=contract_changed,
            audit=resolution.audit,
        )

    def attach_product_constraints(
        self,
        expert_brief_plan: Any,
        *,
        product_name: str | None,
        product_identity_constraints: Iterable[str],
    ) -> Any:
        """Attach bounded scope evidence to the matching product brief only."""
        constraints = _bounded_constraints(product_identity_constraints)
        product_briefs = list(getattr(expert_brief_plan, "product_briefs", []) or [])
        if not constraints or not product_briefs:
            return expert_brief_plan

        target_index = _matching_product_brief_index(product_briefs, product_name)
        if target_index is None:
            return expert_brief_plan
        target = product_briefs[target_index]
        metadata = dict(getattr(target, "metadata", {}) or {})
        metadata["product_identity_constraints"] = constraints
        product_briefs[target_index] = target.model_copy(
            update={"metadata": metadata},
            deep=True,
        )
        return expert_brief_plan.model_copy(
            update={"product_briefs": product_briefs},
            deep=True,
        )

    def _resolve_contract_scope(
        self,
        *,
        original_contract: V2VisualStyleContract,
        product_name: str | None,
        terms: list[str],
        source: VisualStyleScopeSource,
        allow_structured_repair: bool,
    ) -> V2VisualStyleResolution:
        style_prompt, constraints = _separate_identity_clauses(
            original_contract.style_prompt,
            terms,
        )
        if not constraints:
            return _resolution(
                contract=original_contract,
                constraints=[],
                status="valid",
                repair_mode="none",
                source=source,
                original_contract_hash=original_contract.contract_hash(),
            )

        structured_error_code: str | None = None
        if allow_structured_repair:
            structured_resolution, structured_error_code = self._try_structured_repair(
                original_contract=original_contract,
                product_name=product_name,
                terms=terms,
                deterministic_constraints=constraints,
                source=source,
            )
            if structured_resolution is not None:
                return structured_resolution

        effective_style = style_prompt or _safe_style_for_medium(original_contract.rendering_medium)
        if structured_error_code is not None:
            effective_style = _safe_style_for_medium(original_contract.rendering_medium)
        effective_contract = original_contract.model_copy(
            update={
                "style_prompt": effective_style,
                "source_text": effective_style,
            }
        )
        return _resolution(
            contract=effective_contract,
            constraints=constraints,
            status="repaired",
            repair_mode="deterministic_fallback",
            source=source,
            original_contract_hash=original_contract.contract_hash(),
            structured_repair_error_code=structured_error_code,
        )

    def _try_structured_repair(
        self,
        *,
        original_contract: V2VisualStyleContract,
        product_name: str | None,
        terms: list[str],
        deterministic_constraints: list[str],
        source: VisualStyleScopeSource,
    ) -> tuple[V2VisualStyleResolution | None, str | None]:
        runtime = self._runtime_for_repair()
        if runtime is None:
            return None, None
        try:
            rendered = V2HighRiskPromptRenderer().render(
                prompt_id="v2.visual_style.scope_repair.v1",
                context={
                    "product_name": product_name or "Product",
                    "raw_visual_style": original_contract.style_prompt,
                    "identity_terms": terms,
                },
                identity={"path_kind": "normal"},
            )
            result = runtime.run(
                StructuredGenerationSpec(
                    stage_name="visual_style_scope_repair",
                    contract_name="V2VisualStyleScopeRepairOutput",
                    model_id=self._settings.llm_creative_model,
                    system_prompt=rendered.prompt_text,
                    input_payload={
                        "raw_visual_style": original_contract.style_prompt,
                        "product_name": product_name or "",
                        "product_identity_terms": terms,
                    },
                    output_model=V2VisualStyleScopeRepairOutput,
                    trace_metadata={
                        "prompt_registry_ref": rendered.prompt_registry_ref.model_dump(mode="json"),
                    },
                )
            )
            output = _repair_output(getattr(result, "output", result))
            if _contains_identity_term(
                output.rendering_style, terms
            ) or _contains_product_scope_semantics(output.rendering_style):
                raise ValueError("scope repair retained product semantics in rendering style")
            repaired_contract = self._visual_style_service.resolve_for_planning(
                SimpleNamespace(visual_style=output.rendering_style)
            ).model_copy(
                update={
                    "source": original_contract.source,
                    "source_text": output.rendering_style,
                    "is_user_explicit": original_contract.is_user_explicit,
                }
            )
            return (
                _resolution(
                    contract=repaired_contract,
                    constraints=(output.product_identity_constraints or deterministic_constraints),
                    status="repaired",
                    repair_mode="structured_repair",
                    source=source,
                    original_contract_hash=original_contract.contract_hash(),
                ),
                None,
            )
        except StructuredGenerationRuntimeError as exc:
            return None, _bounded_error_code(exc.code)
        except Exception:
            return None, "visual_style_scope_repair_invalid"

    def _runtime_for_repair(self) -> StructuredGenerationRuntime | None:
        if self._structured_runtime is not None:
            return self._structured_runtime
        if self._settings.agno_mock_mode or not (self._settings.llm_api_key or "").strip():
            return None
        return StructuredGenerationRuntime(settings=self._settings)

    def _contract_from_raw_style(
        self,
        raw_visual_style: str | None,
        *,
        inferred_visual_style: str | None = None,
    ) -> V2VisualStyleContract:
        return self._visual_style_service.resolve_for_planning(
            SimpleNamespace(visual_style=raw_visual_style),
            intent_plan=SimpleNamespace(visual_style=inferred_visual_style),
        )


def _resolution(
    *,
    contract: V2VisualStyleContract,
    constraints: list[str],
    status: VisualStyleScopeStatus,
    repair_mode: VisualStyleScopeRepairMode,
    source: VisualStyleScopeSource,
    original_contract_hash: str,
    structured_repair_error_code: str | None = None,
) -> V2VisualStyleResolution:
    normalized_constraints = _bounded_constraints(constraints)
    return V2VisualStyleResolution(
        contract=contract,
        product_identity_constraints=normalized_constraints,
        audit=V2VisualStyleScopeAudit(
            status=status,
            repair_mode=repair_mode,
            source=source,
            removed_scopes=["product_identity"] if normalized_constraints else [],
            original_contract_hash=original_contract_hash,
            effective_contract_hash=contract.contract_hash(),
            extracted_constraint_count=len(normalized_constraints),
            structured_repair_error_code=structured_repair_error_code,
        ),
    )


def _identity_terms(product_name: str | None, values: Iterable[str]) -> list[str]:
    terms = [product_name or "", *values]
    normalized: list[str] = []
    seen: set[str] = set()
    for value in terms:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if len(text) < 2:
            continue
        key = text.casefold()
        if key not in seen:
            normalized.append(text)
            seen.add(key)
    return normalized


def _matching_product_brief_index(
    product_briefs: list[Any], product_name: str | None
) -> int | None:
    expected = (product_name or "").strip().casefold()
    if expected:
        for index, brief in enumerate(product_briefs):
            display_name = str(getattr(brief, "display_name", "") or "").strip().casefold()
            if display_name == expected:
                return index
    return None


def _workflow_style_contract(metadata: dict[str, Any]) -> V2VisualStyleContract | None:
    value = metadata.get("visual_style_contract")
    if not isinstance(value, dict):
        return None
    try:
        return V2VisualStyleContract.model_validate(value)
    except ValueError:
        return None


def _workflow_scope_audit(metadata: dict[str, Any]) -> V2VisualStyleScopeAudit | None:
    value = metadata.get("visual_style_scope_audit")
    if not isinstance(value, dict):
        return None
    try:
        return V2VisualStyleScopeAudit.model_validate(value)
    except ValueError:
        return None


def _workflow_product_name(workflow: WorkflowV2) -> str | None:
    for node in workflow.nodes:
        for item in node.items:
            if item.item_type != "product":
                continue
            identity_spec = item.metadata.get("identity_spec")
            value = (
                str(identity_spec.get("product_name") or "").strip()
                if isinstance(identity_spec, dict)
                else ""
            )
            if value:
                return value
    request = workflow.metadata.get("request")
    if isinstance(request, dict):
        value = str(request.get("product_name") or "").strip()
        if value:
            return value
    for node in workflow.nodes:
        for item in node.items:
            if item.item_type != "product":
                continue
            value = str(item.display_name or "").strip()
            if value:
                return value
    return None


def _workflow_product_identity_terms(workflow: WorkflowV2) -> list[str]:
    terms: list[str] = []
    request = workflow.metadata.get("request")
    if isinstance(request, dict):
        terms.append(str(request.get("product_name") or ""))
    for node in workflow.nodes:
        for item in node.items:
            if item.item_type != "product":
                continue
            terms.append(item.display_name)
            identity_spec = item.metadata.get("identity_spec")
            if isinstance(identity_spec, dict):
                terms.append(str(identity_spec.get("product_name") or ""))
    return _identity_terms(None, terms)


def _separate_identity_clauses(style_text: str, terms: list[str]) -> tuple[str, list[str]]:
    clauses = [
        clause.strip(" ,;:-")
        for clause in re.split(r"(?<=[,;:.])\s+", style_text)
        if clause.strip(" ,;:-")
    ]
    identity_index = next(
        (index for index, clause in enumerate(clauses) if _contains_identity_term(clause, terms)),
        None,
    )
    if identity_index is None:
        return ", ".join(clauses), []
    constraint = ", ".join(clauses[identity_index:])
    constraint = re.sub(r"^(?:with|while|and)\s+", "", constraint, flags=re.IGNORECASE)
    return ", ".join(clauses[:identity_index]), _bounded_constraints([constraint])


def _contains_identity_term(value: str, terms: list[str]) -> bool:
    return any(_contains_ascii_lexical_phrase(value, term) for term in terms)


def _contains_product_scope_semantics(value: str) -> bool:
    return any(
        _contains_ascii_lexical_phrase(value, phrase) for phrase in _PRODUCT_SCOPE_SEMANTIC_PHRASES
    )


def _contains_ascii_lexical_phrase(value: str, phrase: str) -> bool:
    normalized_phrase = phrase.strip().casefold()
    if not normalized_phrase:
        return False
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(normalized_phrase)}(?![A-Za-z0-9_])")
    return pattern.search(value.casefold()) is not None


def _bounded_constraints(values: Iterable[str]) -> list[str]:
    constraints: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if not text:
            continue
        text = text[:500]
        key = text.casefold()
        if key not in seen:
            constraints.append(text)
            seen.add(key)
        if len(constraints) == 10:
            break
    return constraints


def _safe_style_for_medium(rendering_medium: str) -> str:
    templates = {
        "comic_illustration": (
            "Detailed comic illustration with refined linework and a polished commercial finish."
        ),
        "watercolor_illustration": (
            "Refined watercolor illustration with controlled color and a polished commercial finish."
        ),
        "three_dimensional": (
            "Detailed three-dimensional product visualization with controlled lighting and a "
            "polished commercial finish."
        ),
        "photorealistic": (
            "Polished photorealistic commercial rendering with controlled lighting and realistic "
            "materials."
        ),
        "illustration": (
            "Detailed editorial illustration with refined linework and a polished commercial finish."
        ),
    }
    return templates.get(rendering_medium, DEFAULT_V2_VISUAL_STYLE.style_prompt)


def _repair_output(value: Any) -> V2VisualStyleScopeRepairOutput:
    if isinstance(value, V2VisualStyleScopeRepairOutput):
        return value
    return V2VisualStyleScopeRepairOutput.model_validate(value)


def _bounded_error_code(value: str) -> str:
    normalized = value.strip().lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", normalized):
        return normalized[:120]
    return "visual_style_scope_repair_failed"
