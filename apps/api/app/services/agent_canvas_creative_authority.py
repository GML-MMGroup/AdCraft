"""Bounded creative-authority resolution for guided Agent Canvas sessions."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, cast

from app.schemas.agent_canvas_creative_session import (
    CreativeAuthorityActionV2,
    CreativeAuthorityResolutionV2,
    CreativeAuthorityV2,
    GuidedSessionStateV2,
)


class CreativeAuthorityResolverV2:
    """Validate explicit facts and a bounded Director decision without parsing prose."""

    def resolve(
        self,
        *,
        message: str,
        session: GuidedSessionStateV2,
        frozen_facts: Mapping[str, Any],
        director_resolution: CreativeAuthorityResolutionV2,
        turn_id: str,
    ) -> CreativeAuthorityResolutionV2:
        del message
        explicit = frozen_facts.get("explicit_creative_authority")
        if explicit in {"user", "director"}:
            authority = cast(CreativeAuthorityV2, explicit)
            return CreativeAuthorityResolutionV2(
                outcome="resolved",
                authority=authority,
                source=("explicit_user" if authority == "user" else "explicit_delegation"),
            )
        if director_resolution.outcome == "resolved":
            return director_resolution
        return CreativeAuthorityResolutionV2(
            outcome="ask",
            actions=tuple(
                CreativeAuthorityActionV2(
                    action_id=_action_id(session.session_id, turn_id, authority),
                    authority=authority,
                    label=label,
                    expected_session_revision=session.revision,
                )
                for authority, label in (
                    ("user", "I have a direction"),
                    ("director", "Take the lead"),
                )
            ),
        )


def _action_id(session_id: str, turn_id: str, authority: str) -> str:
    identity = f"{session_id}:{turn_id}:set_creative_authority:{authority}"
    return "guided_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
