"""Shared policy for Canvas authoring metadata that never reaches providers."""

from __future__ import annotations

from collections.abc import Mapping


NON_PROVIDER_NODE_PARAMETER_KEYS = frozenset(
    {
        "requested_run",
        "source_option_id",
        "source_proposal_id",
        "stage_draft_key",
        "scene_asset_kind",
        "generate_subtitles",
    }
)


def provider_node_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    """Project provider parameters separately from persisted authoring controls."""

    return {
        key: value
        for key, value in parameters.items()
        if key not in NON_PROVIDER_NODE_PARAMETER_KEYS
    }
