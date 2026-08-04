"""Canonical Agent Canvas model-selection policy.

This module intentionally contains no provider credential handling.  It reads
the installation-scoped catalog and defaults, then returns secret-free model
metadata that authoring and runtime services can persist independently.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.persistence.errors import V2PersistenceError
from app.persistence.provider_model_repository import ProviderModelRecord
from app.schemas.agent_canvas import CanvasModelSummaryV2, CanvasNodeV2
from app.services.automatic_model_routing import (
    AutomaticModelRoutingService,
    validate_audio_model_parameters,
)
from app.services.provider_model_catalog import ProviderModelCatalogService


@dataclass(frozen=True, slots=True)
class SelectedModelV1:
    """A capability-validated model selection without credentials."""

    model_ref: str
    provider_id: str
    provider_model_id: str
    capability: str
    catalog_revision: int
    capability_metadata: dict[str, object]

    @classmethod
    def from_record(cls, record: ProviderModelRecord) -> "SelectedModelV1":
        return cls(
            model_ref=record.model_ref,
            provider_id=record.provider_id,
            provider_model_id=record.provider_model_id,
            capability=record.capability,
            catalog_revision=record.catalog_revision,
            capability_metadata=dict(record.capability_metadata),
        )


class ModelSelectionService:
    """Validate canonical Canvas model choices against the SQLite catalog."""

    def __init__(
        self,
        catalog: ProviderModelCatalogService,
        automatic_routing: AutomaticModelRoutingService | None = None,
    ) -> None:
        self._catalog = catalog
        self._automatic_routing = automatic_routing or AutomaticModelRoutingService()

    def validate_authoring(self, node: CanvasNodeV2) -> SelectedModelV1 | None:
        return self.validate_selection(
            node_type=node.node_type,
            model_selection_mode=node.model_selection_mode,
            model_ref=node.model_ref,
            parameters=node.parameters,
        )

    def validate_selection(
        self,
        *,
        node_type: str,
        model_selection_mode: str,
        model_ref: str | None,
        parameters: Mapping[str, object] | None = None,
    ) -> SelectedModelV1 | None:
        """Validate a persisted selection without requiring a complete Canvas Node."""

        if node_type == "editing":
            if model_selection_mode != "default" or model_ref is not None:
                raise _model_error(
                    "model_capability_mismatch",
                    "Editing Nodes cannot select a generation model.",
                )
            return None
        selected = self._resolve_record(
            node_type=node_type,
            model_selection_mode=model_selection_mode,
            model_ref=model_ref,
            parameters=parameters or {},
        )
        self._validate_node_capability(node_type, selected)
        if node_type == "audio":
            validate_audio_model_parameters(selected, parameters or {})
        return SelectedModelV1.from_record(selected)

    def summary_for(self, model_ref: str | None) -> CanvasModelSummaryV2 | None:
        if model_ref is None:
            return None
        record = next(
            (
                item
                for item in self._catalog.list_models(include_unavailable=True)
                if item.model_ref == model_ref
            ),
            None,
        )
        if record is None:
            return None
        return CanvasModelSummaryV2(
            model_ref=record.model_ref,
            provider_id=record.provider_id,
            display_name=record.display_name,
            capability=record.capability,
            availability=record.availability,
            unavailable_reason=record.unavailable_reason,
            catalog_revision=record.catalog_revision,
        )

    def _resolve_record(
        self,
        *,
        node_type: str,
        model_selection_mode: str,
        model_ref: str | None,
        parameters: Mapping[str, object],
    ) -> ProviderModelRecord:
        if model_selection_mode == "explicit":
            if model_ref is None:
                raise _model_error("model_selection_invalid", "A model reference is required.")
            return self._record(model_ref)
        default_key = "agent" if node_type == "script" else node_type
        defaults = self._catalog.get_default_records()
        default = defaults.get(default_key)
        if default is None:
            raise _model_error(
                "model_default_not_configured",
                "No installation default is configured for this node type.",
            )
        preferred = self._record(default.model_ref)
        if default.selection_mode != "automatic":
            return preferred
        if node_type != "audio":
            raise _model_error(
                "model_automatic_policy_unsupported",
                "Automatic model routing is currently supported only for Audio Nodes.",
                node_type=node_type,
            )
        if "duration_seconds" not in parameters:
            return preferred
        candidates = self._catalog.list_models(
            provider_id=preferred.provider_id,
            capability="audio",
        )
        return self._automatic_routing.resolve(
            preferred=preferred,
            node_type=node_type,
            parameters=parameters,
            candidates=candidates,
        )

    def _record(self, model_ref: str) -> ProviderModelRecord:
        models = self._catalog.list_models(include_unavailable=True)
        record = next((item for item in models if item.model_ref == model_ref), None)
        if record is None:
            raise _model_error("model_not_found", "The selected model is not in the catalog.")
        if record.availability != "available":
            raise _model_error(
                "model_unavailable",
                "The selected model is currently unavailable.",
                model_ref=model_ref,
                unavailable_reason=record.unavailable_reason,
            )
        return record

    @staticmethod
    def _validate_node_capability(node_type: str, record: ProviderModelRecord) -> None:
        required_capability = "text" if node_type in {"text", "script"} else node_type
        if record.capability != required_capability:
            raise _model_error(
                "model_capability_mismatch",
                "The selected model is incompatible with this node type.",
                model_ref=record.model_ref,
                node_type=node_type,
            )
        if node_type == "script" and not bool(record.capability_metadata.get("agent_compatible")):
            raise _model_error(
                "agent_model_incompatible",
                "Script Nodes require an Agent-compatible text model.",
                model_ref=record.model_ref,
            )


def _model_error(code: str, message: str, **details: object) -> V2PersistenceError:
    error = V2PersistenceError(code, message, stage="model_selection")
    error.details = details
    return error
