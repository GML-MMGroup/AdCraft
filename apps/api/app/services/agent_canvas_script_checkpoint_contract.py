"""Contract binding and canonicalization for guided Script checkpoints."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import BaseModel

from app.schemas.agent_canvas_materialization import (
    GuidedScriptCheckpointDraftV1,
    ScriptMaterializationContentV1,
    ScriptMaterializationResultV1,
)


class GuidedScriptCheckpointCanonicalizationError(ValueError):
    """A model draft cannot be converted into the canonical Script result."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def normalize_guided_script_checkpoint(
    draft: GuidedScriptCheckpointDraftV1 | Mapping[str, object] | BaseModel,
    *,
    duration_seconds: float | int | None,
) -> ScriptMaterializationResultV1:
    """Inject only the frozen duration into an accepted model-owned draft."""

    if duration_seconds is None:
        raise GuidedScriptCheckpointCanonicalizationError(
            "production_duration_required",
            "Canonical production duration is required before Script authoring.",
        )
    try:
        typed_draft = GuidedScriptCheckpointDraftV1.model_validate(draft)
        content = ScriptMaterializationContentV1(
            content=typed_draft.content,
            total_duration_seconds=duration_seconds,
        )
        return ScriptMaterializationResultV1(
            title=typed_draft.title,
            summary_prompt=typed_draft.summary_prompt,
            structured_content=content,
        )
    except Exception as error:  # noqa: BLE001 - canonical contract boundary.
        raise GuidedScriptCheckpointCanonicalizationError(
            "agent_working_document_content_invalid",
            "Guided Script draft cannot be canonicalized.",
        ) from error


@dataclass(frozen=True, slots=True)
class CapabilityContractBinding:
    """One explicit model-to-publication contract binding."""

    operation: str
    publication_kind: str
    model_contract_name: str
    canonical_contract_name: str
    normalization_id: str
    normalizer: Callable[..., ScriptMaterializationResultV1]


_BINDINGS = (
    CapabilityContractBinding(
        operation="author_guided_script_checkpoint",
        publication_kind="internal_document",
        model_contract_name="GuidedScriptCheckpointDraftV1",
        canonical_contract_name="ScriptMaterializationResultV1",
        normalization_id="guided-script-checkpoint-v1",
        normalizer=normalize_guided_script_checkpoint,
    ),
)


class CapabilityContractBindingRegistryError(ValueError):
    """Stable error raised for invalid model-to-publication bindings."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class CapabilityContractBindingRegistry:
    """Resolve exact model-to-canonical bindings without fallback."""

    def __init__(self, bindings: tuple[CapabilityContractBinding, ...] = _BINDINGS) -> None:
        keys = tuple((binding.operation, binding.publication_kind) for binding in bindings)
        if len(keys) != len(set(keys)):
            raise CapabilityContractBindingRegistryError(
                "agent_contract_registry_invalid",
                "Capability contract bindings must be unique.",
            )
        for binding in bindings:
            if (
                binding.operation != "author_guided_script_checkpoint"
                or binding.publication_kind != "internal_document"
                or binding.model_contract_name != "GuidedScriptCheckpointDraftV1"
                or binding.canonical_contract_name != "ScriptMaterializationResultV1"
                or binding.normalization_id != "guided-script-checkpoint-v1"
                or binding.normalizer is not normalize_guided_script_checkpoint
            ):
                raise CapabilityContractBindingRegistryError(
                    "agent_contract_registry_invalid",
                    "Capability contract binding is contradictory or unknown.",
                )
        self._bindings = MappingProxyType(dict(zip(keys, bindings, strict=True)))

    def resolve(self, operation: str, publication_kind: str) -> CapabilityContractBinding:
        try:
            return self._bindings[(operation, publication_kind)]
        except KeyError as error:
            raise CapabilityContractBindingRegistryError(
                "agent_contract_registry_invalid",
                "Capability contract binding is not registered.",
            ) from error
