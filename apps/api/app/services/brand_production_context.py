"""Project reviewed content without rewriting prose or changing its source digest."""

from collections.abc import Mapping

from app.schemas.brand_professional_mode import BrandTreatmentDocumentV1
from app.schemas.brand_production_context import (
    BrandProductionContextV1,
    BrandProductionRoleV1,
    BrandProductionStepV1,
)


_ROLE_NAMES: dict[str, BrandProductionRoleV1] = {
    "product_design": "product",
    "product_main": "product",
    "product_multiview": "product",
    "prop_design": "product",
    "prop": "product",
    "product": "product",
    "character_design": "character",
    "character_main": "character",
    "character_turnaround": "character",
    "character": "character",
    "scene_design": "scene",
    "scene_board": "scene",
    "scene": "scene",
    "script_authoring": "script",
    "script": "script",
    "storyboard_design": "storyboard",
    "storyboard_grid": "storyboard",
    "storyboard": "storyboard",
    "video_direction": "video",
    "video_segment": "video",
    "video": "video",
    "bgm_direction": "bgm",
    "bgm": "bgm",
}
_ROLE_STEPS = {
    "product": frozenset({"hook", "story", "visual", "camera"}),
    "character": frozenset({"hook", "story", "character", "visual", "camera"}),
    "scene": frozenset({"hook", "story", "scene", "visual", "camera"}),
    "bgm": frozenset({"hook", "story", "editing", "sound"}),
}
# These constraints and product decisions apply even outside their owning role.
_SHARED_SECTIONS = frozenset({"boundaries", "prohibited_shots", "product_role", "product_shots"})
_COMMON_FIELDS = frozenset(
    {
        "brand_profile",
        "campaign_brief",
        "selected_hypothesis",
        "adspec",
        "skill_stack",
        "authorized_asset_references",
        "complete",
        "missing_sections",
        "execution_limitations",
    }
)


def project_brand_production_context(
    source: BrandTreatmentDocumentV1 | BrandProductionContextV1 | Mapping[str, object] | None,
    *,
    role: str,
) -> BrandProductionContextV1 | None:
    """Keep shared decisions and verbatim relevant sections; never widen a partial projection."""
    if source is None:
        return None
    if isinstance(source, Mapping):
        source = (
            BrandProductionContextV1.model_validate(source)
            if "projection_version" in source
            else BrandTreatmentDocumentV1.model_validate(source)
        )
    target = _ROLE_NAMES.get(role, "general")
    if isinstance(source, BrandProductionContextV1):
        for omitted in source.omitted_sections:
            step, _, section = omitted.partition(".")
            if _include(target, step, section):
                raise ValueError("Brand role projection requires reloading the reviewed snapshot.")
        steps = source.treatment_steps
        digest = source.source_content_digest
        omitted_sections = list(source.omitted_sections)
    else:
        steps = tuple(
            BrandProductionStepV1(
                step_key=step.step_key,
                selected_label=step.selected_label,
                sections=step.structured_detail.sections if step.structured_detail else (),
                legacy_detail=step.detail if step.structured_detail is None else None,
            )
            for step in source.treatment_steps
        )
        digest = source.content_digest
        omitted_sections = []
    projected = []
    for step in steps:
        sections = tuple(
            section for section in step.sections if _include(target, step.step_key, section.key)
        )
        omitted_sections.extend(
            f"{step.step_key}.{section.key}" for section in step.sections if section not in sections
        )
        # Unstructured historical prose has no safe section boundary to filter.
        if sections or step.legacy_detail is not None:
            projected.append(step.model_copy(update={"sections": sections}))
    return BrandProductionContextV1(
        **source.model_dump(include=_COMMON_FIELDS),
        source_content_digest=digest,
        role=target,
        treatment_steps=tuple(projected),
        omitted_sections=tuple(omitted_sections),
    )


def _include(role: BrandProductionRoleV1, step: str, section: str) -> bool:
    return role not in _ROLE_STEPS or step in _ROLE_STEPS[role] or section in _SHARED_SECTIONS
