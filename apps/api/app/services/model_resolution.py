"""Freeze one secret-free catalog model selection for a Canvas attempt."""

from __future__ import annotations

import hashlib
import json

from app.persistence.errors import V2PersistenceError
from app.persistence.provider_model_repository import ProviderModelRepository
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_runtime import ResolvedModelExecutionV2
from app.schemas.provider_models import ProviderAdapterProfileV1
from app.services.model_selection import ModelSelectionService
from app.services.provider_adapter_registry import ProviderAdapterRegistry


class ModelResolutionService:
    """Resolve a node selection once and bind it to catalog policy revisions."""

    def __init__(
        self,
        selection: ModelSelectionService,
        repository: ProviderModelRepository,
        *,
        allow_fake: bool,
        adapter_registry: ProviderAdapterRegistry | None = None,
    ) -> None:
        self._selection = selection
        self._repository = repository
        self._allow_fake = allow_fake
        self._adapter_registry = adapter_registry

    def resolve(self, node: CanvasNodeV2) -> ResolvedModelExecutionV2:
        return self.resolve_selection(
            node_type=node.node_type,
            model_selection_mode=node.model_selection_mode,
            model_ref=node.model_ref,
            parameters=node.parameters,
        )

    def resolve_selection(
        self,
        *,
        node_type: str,
        model_selection_mode: str,
        model_ref: str | None,
        parameters: dict[str, object] | None = None,
    ) -> ResolvedModelExecutionV2:
        """Resolve one frozen catalog selection without constructing a Canvas Node."""

        selected = self._selection.validate_selection(
            node_type=node_type,
            model_selection_mode=model_selection_mode,
            model_ref=model_ref,
            parameters=parameters,
        )
        if selected is None:
            raise V2PersistenceError(
                "node_not_runnable",
                "Editing Nodes do not have a generation model.",
                stage="model_resolution",
            )
        try:
            connection = self._repository.get_connection(selected.provider_id)
        except ValueError as error:
            raise _error("provider_credentials_missing", selected.provider_id) from error
        if selected.provider_id != "fake" or not self._allow_fake:
            if connection.connection_state != "configured":
                raise _error("provider_credentials_missing", selected.provider_id)
            capability_status = connection.credential_status.get(selected.capability)
            if not isinstance(capability_status, dict) or not bool(
                capability_status.get("configured")
            ):
                raise _error(
                    "provider_credentials_missing",
                    selected.provider_id,
                    credential_capability=selected.capability,
                )
        adapter_profile = _profile_for_selection(selected)
        if self._adapter_registry is not None and "adapter_profile" in selected.capability_metadata:
            try:
                self._adapter_registry.resolve(selected.model_ref, selected.capability)
            except ValueError as error:
                raise _error(
                    str(error),
                    selected.provider_id,
                    model_ref=selected.model_ref,
                ) from error
        requested_parameter_fingerprint = _parameter_fingerprint(parameters or {})
        return ResolvedModelExecutionV2(
            model_ref=selected.model_ref,
            provider_id=selected.provider_id,
            provider_model_id=selected.provider_model_id,
            capability=selected.capability,
            provider_protocol=str(selected.capability_metadata.get("provider_protocol", "unknown")),
            credential_capability=selected.capability,
            credential_revision=connection.credential_revision,
            catalog_revision=selected.catalog_revision,
            capability_metadata=selected.capability_metadata,
            adapter_id=adapter_profile["adapter_id"],
            transport_kind=adapter_profile["transport_kind"],
            conformance_status=adapter_profile["conformance_status"],
            capability_revision=adapter_profile["capability_revision"],
            adapter_revision=adapter_profile["adapter_revision"],
            requested_parameter_fingerprint=requested_parameter_fingerprint,
            effective_parameter_fingerprint=requested_parameter_fingerprint,
        )


def _error(
    code: str,
    provider_id: str,
    **details: object,
) -> V2PersistenceError:
    error = V2PersistenceError(
        code,
        "The selected provider credentials are not configured.",
        stage="model_resolution",
    )
    error.details = {"provider_id": provider_id, **details}
    return error


def _profile_for_selection(selected: object) -> dict[str, str]:
    metadata = getattr(selected, "capability_metadata")
    raw_profile = metadata.get("adapter_profile")
    if raw_profile is not None:
        try:
            profile = ProviderAdapterProfileV1.model_validate(raw_profile)
        except Exception as error:
            raise _error(
                "model_adapter_unavailable",
                getattr(selected, "provider_id"),
            ) from error
        if profile.model_ref != selected.model_ref or profile.capability != selected.capability:
            raise _error(
                "model_adapter_unavailable",
                getattr(selected, "provider_id"),
                model_ref=selected.model_ref,
            )
        return {
            "adapter_id": profile.adapter_id,
            "transport_kind": profile.transport_kind,
            "conformance_status": profile.conformance_status,
            "capability_revision": profile.capability_revision,
            "adapter_revision": profile.adapter_revision,
        }
    provider_id = getattr(selected, "provider_id")
    return {
        "adapter_id": str(metadata.get("adapter_id", f"{provider_id}-legacy-adapter-v1")),
        "transport_kind": str(
            metadata.get(
                "transport_kind",
                "fake" if provider_id == "fake" else "pi_native_openai_compatible",
            )
        ),
        "conformance_status": "compatible",
        "capability_revision": str(
            metadata.get("capability_revision", f"catalog-{selected.catalog_revision}")
        ),
        "adapter_revision": str(
            metadata.get("adapter_revision", f"{provider_id}-legacy-adapter-v1")
        ),
    }


def _parameter_fingerprint(parameters: dict[str, object]) -> str:
    encoded = json.dumps(
        parameters,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
