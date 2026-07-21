from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.schemas.workflow_v2_style import (
    V2VisualStyleApplication,
    V2VisualStyleAudit,
    V2VisualStyleContract,
)


DEFAULT_V2_VISUAL_STYLE = V2VisualStyleContract(
    rendering_medium="detailed_semi_realistic_illustration",
    style_prompt=(
        "High-detail semi-realistic hand-drawn concept illustration, refined linework, "
        "realistic anatomy, carefully rendered facial features, detailed clothing folds and "
        "material textures, controlled cinematic lighting, sophisticated color grading, and a "
        "production-ready concept-art finish."
    ),
    negative_constraints=[
        "no photorealistic camera image",
        "no flat vector art",
        "no chibi proportions",
        "no low-detail children's cartoon",
        "no crude sketch",
        "no simplified anatomy",
        "no plastic 3D rendering",
    ],
    source="system_default",
)


class V2VisualStyleContractError(RuntimeError):
    code = "v2_visual_style_contract_failed"
    stage = "visual_style_integrity"

    def __init__(self, message: str, *, audit: V2VisualStyleAudit) -> None:
        super().__init__(message)
        self.audit = audit


class V2VisualStyleService:
    def resolve_for_planning(
        self,
        request: Any,
        *,
        intent_plan: Any | None = None,
        scoped_contract: V2VisualStyleContract | None = None,
    ) -> V2VisualStyleContract:
        if scoped_contract is not None:
            return scoped_contract
        explicit_style = _text(getattr(request, "visual_style", None))
        if explicit_style:
            return _contract_from_text(
                explicit_style,
                source="explicit_user",
                is_user_explicit=True,
            )

        inferred_style = _text(getattr(intent_plan, "visual_style", None))
        if inferred_style:
            return _contract_from_text(inferred_style, source="inferred")
        return DEFAULT_V2_VISUAL_STYLE.model_copy(deep=True)

    def resolve_slot_override(self, style_text: str) -> V2VisualStyleContract:
        return _contract_from_text(
            style_text,
            source="slot_user_override",
            is_user_explicit=True,
        )

    def resolve_for_slot(
        self,
        workflow: Any,
        item: Any,
        slot: Any,
        context: dict[str, Any] | None = None,
    ) -> V2VisualStyleContract:
        del item
        slot_contract = _contract_from_metadata(_metadata(slot).get("visual_style_contract"))
        if slot_contract is not None and slot_contract.source == "slot_user_override":
            return slot_contract

        workflow_contract = _contract_from_metadata(
            _metadata(workflow).get("visual_style_contract")
        )
        if workflow_contract is not None:
            return workflow_contract

        legacy_request_contract = _workflow_request_style_contract(_metadata(workflow))
        if legacy_request_contract is not None:
            return legacy_request_contract

        reference_contract = _reference_style_contract(context or {})
        if reference_contract is not None:
            return reference_contract.model_copy(
                update={"source": "selected_reference", "is_user_explicit": False}
            )
        return DEFAULT_V2_VISUAL_STYLE.model_copy(deep=True)

    def apply_to_provider_prompt(
        self,
        *,
        slot_type: str,
        provider_prompt: str | None,
        negative_prompt: str | None,
        negative_constraints: str | None,
        contract: V2VisualStyleContract,
        reference_style_preserved: bool = False,
    ) -> V2VisualStyleApplication:
        prompt = _text(provider_prompt) or ""
        if not _is_visual_slot(slot_type):
            return V2VisualStyleApplication(
                provider_prompt=prompt,
                negative_prompt=_text(negative_prompt),
                negative_constraints=_text(negative_constraints),
                contract=contract,
                audit=_audit(
                    contract,
                    reference_style_preserved=reference_style_preserved,
                ),
            )

        positive_clause_added = not _contains_fragment(prompt, contract.style_prompt)
        if positive_clause_added:
            prompt = _append_clause(prompt, contract.style_prompt)
        if slot_type == "shot_video_segment":
            prompt = _append_clause(
                prompt,
                "Animate the supplied selected storyboard keyframes in the same rendering medium; "
                "do not convert them to live-action or photorealistic video without an explicit user override.",
            )

        sanitized_negative_prompt, removed_prompt = _sanitize_negative(
            negative_prompt,
            contract,
        )
        sanitized_constraints, removed_constraints = _sanitize_negative(
            negative_constraints,
            contract,
        )
        removed = _ordered_unique([*removed_prompt, *removed_constraints])
        unresolved = _unresolved_conflicts(
            [sanitized_negative_prompt, sanitized_constraints],
            contract,
        )
        audit = _audit(
            contract,
            positive_clause_added=positive_clause_added,
            removed_negative_fragments=removed,
            unresolved_conflicts=unresolved,
            reference_style_preserved=reference_style_preserved,
        )
        return V2VisualStyleApplication(
            provider_prompt=prompt,
            negative_prompt=sanitized_negative_prompt,
            negative_constraints=sanitized_constraints,
            contract=contract,
            audit=audit,
        )

    def validate_application(self, application: V2VisualStyleApplication) -> None:
        if application.audit.unresolved_conflicts:
            raise V2VisualStyleContractError(
                "Provider prompt contains an unresolved visual style contradiction.",
                audit=application.audit,
            )
        if _is_visual_slot_from_prompt(application.provider_prompt) and not _contains_fragment(
            application.provider_prompt,
            application.contract.style_prompt,
        ):
            raise V2VisualStyleContractError(
                "Provider prompt is missing the effective visual style clause.",
                audit=application.audit,
            )


