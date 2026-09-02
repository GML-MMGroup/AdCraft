"""Derive bounded conditioning plans from the existing reference authority."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from app.schemas.agent_canvas_reference_conditioning import ReferenceConditioningPlanV1
from app.schemas.agent_canvas_role_prompt_preparation import RolePromptPreparationContextV2
from app.services.agent_canvas_reference_style_authority import (
    ReferenceStyleAuthorityPolicyResolver,
)


_CHARACTER_ALLOWED = ("view", "pose", "camera", "framing", "background", "content")
_SCENE_ALLOWED = ("view", "camera", "framing", "content")


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class ReferenceConditioningPlanResolver:
    """Create one immutable conditioning projection for an exact current policy."""

    def __init__(self, policy_resolver: ReferenceStyleAuthorityPolicyResolver | None = None):
        self._policy_resolver = policy_resolver or ReferenceStyleAuthorityPolicyResolver()

    def resolve(
        self, context: RolePromptPreparationContextV2
    ) -> ReferenceConditioningPlanV1 | None:
        policy = self._policy_resolver.resolve(context)
        if policy is None:
            return None
        self._validate_structured_overrides(context, policy.protected_dimensions)
        allowed = _CHARACTER_ALLOWED if context.role_variant == "character_main" else _SCENE_ALLOWED
        return ReferenceConditioningPlanV1(
            target_role=context.role_variant,
            source_policy_id=policy.policy_id,
            source_policy_digest=policy.policy_digest,
            reference_kind=policy.reference_kind,
            semantic_reference_role=policy.semantic_reference_role,
            reference_purpose=policy.reference_purpose,
            protected_dimensions=policy.protected_dimensions,
            allowed_change_dimensions=allowed,
            explicit_override_dimensions=policy.explicit_override_dimensions,
            reference_control_level=policy.reference_control_level,
            provenance=policy.provenance,
            provenance_digest=_digest(policy.provenance.model_dump(mode="json")),
        )

    @staticmethod
    def _validate_structured_overrides(
        context: RolePromptPreparationContextV2,
        protected_dimensions: tuple[str, ...],
    ) -> None:
        raw = context.explicit_controls.get("visual_overrides")
        if raw is None:
            return
        if not isinstance(raw, Mapping):
            raise ValueError("reference_conditioning_override_invalid")
        protected = set(protected_dimensions)
        for key, value in raw.items():
            if not isinstance(key, str) or key not in protected:
                raise ValueError("reference_conditioning_override_invalid")
            if isinstance(value, (Mapping, list, tuple, set)):
                raise ValueError("reference_conditioning_override_invalid")
