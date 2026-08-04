"""Secret-safe SQLite persistence for provider connections and model policy."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.models import (
    ModelDefaultRow,
    ProviderConnectionRow,
    ProviderModelRow,
    ProviderModelSyncRunRow,
)


_DEFAULT_KEYS = frozenset({"agent", "text", "image", "video", "audio"})
_DEFAULT_SELECTION_MODES = frozenset({"automatic", "explicit"})
_INITIAL_SELECTION_MODES = {
    key: ("automatic" if key == "audio" else "explicit") for key in _DEFAULT_KEYS
}
_CAPABILITIES = frozenset({"agent", "text", "image", "video", "audio"})
_AVAILABILITIES = frozenset(
    {"available", "unavailable", "unauthorized", "unsupported", "deprecated"}
)


@dataclass(frozen=True)
class ProviderConnectionRecord:
    provider_id: str
    connection_state: str
    credential_status: dict[str, Any]
    credential_revision: int
    updated_at: str


@dataclass(frozen=True)
class ProviderModelRecord:
    model_ref: str
    provider_id: str
    provider_model_id: str
    display_name: str
    capability: str
    capability_metadata: dict[str, Any]
    source: str
    availability: str
    unavailable_reason: str | None
    catalog_revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ModelDefaultRecord:
    default_key: str
    model_ref: str
    revision: int
    updated_at: str
    selection_mode: str = "explicit"


@dataclass(frozen=True)
class ProviderModelSyncRunRecord:
    sync_run_id: str
    provider_id: str
    status: str
    catalog_revision: int | None
    summary: dict[str, Any]
    error_code: str | None
    created_at: str


class ProviderModelRepository:
    """Own provider/model metadata transactions without receiving complete secrets."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    @staticmethod
    def credential_fingerprint(*, provider_id: str, capability: str, credential: str) -> str:
        """Return an intentionally capability-scoped one-way credential fingerprint."""

        value = f"adcraft-provider-fingerprint-v1:{provider_id}:{capability}:{credential}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def upsert_connection(
        self,
        *,
        provider_id: str,
        connection_state: str,
        credential_status: Mapping[str, Any],
        updated_at: str,
    ) -> ProviderConnectionRecord:
        if connection_state not in {"configured", "unconfigured", "invalid"}:
            raise ValueError("provider_connection_state_invalid")
        _assert_no_secret_values(credential_status)
        try:
            with self._database.engine.begin() as connection:
                current = (
                    connection.execute(
                        select(ProviderConnectionRow).where(
                            ProviderConnectionRow.provider_id == provider_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                values = {
                    "connection_state": connection_state,
                    "credential_status_json": _json_dump(dict(credential_status)),
                    "updated_at": updated_at,
                }
                if current is None:
                    values["provider_id"] = provider_id
                    values["credential_revision"] = 1
                    connection.execute(insert(ProviderConnectionRow).values(**values))
                else:
                    values["credential_revision"] = int(current["credential_revision"]) + 1
                    connection.execute(
                        update(ProviderConnectionRow)
                        .where(ProviderConnectionRow.provider_id == provider_id)
                        .values(**values)
                    )
                row = (
                    connection.execute(
                        _connection_select().where(ProviderConnectionRow.provider_id == provider_id)
                    )
                    .mappings()
                    .one()
                )
        except SQLAlchemyError as error:
            raise RuntimeError("provider_model_persistence_failed") from error
        return _connection_from_row(row)

    def get_connection(self, provider_id: str) -> ProviderConnectionRecord:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        _connection_select().where(ProviderConnectionRow.provider_id == provider_id)
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise RuntimeError("provider_model_persistence_failed") from error
        if row is None:
            raise ValueError("provider_connection_not_found")
        return _connection_from_row(row)

    def upsert_models(
        self,
        *,
        provider_id: str,
        models: Iterable[Mapping[str, Any]],
        updated_at: str,
    ) -> tuple[ProviderModelRecord, ...]:
        normalized = tuple(_normalized_model(provider_id, model) for model in models)
        if not normalized:
            return ()
        try:
            with self._database.engine.begin() as connection:
                _ensure_connection(connection, provider_id, updated_at)
                revision = (
                    int(
                        connection.execute(
                            select(func.max(ProviderModelRow.catalog_revision)).where(
                                ProviderModelRow.provider_id == provider_id
                            )
                        ).scalar_one_or_none()
                        or 0
                    )
                    + 1
                )
                for model in normalized:
                    existing = connection.execute(
                        select(ProviderModelRow.model_ref).where(
                            ProviderModelRow.model_ref == model["model_ref"]
                        )
                    ).scalar_one_or_none()
                    values = {**model, "catalog_revision": revision, "updated_at": updated_at}
                    if existing is None:
                        values["created_at"] = updated_at
                        connection.execute(insert(ProviderModelRow).values(**values))
                    else:
                        connection.execute(
                            update(ProviderModelRow)
                            .where(ProviderModelRow.model_ref == model["model_ref"])
                            .values(**values)
                        )
                rows = (
                    connection.execute(
                        _model_select().where(
                            ProviderModelRow.model_ref.in_(
                                tuple(model["model_ref"] for model in normalized)
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise RuntimeError("provider_model_persistence_failed") from error
        by_ref = {_model_from_row(row).model_ref: _model_from_row(row) for row in rows}
        return tuple(by_ref[model["model_ref"]] for model in normalized)

    def get_model(self, model_ref: str) -> ProviderModelRecord:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        _model_select().where(ProviderModelRow.model_ref == model_ref)
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise RuntimeError("provider_model_persistence_failed") from error
        if row is None:
            raise ValueError("provider_model_not_found")
        return _model_from_row(row)

    def list_models(
        self,
        *,
        provider_id: str | None = None,
        capability: str | None = None,
        availability: str | None = None,
    ) -> tuple[ProviderModelRecord, ...]:
        try:
            with self._database.engine.connect() as connection:
                query = _model_select()
                if provider_id is not None:
                    query = query.where(ProviderModelRow.provider_id == provider_id)
                if capability is not None:
                    query = query.where(ProviderModelRow.capability == capability)
                if availability is not None:
                    query = query.where(ProviderModelRow.availability == availability)
                rows = (
                    connection.execute(
                        query.order_by(ProviderModelRow.provider_id, ProviderModelRow.model_ref)
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise RuntimeError("provider_model_persistence_failed") from error
        return tuple(_model_from_row(row) for row in rows)

    def set_defaults(
        self,
        values: Mapping[str, str],
        *,
        modes: Mapping[str, str] | None = None,
        updated_at: str,
    ) -> dict[str, ModelDefaultRecord]:
        mode_updates = dict(modes or {})
        affected_keys = set(values).union(mode_updates)
        if not affected_keys or not affected_keys.issubset(_DEFAULT_KEYS):
            raise ValueError("model_default_update_invalid")
        if not set(mode_updates.values()).issubset(_DEFAULT_SELECTION_MODES):
            raise ValueError("model_default_mode_invalid")
        try:
            with self._database.engine.begin() as connection:
                known = _model_capabilities(connection, values.values())
                if len(known) != len(set(values.values())):
                    raise ValueError("model_default_model_not_found")
                for default_key, model_ref in values.items():
                    if not _default_accepts_capability(default_key, known[model_ref]):
                        raise ValueError("model_default_capability_invalid")
                current_rows = (
                    connection.execute(
                        _default_select().where(
                            ModelDefaultRow.default_key.in_(tuple(affected_keys))
                        )
                    )
                    .mappings()
                    .all()
                )
                current_by_key = {str(row["default_key"]): row for row in current_rows}
                for default_key in affected_keys:
                    current = current_by_key.get(default_key)
                    if current is None and default_key not in values:
                        raise ValueError("model_default_not_configured")
                    model_ref = str(values.get(default_key) or current["model_ref"])
                    selection_mode = mode_updates.get(
                        default_key,
                        str(current["selection_mode"])
                        if current is not None
                        else _INITIAL_SELECTION_MODES[default_key],
                    )
                    if current is None:
                        connection.execute(
                            insert(ModelDefaultRow).values(
                                default_key=default_key,
                                model_ref=model_ref,
                                selection_mode=selection_mode,
                                revision=1,
                                updated_at=updated_at,
                            )
                        )
                    else:
                        connection.execute(
                            update(ModelDefaultRow)
                            .where(ModelDefaultRow.default_key == default_key)
                            .values(
                                model_ref=model_ref,
                                selection_mode=selection_mode,
                                revision=int(current["revision"]) + 1,
                                updated_at=updated_at,
                            )
                        )
                rows = (
                    connection.execute(
                        _default_select().where(
                            ModelDefaultRow.default_key.in_(tuple(affected_keys))
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise RuntimeError("provider_model_persistence_failed") from error
        result = {_default_from_row(row).default_key: _default_from_row(row) for row in rows}
        return {key: result[key] for key in affected_keys}

    def get_defaults(self) -> dict[str, ModelDefaultRecord]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(_default_select().order_by(ModelDefaultRow.default_key))
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise RuntimeError("provider_model_persistence_failed") from error
        return {_default_from_row(row).default_key: _default_from_row(row) for row in rows}

    def record_sync_run(
        self,
        *,
        sync_run_id: str,
        provider_id: str,
        status: str,
        catalog_revision: int | None,
        summary: Mapping[str, Any],
        error_code: str | None,
        created_at: str,
    ) -> ProviderModelSyncRunRecord:
        if status not in {"succeeded", "failed"}:
            raise ValueError("provider_model_sync_status_invalid")
        _assert_no_secret_values(summary)
        try:
            with self._database.engine.begin() as connection:
                _ensure_connection(connection, provider_id, created_at)
                connection.execute(
                    insert(ProviderModelSyncRunRow).values(
                        sync_run_id=sync_run_id,
                        provider_id=provider_id,
                        status=status,
                        catalog_revision=catalog_revision,
                        summary_json=_json_dump(dict(summary)),
                        error_code=error_code,
                        created_at=created_at,
                    )
                )
                row = (
                    connection.execute(
                        _sync_run_select().where(ProviderModelSyncRunRow.sync_run_id == sync_run_id)
                    )
                    .mappings()
                    .one()
                )
        except SQLAlchemyError as error:
            raise RuntimeError("provider_model_persistence_failed") from error
        return _sync_run_from_row(row)


def _ensure_connection(connection: Any, provider_id: str, updated_at: str) -> None:
    exists = connection.execute(
        select(ProviderConnectionRow.provider_id).where(
            ProviderConnectionRow.provider_id == provider_id
        )
    ).scalar_one_or_none()
    if exists is None:
        connection.execute(
            insert(ProviderConnectionRow).values(
                provider_id=provider_id,
                connection_state="unconfigured",
                credential_status_json="{}",
                credential_revision=1,
                updated_at=updated_at,
            )
        )


def _normalized_model(provider_id: str, model: Mapping[str, Any]) -> dict[str, Any]:
    model_ref = _required_string(model, "model_ref")
    provider_model_id = _required_string(model, "provider_model_id")
    if model_ref != f"{provider_id}:{provider_model_id}":
        raise ValueError("provider_model_reference_invalid")
    capability = _required_string(model, "capability")
    if capability not in _CAPABILITIES:
        raise ValueError("provider_model_capability_invalid")
    availability = _required_string(model, "availability")
    if availability not in _AVAILABILITIES:
        raise ValueError("provider_model_availability_invalid")
    capability_metadata = model.get("capability_metadata", {})
    if not isinstance(capability_metadata, Mapping):
        raise ValueError("provider_model_metadata_invalid")
    return {
        "model_ref": model_ref,
        "provider_id": provider_id,
        "provider_model_id": provider_model_id,
        "display_name": _required_string(model, "display_name"),
        "capability": capability,
        "capability_metadata_json": _json_dump(dict(capability_metadata)),
        "source": _required_string(model, "source"),
        "availability": availability,
        "unavailable_reason": _optional_string(model.get("unavailable_reason")),
    }


def _default_accepts_capability(default_key: str, capability: str) -> bool:
    if default_key == "agent":
        return capability in {"agent", "text"}
    return default_key == capability


def _model_capabilities(connection: Any, model_refs: Iterable[str]) -> dict[str, str]:
    references = tuple(model_refs)
    if not references:
        return {}
    rows = (
        connection.execute(
            select(ProviderModelRow.model_ref, ProviderModelRow.capability).where(
                ProviderModelRow.model_ref.in_(references)
            )
        )
        .mappings()
        .all()
    )
    return {str(row["model_ref"]): str(row["capability"]) for row in rows}


def _required_string(values: Mapping[str, Any], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("provider_model_value_invalid")
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _assert_no_secret_values(values: Mapping[str, Any]) -> None:
    serialized = _json_dump(dict(values)).lower()
    forbidden = ("api_key", "secret", "authorization", "bearer ")
    if any(token in serialized for token in forbidden):
        raise ValueError("provider_metadata_secret_forbidden")


def _json_dump(value: Mapping[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _connection_select():
    return select(
        ProviderConnectionRow.provider_id,
        ProviderConnectionRow.connection_state,
        ProviderConnectionRow.credential_status_json,
        ProviderConnectionRow.credential_revision,
        ProviderConnectionRow.updated_at,
    )


def _model_select():
    return select(
        ProviderModelRow.model_ref,
        ProviderModelRow.provider_id,
        ProviderModelRow.provider_model_id,
        ProviderModelRow.display_name,
        ProviderModelRow.capability,
        ProviderModelRow.capability_metadata_json,
        ProviderModelRow.source,
        ProviderModelRow.availability,
        ProviderModelRow.unavailable_reason,
        ProviderModelRow.catalog_revision,
        ProviderModelRow.created_at,
        ProviderModelRow.updated_at,
    )


def _default_select():
    return select(
        ModelDefaultRow.default_key,
        ModelDefaultRow.model_ref,
        ModelDefaultRow.selection_mode,
        ModelDefaultRow.revision,
        ModelDefaultRow.updated_at,
    )


def _sync_run_select():
    return select(
        ProviderModelSyncRunRow.sync_run_id,
        ProviderModelSyncRunRow.provider_id,
        ProviderModelSyncRunRow.status,
        ProviderModelSyncRunRow.catalog_revision,
        ProviderModelSyncRunRow.summary_json,
        ProviderModelSyncRunRow.error_code,
        ProviderModelSyncRunRow.created_at,
    )


def _connection_from_row(row: RowMapping) -> ProviderConnectionRecord:
    return ProviderConnectionRecord(
        provider_id=str(row["provider_id"]),
        connection_state=str(row["connection_state"]),
        credential_status=dict(json.loads(str(row["credential_status_json"]))),
        credential_revision=int(row["credential_revision"]),
        updated_at=str(row["updated_at"]),
    )


def _model_from_row(row: RowMapping) -> ProviderModelRecord:
    return ProviderModelRecord(
        model_ref=str(row["model_ref"]),
        provider_id=str(row["provider_id"]),
        provider_model_id=str(row["provider_model_id"]),
        display_name=str(row["display_name"]),
        capability=str(row["capability"]),
        capability_metadata=dict(json.loads(str(row["capability_metadata_json"]))),
        source=str(row["source"]),
        availability=str(row["availability"]),
        unavailable_reason=_optional_string(row["unavailable_reason"]),
        catalog_revision=int(row["catalog_revision"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _default_from_row(row: RowMapping) -> ModelDefaultRecord:
    return ModelDefaultRecord(
        default_key=str(row["default_key"]),
        model_ref=str(row["model_ref"]),
        selection_mode=str(row["selection_mode"]),
        revision=int(row["revision"]),
        updated_at=str(row["updated_at"]),
    )


def _sync_run_from_row(row: RowMapping) -> ProviderModelSyncRunRecord:
    return ProviderModelSyncRunRecord(
        sync_run_id=str(row["sync_run_id"]),
        provider_id=str(row["provider_id"]),
        status=str(row["status"]),
        catalog_revision=int(row["catalog_revision"])
        if row["catalog_revision"] is not None
        else None,
        summary=dict(json.loads(str(row["summary_json"]))),
        error_code=_optional_string(row["error_code"]),
        created_at=str(row["created_at"]),
    )
