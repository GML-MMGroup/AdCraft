"""Immutable, versioned role-reference policy for Agent Canvas providers."""

from __future__ import annotations

from collections import Counter
from types import MappingProxyType

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_role_prompt_preparation import RolePromptVariantV2
from app.schemas.agent_canvas_role_reference_policy import (
    RoleReferencePolicyV1,
    RoleReferenceRuleV1,
    RoleReferenceTargetV1,
)


_POLICY_VERSION = "agent_canvas_role_reference_policy_v1"


def _rule(
    source_role: str,
    media_kind: str,
    minimum: int,
    maximum: int,
    *,
    required: bool,
    required_when_active: bool = False,
    default_included: bool = True,
    canonical_order: int,
) -> RoleReferenceRuleV1:
    return RoleReferenceRuleV1(
        source_role=source_role,
        media_kind=media_kind,
        minimum=minimum,
        maximum=maximum,
        required=required,
        required_when_active=required_when_active,
        default_included=default_included,
        canonical_order=canonical_order,
    )


_POLICIES: dict[RoleReferenceTargetV1, RoleReferencePolicyV1] = {
    "product_multiview": RoleReferencePolicyV1(
        policy_version=_POLICY_VERSION,
        target_role="product_multiview",
        sources=(_rule("product_main", "image", 1, 1, required=True, canonical_order=0),),
    ),
    "character_turnaround": RoleReferencePolicyV1(
        policy_version=_POLICY_VERSION,
        target_role="character_turnaround",
        sources=(_rule("character_main", "image", 1, 1, required=True, canonical_order=0),),
    ),
    "storyboard_grid_1": RoleReferencePolicyV1(
        policy_version=_POLICY_VERSION,
        target_role="storyboard_grid_1",
        sources=(
            _rule(
                "character_turnaround",
                "image",
                0,
                1,
                required=False,
                required_when_active=True,
                canonical_order=0,
            ),
            _rule("scene_board", "image", 1, 1, required=True, canonical_order=1),
        ),
    ),
    "storyboard_grid_n": RoleReferencePolicyV1(
        policy_version=_POLICY_VERSION,
        target_role="storyboard_grid_n",
        sources=(
            _rule("storyboard_grid_1", "image", 1, 1, required=True, canonical_order=0),
            _rule(
                "character_turnaround",
                "image",
                0,
                1,
                required=False,
                required_when_active=True,
                canonical_order=1,
            ),
            _rule("scene_board", "image", 1, 1, required=True, canonical_order=2),
        ),
    ),
    "storyboard_video": RoleReferencePolicyV1(
        policy_version=_POLICY_VERSION,
        target_role="storyboard_video",
        sources=(
            _rule("storyboard_grid", "image", 1, 1, required=True, canonical_order=0),
            _rule("product_multiview", "image", 1, 1, required=True, canonical_order=1),
            _rule("prop", "image", 0, 64, required=False, canonical_order=2),
            _rule(
                "character_turnaround",
                "image",
                0,
                1,
                required=False,
                required_when_active=True,
                canonical_order=3,
            ),
            _rule("scene_board", "image", 1, 1, required=True, canonical_order=4),
        ),
    ),
    "bgm": RoleReferencePolicyV1(
        policy_version=_POLICY_VERSION,
        target_role="bgm",
        sources=(),
    ),
    "editing": RoleReferencePolicyV1(
        policy_version=_POLICY_VERSION,
        target_role="editing",
        sources=(
            _rule("video_segment", "video", 1, 64, required=True, canonical_order=0),
            _rule(
                "bgm",
                "audio",
                0,
                1,
                required=False,
                required_when_active=True,
                canonical_order=1,
            ),
        ),
    ),
}

_POLICY_BY_ROLE = MappingProxyType(_POLICIES)

_CAPABILITY_TARGETS: MappingProxyType[CapabilityIdV1, RoleReferenceTargetV1] = MappingProxyType(
    {
        "storyboard_design": "storyboard_grid_1",
        "video_direction": "storyboard_video",
        "bgm_direction": "bgm",
    }
)

_PROMPT_TARGETS: MappingProxyType[RolePromptVariantV2, RoleReferenceTargetV1] = MappingProxyType(
    {
        "product_multiview": "product_multiview",
        "character_turnaround": "character_turnaround",
        "storyboard_grid": "storyboard_grid_1",
        "video_segment": "storyboard_video",
        "bgm": "bgm",
    }
)


class AgentCanvasRoleReferencePolicyService:
    """Resolve and validate one closed policy without mutable runtime state."""

    policy_version = _POLICY_VERSION

    def resolve(self, target_role: RoleReferenceTargetV1) -> RoleReferencePolicyV1:
        try:
            return _POLICY_BY_ROLE[target_role]
        except KeyError as error:
            raise self._error(
                "role_reference_policy_unknown", "Role reference target is unknown."
            ) from error

    def for_capability(self, capability_id: CapabilityIdV1) -> RoleReferencePolicyV1 | None:
        target = _CAPABILITY_TARGETS.get(capability_id)
        return self.resolve(target) if target is not None else None

    def for_prompt_variant(self, role_variant: RolePromptVariantV2) -> RoleReferencePolicyV1 | None:
        target = _PROMPT_TARGETS.get(role_variant)
        return self.resolve(target) if target is not None else None

    def validate(
        self,
        target_role: RoleReferenceTargetV1,
        source_roles: tuple[str, ...],
        *,
        include_optional: bool = True,
    ) -> tuple[str, ...]:
        policy = self.resolve(target_role)
        counts = Counter(source_roles)
        errors: list[str] = []
        for source_role in counts:
            rule = policy.rule_for(source_role)
            if rule is None:
                errors.append(f"unknown_source:{source_role}")
                continue
            if counts[source_role] > rule.maximum:
                errors.append(f"cardinality_exceeded:{source_role}")
        for rule in policy.sources:
            if rule.required and counts[rule.source_role] < rule.minimum:
                errors.append(f"required_reference_missing:{rule.source_role}")
            elif (
                include_optional
                and rule.required_when_active
                and counts[rule.source_role] > rule.maximum
            ):
                errors.append(f"cardinality_exceeded:{rule.source_role}")
        return tuple(errors)

    def require(
        self,
        target_role: RoleReferenceTargetV1,
        source_roles: tuple[str, ...],
    ) -> None:
        errors = self.validate(target_role, source_roles)
        if errors:
            raise self._error(
                "role_reference_policy_invalid",
                "Role references do not satisfy the authoritative policy.",
                details={"policy_version": self.policy_version, "violations": list(errors)},
            )

    @staticmethod
    def _error(
        code: str, message: str, *, details: dict[str, object] | None = None
    ) -> V2PersistenceError:
        error = V2PersistenceError(code, message, stage="agent_canvas_role_reference_policy")
        if details:
            error.details = details
        return error
