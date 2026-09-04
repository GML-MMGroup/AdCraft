"""Immutable, versioned role-reference policy for Agent Canvas providers."""

from __future__ import annotations

from collections import Counter
from types import MappingProxyType

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasBindingV2,
    CanvasNodeV2,
    ResolvedMediaInputSnapshotV2,
)
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_materialization import ParentNodeSnapshotV1
from app.schemas.agent_canvas_role_prompt_preparation import (
    RoleBindingSnapshotV2,
    RolePromptVariantV2,
)
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
                64,
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
                64,
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
                64,
                required=False,
                required_when_active=True,
                canonical_order=3,
            ),
            _rule("scene_board", "image", 1, 1, required=True, canonical_order=4),
            _rule(
                "character_main",
                "image",
                0,
                1,
                required=False,
                default_included=False,
                canonical_order=5,
            ),
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

    def require_derivative_bindings(
        self,
        parent: ParentNodeSnapshotV1 | None,
        nodes: tuple[CanvasNodeV2, ...],
        bindings: tuple[CanvasBindingV2, ...],
    ) -> None:
        """Require the closed parent-only topology for one guided derivative."""

        violations: list[str] = []
        if parent is None or len(nodes) != 1:
            violations.append("derivative_shape_invalid")
        if len(bindings) != 1:
            violations.append("derivative_binding_cardinality_invalid")
        if parent is not None and len(nodes) == 1:
            node = nodes[0]
            target_role = (
                "product_multiview"
                if node.creative_role == "product"
                and node.structured_content.get("asset_kind") == "multi_view"
                else "character_turnaround"
                if node.creative_role == "character"
                and node.structured_content.get("character_asset_kind") == "turnaround"
                else None
            )
            expected_parent_role = (
                "product_main"
                if target_role == "product_multiview"
                else "character_main"
                if target_role == "character_turnaround"
                else None
            )
            if target_role is None or parent.semantic_role != expected_parent_role:
                violations.append("derivative_role_invalid")
            if len(bindings) == 1:
                binding = bindings[0]
                if (
                    binding.workflow_id != node.workflow_id
                    or binding.target_node_id != node.node_id
                    or binding.source.kind != "node_output"
                    or binding.source.source_node_id != parent.node_id
                    or binding.input_role != "image_reference"
                    or not binding.enabled
                    or binding.order != 0
                ):
                    violations.append("derivative_parent_binding_invalid")
                elif target_role is not None:
                    policy_violations = self.validate(
                        target_role,
                        (parent.semantic_role,),
                    )
                    violations.extend(policy_violations)
        if violations:
            raise self._error(
                "role_reference_mismatch",
                "Derivative references do not match the authoritative parent-only policy.",
                details={
                    "policy_version": self.policy_version,
                    "violations": list(dict.fromkeys(violations)),
                },
            )

    def require_derivative_prompt_bindings(
        self,
        role_variant: RolePromptVariantV2,
        bindings: tuple[RoleBindingSnapshotV2, ...],
    ) -> None:
        expected = {
            "product_multiview": ("product", "product_main_identity", "product_main"),
            "character_turnaround": (
                "character",
                "character_main_identity",
                "character_main",
            ),
        }.get(role_variant)
        if expected is None:
            return
        source_role, purpose, policy_source_role = expected
        valid = len(bindings) == 1
        if valid:
            binding = bindings[0]
            valid = bool(
                binding.source_node_id
                and binding.source_node_revision is not None
                and binding.source_role == source_role
                and bool(binding.asset_id) == bool(binding.asset_version_id)
                and binding.reference_purpose == purpose
                and binding.display_order == 0
            )
            if valid and role_variant == "character_turnaround":
                valid = bool(binding.occurrence_id) and binding.character_phase == "main"
        target_role = (
            "product_multiview" if role_variant == "product_multiview" else "character_turnaround"
        )
        if valid:
            valid = not self.validate(target_role, (policy_source_role,))
        if not valid:
            raise self._error(
                "role_reference_mismatch",
                "Derivative prompt references do not match the parent-only policy.",
                details={"policy_version": self.policy_version},
            )

    def require_derivative_runtime_inputs(
        self,
        node: CanvasNodeV2,
        inputs: tuple[ResolvedMediaInputSnapshotV2, ...],
    ) -> None:
        target_role = (
            "product_multiview"
            if node.creative_role == "product"
            and node.structured_content.get("asset_kind") == "multi_view"
            else "character_turnaround"
            if node.creative_role == "character"
            and node.structured_content.get("character_asset_kind") == "turnaround"
            else None
        )
        if target_role is None:
            return
        expected_source_role = "product" if target_role == "product_multiview" else "character"
        policy_source_role = (
            "product_main" if target_role == "product_multiview" else "character_main"
        )
        valid = len(inputs) == 1
        if valid:
            item = inputs[0]
            valid = bool(
                item.source_kind == "node_output"
                and item.source_node_id
                and item.source_node_revision is not None
                and item.source_semantic_role == expected_source_role
                and item.binding_kind == "image_reference"
                and item.input_role == "image_reference"
                and item.display_order == 0
                and item.media_type == "image"
                and item.asset_version_id
            )
            parent_snapshot = node.metadata.get("derived_parent_snapshot")
            if valid and isinstance(parent_snapshot, dict):
                valid = item.source_node_id == parent_snapshot.get("node_id")
            prepared_snapshots = node.metadata.get("prepared_reference_snapshots")
            if valid and isinstance(prepared_snapshots, list):
                prepared = prepared_snapshots[0] if len(prepared_snapshots) == 1 else None
                valid = isinstance(prepared, dict) and all(
                    (
                        item.binding_id == prepared.get("binding_id"),
                        item.source_node_id == prepared.get("source_node_id"),
                        item.source_node_revision == prepared.get("source_node_revision"),
                        prepared.get("asset_id") in {None, item.asset_id},
                        prepared.get("asset_version_id") in {None, item.asset_version_id},
                        item.display_order == prepared.get("display_order"),
                    )
                )
        if valid:
            valid = not self.validate(target_role, (policy_source_role,))
        if not valid:
            raise self._error(
                "role_reference_mismatch",
                "Derivative runtime references do not match the parent-only policy.",
                details={
                    "policy_version": self.policy_version,
                    "target_node_id": node.node_id,
                },
            )

    @staticmethod
    def _error(
        code: str, message: str, *, details: dict[str, object] | None = None
    ) -> V2PersistenceError:
        error = V2PersistenceError(code, message, stage="agent_canvas_role_reference_policy")
        if details:
            error.details = details
        return error