def _contract_from_text(
    style_text: str,
    *,
    source: str,
    is_user_explicit: bool = False,
) -> V2VisualStyleContract:
    normalized = style_text.strip()
    return V2VisualStyleContract(
        rendering_medium=_rendering_medium(normalized),
        style_prompt=normalized,
        negative_constraints=[],
        source=source,  # type: ignore[arg-type]
        source_text=normalized,
        is_user_explicit=is_user_explicit,
    )


def _rendering_medium(style_text: str) -> str:
    normalized = style_text.casefold()
    if "comic" in normalized:
        return "comic_illustration"
    if "watercolor" in normalized or "watercolour" in normalized:
        return "watercolor_illustration"
    if "3d" in normalized or "three-dimensional" in normalized:
        return "three_dimensional"
    if "photorealistic" in normalized or "photographic" in normalized:
        return "photorealistic"
    if "illustration" in normalized or "illustrated" in normalized:
        return "illustration"
    return "custom"


def _contract_from_metadata(value: object) -> V2VisualStyleContract | None:
    if not isinstance(value, dict):
        return None
    try:
        return V2VisualStyleContract.model_validate(value)
    except ValueError:
        return None


def _metadata(value: Any) -> dict[str, Any]:
    metadata = getattr(value, "metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def _reference_style_contract(context: dict[str, Any]) -> V2VisualStyleContract | None:
    direct = _contract_from_metadata(context.get("selected_reference_visual_style_contract"))
    if direct is not None:
        return direct
    references = (
        context.get("reference_asset_summaries") or context.get("selected_references") or []
    )
    if not isinstance(references, Iterable) or isinstance(references, (str, bytes, dict)):
        return None
    for reference in references:
        if not isinstance(reference, dict):
            continue
        contract = _contract_from_metadata(reference.get("visual_style_contract"))
        if contract is not None:
            return contract
        metadata = reference.get("metadata")
        if isinstance(metadata, dict):
            contract = _contract_from_metadata(metadata.get("visual_style_contract"))
            if contract is not None:
                return contract
    return None


def _workflow_request_style_contract(
    workflow_metadata: dict[str, Any],
) -> V2VisualStyleContract | None:
    request = workflow_metadata.get("request")
    if not isinstance(request, dict):
        return None
    explicit_style = _text(request.get("visual_style"))
    if explicit_style is None:
        return None
    return _contract_from_text(
        explicit_style,
        source="explicit_user",
        is_user_explicit=True,
    )


def _is_visual_slot(slot_type: str) -> bool:
    return slot_type not in {"bgm_audio", "final_video", "final_composition"}


def _is_visual_slot_from_prompt(provider_prompt: str) -> bool:
    return bool(provider_prompt)


def _append_clause(prompt: str, clause: str) -> str:
    if _contains_fragment(prompt, clause):
        return prompt
    return f"{prompt.rstrip()} {clause}".strip()


def _contains_fragment(text: str, fragment: str) -> bool:
    return fragment.casefold() in text.casefold()


def _sanitize_negative(
    value: str | None,
    contract: V2VisualStyleContract,
) -> tuple[str | None, list[str]]:
    text = _text(value)
    if text is None:
        return None, []
    fragments = [fragment.strip() for fragment in re.split(r"[;\n]+", text) if fragment.strip()]
    retained: list[str] = []
    removed: list[str] = []
    for fragment in fragments:
        if _is_recoverable_conflict(fragment, contract):
            removed.append(fragment)
        else:
            retained.append(fragment)
    return "; ".join(retained) or None, removed


def _is_recoverable_conflict(fragment: str, contract: V2VisualStyleContract) -> bool:
    normalized = fragment.casefold()
    if "low-detail" in normalized or "children" in normalized:
        return False
    if contract.rendering_medium in {"comic_illustration", "illustration"}:
        return bool(
            re.search(r"\b(no|avoid|without)\b.*\b(comic|illustration|cartoonish)\b", normalized)
        )
    if contract.rendering_medium == "photorealistic":
        return bool(re.search(r"\b(no|avoid|without)\b.*\b(photo|photorealistic)\b", normalized))
    return False


def _unresolved_conflicts(
    negative_values: list[str | None],
    contract: V2VisualStyleContract,
) -> list[str]:
    combined = "; ".join(value for value in negative_values if value).casefold()
    if contract.rendering_medium in {"comic_illustration", "illustration"}:
        if "photorealistic rendering only" in combined or "live-action only" in combined:
            return ["negative prompt requires a photorealistic or live-action-only rendering"]
    if contract.rendering_medium == "photorealistic" and "illustration only" in combined:
        return ["negative prompt requires illustration-only rendering"]
    return []


def _audit(
    contract: V2VisualStyleContract,
    *,
    positive_clause_added: bool = False,
    removed_negative_fragments: list[str] | None = None,
    unresolved_conflicts: list[str] | None = None,
    reference_style_preserved: bool = False,
) -> V2VisualStyleAudit:
    return V2VisualStyleAudit(
        contract_hash=contract.contract_hash(),
        effective_source=contract.source,
        positive_clause_added=positive_clause_added,
        removed_negative_fragments=removed_negative_fragments or [],
        unresolved_conflicts=unresolved_conflicts or [],
        reference_style_preserved=reference_style_preserved,
    )


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
