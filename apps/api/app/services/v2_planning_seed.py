from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.workflow_v2_intent import (
    V2FrontDeskPlanningSeed,
    V2PlanningCountFact,
    V2PlanningInventoryFact,
    V2PlanningProductFact,
    V2PlanningSource,
    V2ExplicitCharacterConstraint,
    V2ExplicitConstraints,
)

if TYPE_CHECKING:
    from app.schemas.workflow_v2 import WorkflowV2PlanFromPromptRequest


def build_v2_planning_seed(
    request: AdWorkflowGenerateRequest,
) -> V2FrontDeskPlanningSeed:
    """Build the minimum authoritative seed available from a typed Front Desk request."""
    return V2FrontDeskPlanningSeed(
        product=V2PlanningProductFact(
            state="explicit",
            identity=request.product_name,
            description=request.product_description,
            source=V2PlanningSource(
                origin="structured_request",
                source_span="product_name",
            ),
        ),
        characters=V2PlanningInventoryFact(state="unspecified"),
        scenes=V2PlanningInventoryFact(state="unspecified"),
        storyboard_shot_count=V2PlanningCountFact(state="unspecified"),
    )


@dataclass(frozen=True)
class V2PlanningSeedValidation:
    seed: V2FrontDeskPlanningSeed
    violations: list[dict[str, str]]


@dataclass(frozen=True)
class V2PlanningSeedCanonicalization:
    seed: V2FrontDeskPlanningSeed
    warnings: list[dict[str, str]]


def canonicalize_v2_planning_seed(
    raw_seed: V2FrontDeskPlanningSeed | None,
    request: WorkflowV2PlanFromPromptRequest,
) -> V2PlanningSeedCanonicalization:
    """Build a strict, non-blocking seed from typed request data and verified facts."""
    product = _typed_product_fact(request)
    warnings: list[dict[str, str]] = []
    if raw_seed is None:
        return V2PlanningSeedCanonicalization(
            seed=V2FrontDeskPlanningSeed(
                product=product,
                characters=V2PlanningInventoryFact(state="unspecified"),
                scenes=V2PlanningInventoryFact(state="unspecified"),
                storyboard_shot_count=V2PlanningCountFact(state="unspecified"),
            ),
            warnings=warnings,
        )

    if raw_seed.product != product:
        warnings.append(_violation("product", "planning_seed_typed_fact_restored"))
    characters = _canonical_inventory_fact(raw_seed.characters, "characters", request, warnings)
    scenes = _canonical_inventory_fact(raw_seed.scenes, "scenes", request, warnings)
    shots = _canonical_count_fact(raw_seed.storyboard_shot_count, request, warnings)
    return V2PlanningSeedCanonicalization(
        seed=V2FrontDeskPlanningSeed(
            product=product,
            characters=characters,
            scenes=scenes,
            storyboard_shot_count=shots,
        ),
        warnings=warnings[:30],
    )


def validate_v2_planning_seed(
    seed: V2FrontDeskPlanningSeed,
    request: WorkflowV2PlanFromPromptRequest,
) -> V2PlanningSeedValidation:
    """Return the canonical seed through the established validation interface."""
    canonicalization = canonicalize_v2_planning_seed(seed, request)
    return V2PlanningSeedValidation(
        seed=canonicalization.seed,
        violations=canonicalization.warnings,
    )


def _typed_product_fact(
    request: WorkflowV2PlanFromPromptRequest,
) -> V2PlanningProductFact:
    metadata_request = request.metadata.get("front_desk_ad_request")
    metadata = metadata_request if isinstance(metadata_request, dict) else {}
    identity = request.product_name or _optional_text(metadata.get("product_name"))
    description = _optional_text(metadata.get("product_description"))
    if identity is None:
        return V2PlanningProductFact(state="unspecified")
    return V2PlanningProductFact(
        state="explicit",
        identity=identity,
        description=description,
        source=V2PlanningSource(origin="structured_request", source_span="product_name"),
    )


def _canonical_inventory_fact(
    fact: V2PlanningInventoryFact,
    field_path: str,
    request: WorkflowV2PlanFromPromptRequest,
    warnings: list[dict[str, str]],
) -> V2PlanningInventoryFact:
    if fact.state == "explicit" and _source_is_valid(fact.source, fact.requested_count, request):
        return fact
    if fact.state != "unspecified":
        warnings.append(_violation(field_path, "planning_seed_optional_fact_dropped"))
    return V2PlanningInventoryFact(state="unspecified")


def _canonical_count_fact(
    fact: V2PlanningCountFact,
    request: WorkflowV2PlanFromPromptRequest,
    warnings: list[dict[str, str]],
) -> V2PlanningCountFact:
    if fact.state == "explicit" and _source_is_valid(fact.source, fact.value, request):
        return fact
    if fact.state != "unspecified":
        warnings.append(_violation("storyboard_shot_count", "planning_seed_optional_fact_dropped"))
    return V2PlanningCountFact(state="unspecified")


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def merge_v2_planning_seed_constraints(
    constraints: V2ExplicitConstraints,
    seed: V2FrontDeskPlanningSeed,
) -> V2ExplicitConstraints:
    """Apply validated Front Desk facts ahead of scanner-derived constraints."""
    payload = constraints.model_dump(mode="python")
    if seed.product.state == "explicit" and seed.product.identity:
        payload["product_name"] = seed.product.identity
        payload["product_source_span"] = _user_message_span(seed.product.source)
    if seed.characters.state == "explicit" and seed.characters.requested_count is not None:
        payload["character_count"] = seed.characters.requested_count
        payload["characters"] = [
            V2ExplicitCharacterConstraint(source_span=_user_message_span(seed.characters.source))
            for _ in range(seed.characters.requested_count)
        ]
    if seed.scenes.state == "explicit" and seed.scenes.requested_count is not None:
        payload["scene_count"] = seed.scenes.requested_count
        payload["scenes"] = []
    if seed.storyboard_shot_count.state == "explicit":
        payload["storyboard_shot_count"] = seed.storyboard_shot_count.value
        payload["storyboard_shot_count_span"] = _user_message_span(
            seed.storyboard_shot_count.source
        )
    return V2ExplicitConstraints.model_validate(payload)


def _source_is_valid(
    source: V2PlanningSource | None,
    value: object,
    request: WorkflowV2PlanFromPromptRequest,
) -> bool:
    if source is None:
        return False
    if source.origin == "user_message":
        return bool(source.source_span and source.source_span in request.prompt)
    if source.origin == "structured_request":
        if source.source_span == "product_name":
            return bool(request.product_name and value == request.product_name)
        return (
            source.source_span == "requested_shot_count" and value == request.requested_shot_count
        )
    if source.origin == "input_asset":
        asset_ids = {
            str(asset.asset_id)
            for asset in [*request.selected_assets, *request.asset_references]
            if getattr(asset, "asset_id", None)
        }
        return bool(source.source_span and source.source_span in asset_ids)
    return False


def _user_message_span(source: V2PlanningSource | None) -> str | None:
    if source is None or source.origin != "user_message":
        return None
    return source.source_span


def _violation(field_path: str, code: str) -> dict[str, str]:
    return {"field_path": field_path, "code": code}
