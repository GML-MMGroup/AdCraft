"""Freeze one secret-free catalog model selection for a Canvas attempt."""

from __future__ import annotations

from app.persistence.errors import V2PersistenceError
from app.persistence.provider_model_repository import ProviderModelRepository
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_runtime import ResolvedModelExecutionV1
from app.services.model_selection import ModelSelectionService


class ModelResolutionService:
    """Resolve a node selection once and bind it to catalog policy revisions."""

    def __init__(
        self,
        selection: ModelSelectionService,
        repository: ProviderModelRepository,
        *,
        allow_fake: bool,
    ) -> None:
        self._selection = selection
        self._repository = repository
        self._allow_fake = allow_fake

    def resolve(self, node: CanvasNodeV2) -> ResolvedModelExecutionV1:
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
    ) -> ResolvedModelExecutionV1:
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
        return ResolvedModelExecutionV1(
            model_ref=selected.model_ref,
            provider_id=selected.provider_id,
            provider_model_id=selected.provider_model_id,
            capability=selected.capability,
            provider_protocol=str(selected.capability_metadata.get("provider_protocol", "unknown")),
            credential_capability=selected.capability,
            credential_revision=connection.credential_revision,
            catalog_revision=selected.catalog_revision,
            capability_metadata=selected.capability_metadata,
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
