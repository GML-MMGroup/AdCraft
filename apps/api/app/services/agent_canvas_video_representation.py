"""Resolve the typed Video representation mode without inspecting free-form prompts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_ad_media import VideoRepresentationModeV2
from app.schemas.agent_canvas_identity_safety import IdentitySafetyDecisionV1
from app.services.agent_canvas_identity_safety import resolve_identity_safety_decision


_DEFAULT_MODE: VideoRepresentationModeV2 = "illustrated"
_POLICY_VERSION = "video-representation-v1"
_VALID_MODES = frozenset(("illustrated", "illustration_to_live_action"))


@dataclass(frozen=True, slots=True)
class VideoRepresentationResolutionV2:
    mode: VideoRepresentationModeV2
    source: str
    source_id: str
    policy_version: str
    digest: str
    identity_safety_decision: IdentitySafetyDecisionV1 | None = None
    identity_safety_digest: str | None = None


def resolve_video_representation_mode(
    *,
    explicit_control: object | None = None,
    skill_mode: object | None = None,
    explicit_source_id: str = "requirement-ledger",
    skill_source_id: str = "video-skill",
    identity_safety_decision: IdentitySafetyDecisionV1 | object | None = None,
) -> VideoRepresentationResolutionV2:
    """Resolve explicit user authority, then Skill metadata, then the platform default."""

    if explicit_control is not None:
        mode = _validated_mode(explicit_control)
        source, source_id = "explicit_user", explicit_source_id
    elif skill_mode is not None:
        mode = _validated_mode(skill_mode)
        source, source_id = "video_skill", skill_source_id
    else:
        mode = _DEFAULT_MODE
        source, source_id = "platform_default", "platform-default"
    safety = resolve_identity_safety_decision(
        identity_safety_decision,
        required=mode == "illustration_to_live_action",
    )
    payload = {
        "mode": mode,
        "source": source,
        "source_id": source_id,
        "policy_version": _POLICY_VERSION,
        "identity_safety_digest": safety.digest if safety is not None else None,
    }
    digest = sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return VideoRepresentationResolutionV2(
        mode=mode,
        source=source,
        source_id=source_id,
        policy_version=_POLICY_VERSION,
        digest=f"sha256:{digest}",
        identity_safety_decision=safety.decision if safety is not None else None,
        identity_safety_digest=safety.digest if safety is not None else None,
    )


def _validated_mode(value: object) -> VideoRepresentationModeV2:
    if not isinstance(value, str) or value not in _VALID_MODES:
        raise V2PersistenceError(
            "video_representation_mode_invalid",
            "Video representation mode is invalid.",
            stage="video_representation_resolver",
        )
    return value  # type: ignore[return-value]
