"""Fail-soft presentation projection for the Agent Canvas timeline."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast, get_args

from pydantic import JsonValue, TypeAdapter, ValidationError

from app.schemas.agent_canvas_conversation import (
    ChatTimelineEntryV2,
    ChatTimelinePresentationItemV2,
)
from app.schemas.language import canonicalize_bcp47_tag


PresentationMessageKey = Literal[
    "concept_proposal.review",
    "planning_progress.next_action",
    "expert_activity.working",
    "expert_activity.completed",
    "expert_activity.failed",
    "draft.materialized",
    "action.topic_deferred",
    "action.element_excluded",
]

PRESENTATION_MESSAGE_KEYS: frozenset[str] = frozenset(get_args(PresentationMessageKey))
_MESSAGE_ARGS_ADAPTER = TypeAdapter(dict[str, JsonValue])
_TRUSTED_STORED_KEY_PREFIXES = ("planning:", "receipt:")


class AgentCanvasTimelinePresentation:
    """Project one raw timeline page into stable user-facing items."""

    def project(
        self,
        items: tuple[ChatTimelineEntryV2, ...],
    ) -> tuple[ChatTimelinePresentationItemV2, ...]:
        selected: dict[str, ChatTimelinePresentationItemV2] = {}
        sources: dict[str, list[str]] = {}
        for entry in items:
            item = self._project_entry(entry)
            key = item.presentation_key
            source_ids = sources.setdefault(key, [])
            if entry.entry_id not in source_ids:
                source_ids.append(entry.entry_id)
            current = selected.get(key)
            if current is None or (
                item.presentation_revision,
                item.sequence_no,
            ) > (
                current.presentation_revision,
                current.sequence_no,
            ):
                selected[key] = item

        projected = (
            item.model_copy(update={"source_entry_ids": tuple(sources[key])})
            for key, item in selected.items()
        )
        return tuple(sorted(projected, key=lambda item: item.sequence_no))

    def _project_entry(self, entry: ChatTimelineEntryV2) -> ChatTimelinePresentationItemV2:
        try:
            presentation_key, presentation_revision = _presentation_identity(entry)
            message_key, message_args, response_locale = extract_message_envelope(entry.metadata)
            return ChatTimelinePresentationItemV2(
                **entry.model_dump(mode="python"),
                presentation_key=presentation_key,
                presentation_revision=presentation_revision,
                source_entry_ids=(entry.entry_id,),
                message_key=message_key,
                message_args=message_args,
                response_locale=response_locale,
            )
        except (TypeError, ValueError, ValidationError):
            return ChatTimelinePresentationItemV2(
                **entry.model_dump(mode="python"),
                presentation_key=f"entry:{entry.entry_id}",
                presentation_revision=1,
                source_entry_ids=(entry.entry_id,),
                message_key=None,
                message_args={},
                response_locale="und",
            )


def build_presentation_metadata(
    *,
    message_key: PresentationMessageKey | None,
    message_args: Mapping[str, JsonValue] | None,
    response_locale: str,
    presentation_key: str,
    base: Mapping[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    """Add trusted localization inputs to existing timeline metadata."""

    metadata = dict(base or {})
    if message_key is not None:
        metadata["message_key"] = message_key
    metadata["message_args"] = _safe_message_args(message_args)
    metadata["response_locale"] = _safe_locale(response_locale)
    metadata["presentation_key"] = presentation_key
    return metadata


def extract_message_envelope(
    metadata: Mapping[str, object] | object,
) -> tuple[PresentationMessageKey | None, dict[str, JsonValue], str]:
    """Extract optional presentation metadata without failing a timeline read."""

    if not isinstance(metadata, Mapping):
        return None, {}, "und"
    raw_key = metadata.get("message_key")
    message_key = (
        cast(PresentationMessageKey, raw_key)
        if isinstance(raw_key, str) and raw_key in PRESENTATION_MESSAGE_KEYS
        else None
    )
    return (
        message_key,
        _safe_message_args(metadata.get("message_args")),
        _safe_locale(metadata.get("response_locale")),
    )


def _safe_message_args(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        return {}
    try:
        return _MESSAGE_ARGS_ADAPTER.validate_python(dict(value))
    except (TypeError, ValueError, ValidationError):
        return {}


def _safe_locale(value: object) -> str:
    if not isinstance(value, str):
        return "und"
    try:
        return canonicalize_bcp47_tag(value)
    except ValueError:
        return "und"


def _presentation_identity(entry: ChatTimelineEntryV2) -> tuple[str, int]:
    metadata = entry.metadata
    if entry.entry_type == "agent_document_reference":
        document_id = _bounded_identity(metadata.get("document_id"))
        if document_id is not None:
            return f"document:{document_id}", _positive_int(metadata.get("revision"))
    if entry.entry_type == "expert_activity":
        activity_id = _bounded_identity(metadata.get("activity_id"))
        if activity_id is not None:
            return f"activity:{activity_id}", entry.sequence_no
    if entry.entry_type == "concept_proposal":
        proposal_id = _bounded_identity(metadata.get("proposal_id"))
        if proposal_id is not None:
            return f"proposal:{proposal_id}", _positive_int(
                metadata.get("proposal_revision")
            )
    stored_key = metadata.get("presentation_key")
    if (
        isinstance(stored_key, str)
        and 1 <= len(stored_key) <= 320
        and stored_key.startswith(_TRUSTED_STORED_KEY_PREFIXES)
    ):
        return stored_key, _positive_int(metadata.get("presentation_revision"))
    return f"entry:{entry.entry_id}", 1


def _bounded_identity(value: object) -> str | None:
    return value if isinstance(value, str) and 1 <= len(value) <= 160 else None


def _positive_int(value: object) -> int:
    if isinstance(value, bool):
        return 1
    try:
        return max(1, int(value))
    except (TypeError, ValueError, OverflowError):
        return 1
