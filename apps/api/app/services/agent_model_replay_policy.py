"""Install trusted model metadata for one isolated model-trace replay stack."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import Settings
from app.persistence.database import create_v2_database
from app.persistence.provider_model_repository import ProviderModelRepository
from app.schemas.agent_model_trace import AgentModelTraceBundleV1
from app.services.agent_model_trace_sessions import AgentModelTraceSessionError
from app.services.provider_model_catalog import ProviderModelCatalogService


class AgentModelReplayPolicyService:
    """Prepare existing installation policy without loading provider credentials."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def prepare(self, bundle: AgentModelTraceBundleV1) -> dict[str, object]:
        model_refs = {entry.request_identity.model_ref for entry in bundle.entries}
        if len(model_refs) != 1:
            raise AgentModelTraceSessionError("acceptance_model_replay_mismatch")
        model_ref = next(iter(model_refs))
        if ":" not in model_ref:
            raise AgentModelTraceSessionError("acceptance_model_replay_mismatch")
        provider_id = model_ref.split(":", 1)[0]
        database = create_v2_database(self._settings.media_data_dir)
        try:
            repository = ProviderModelRepository(database)
            now = datetime.now(timezone.utc).isoformat()
            catalog = ProviderModelCatalogService(
                repository,
                capability_available=(
                    lambda candidate_provider, capability: (
                        candidate_provider == provider_id and capability == "text"
                    )
                ),
            )
            catalog.reconcile_trusted_models(provider_id, now=now)
            try:
                model = catalog.get_model(model_ref)
            except ValueError as error:
                raise AgentModelTraceSessionError("acceptance_model_replay_mismatch") from error
            if model.availability != "available" or not bool(
                model.capability_metadata.get("agent_compatible")
            ):
                raise AgentModelTraceSessionError("acceptance_model_replay_mismatch")
            defaults = catalog.get_defaults()
            if any(key in defaults and defaults[key] != model_ref for key in ("agent", "text")):
                raise AgentModelTraceSessionError("acceptance_model_replay_mismatch")
            missing = {key: model_ref for key in ("agent", "text") if key not in defaults}
            if missing:
                catalog.set_defaults(missing, now=now)
                defaults = catalog.get_defaults()
        finally:
            database.dispose()
        return {
            "model_ref": model_ref,
            "availability": model.availability,
            "agent_default_matches": defaults.get("agent") == model_ref,
            "text_default_matches": defaults.get("text") == model_ref,
            "credential_loaded": False,
        }
