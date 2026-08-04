from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from types import MappingProxyType
from typing import Callable, Iterable, Iterator, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from filelock import FileLock, Timeout
from dotenv import dotenv_values

from app.core.config import DEFAULT_LOCAL_SETTINGS_ALLOWED_ORIGINS, Settings, get_settings
from app.persistence.provider_model_repository import ProviderModelRepository
from app.schemas.provider_settings import (
    CredentialTestCapability,
    ProviderCredentialConsumer,
    ProviderCredentialConsumerStatus,
    VolcengineCredentialSetStatus,
)


class CredentialSettingsError(ValueError):
    """A bounded failure that can be converted to the public settings error contract."""

    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class LocalSettingsAccessPolicy:
    """Restricts credential settings operations to the local application boundary."""

    def __init__(
        self,
        allowed_origins: tuple[str, ...] = DEFAULT_LOCAL_SETTINGS_ALLOWED_ORIGINS,
    ) -> None:
        self._allowed_origins = frozenset(allowed_origins)

    def ensure_allowed(self, *, client_host: str | None, origin: str | None) -> None:
        if not _is_loopback_host(client_host) or (
            origin is not None and origin not in self._allowed_origins
        ):
            raise CredentialSettingsError(
                code="local_settings_access_denied",
                message="Credential settings are available only from trusted local clients.",
                status_code=403,
            )


def _is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class ConsumerCredentialBinding:
    consumer: ProviderCredentialConsumer
    dotenv_field: str
    settings_field: str
    endpoint_field: str
    test_capability: CredentialTestCapability


@dataclass(frozen=True)
class ProviderCredentialDefinition:
    provider_id: str
    bindings: Mapping[ProviderCredentialConsumer, ConsumerCredentialBinding]
    allowed_test_origins: tuple[str, ...]
    display_name: str
    capability_consumers: Mapping[str, ProviderCredentialConsumer]

    def binding(self, consumer: ProviderCredentialConsumer) -> ConsumerCredentialBinding:
        return self.bindings[consumer]

    def binding_for_capability(self, capability: str) -> ConsumerCredentialBinding:
        try:
            return self.bindings[self.capability_consumers[capability]]
        except KeyError as exc:
            raise CredentialSettingsError(
                code="credential_capability_not_supported",
                message="The requested credential capability is not supported.",
                status_code=422,
            ) from exc

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(self.capability_consumers)


class ProviderCredentialRegistry:
    """Owns the provider-to-consumer credential mapping used by settings services."""

    def __init__(
        self,
        definitions: tuple[ProviderCredentialDefinition, ...] | None = None,
    ) -> None:
        provider_definitions = definitions or (
            _siliconflow_definition(),
            _tianpuyue_definition(),
            _volcengine_ark_definition(),
        )
        self._definitions = MappingProxyType(
            {definition.provider_id: definition for definition in provider_definitions}
        )

    def get(self, provider_id: str) -> ProviderCredentialDefinition:
        try:
            return self._definitions[provider_id]
        except KeyError as exc:
            raise CredentialSettingsError(
                code="credential_provider_not_supported",
                message="The requested credential provider is not supported.",
                status_code=404,
            ) from exc

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))


def normalize_credential_value(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise CredentialSettingsError(
            code="credential_update_invalid",
            message="Credential values must not be empty.",
            status_code=422,
        )
    if any(character in normalized for character in ("\r", "\n", "\x00")):
        raise CredentialSettingsError(
            code="credential_update_invalid",
            message="Credential values contain unsupported control characters.",
            status_code=422,
        )
    return normalized


def mask_credential_value(value: str) -> str:
    """Return a fixed-length status mask without exposing short values in full."""

    suffix = value[-4:] if len(value) >= 4 else "****"
    return f"********{suffix}"


@dataclass(frozen=True)
class DotenvSnapshot:
    exists: bool
    content: bytes
    mode: int | None


@dataclass(frozen=True, repr=False)
class ManagedEnvironmentSnapshot:
    values: Mapping[str, str | None]


_PROCESS_LOCKS: dict[Path, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()
_DOTENV_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


class DotenvCredentialStore:
    """Publishes allowlisted dotenv updates with rollback-capable snapshots."""

    def __init__(
        self,
        project_root: Path,
        *,
        allowed_fields: set[str] | frozenset[str],
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        self._project_root = project_root.resolve()
        self._dotenv_path = self._project_root / ".env"
        self._allowed_fields = frozenset(allowed_fields)
        self._lock_timeout_seconds = lock_timeout_seconds
        self._process_lock = _process_lock_for(self._project_root)
        self._file_lock = FileLock(str(self._project_root / ".env.credentials.lock"))

    @property
    def dotenv_path(self) -> Path:
        return self._dotenv_path

    def snapshot(self) -> DotenvSnapshot:
        if not self._dotenv_path.exists():
            return DotenvSnapshot(exists=False, content=b"", mode=None)
        mode = os.stat(self._dotenv_path).st_mode & 0o777
        return DotenvSnapshot(
            exists=True,
            content=self._dotenv_path.read_bytes(),
            mode=mode,
        )

    def values(self, fields: Iterable[str]) -> dict[str, str | None]:
        if not self._dotenv_path.exists():
            return {field: None for field in fields}
        parsed_values = dotenv_values(self._dotenv_path)
        return {
            field: value if isinstance(value := parsed_values.get(field), str) else None
            for field in fields
        }

    @contextmanager
    def locked(self) -> Iterator[None]:
        if not self._process_lock.acquire(timeout=self._lock_timeout_seconds):
            raise CredentialSettingsError(
                code="credential_update_conflict",
                message="Another credential update is already in progress.",
                status_code=409,
            )
        try:
            try:
                self._file_lock.acquire(timeout=self._lock_timeout_seconds)
            except Timeout as exc:
                raise CredentialSettingsError(
                    code="credential_update_conflict",
                    message="Another credential update is already in progress.",
                    status_code=409,
                ) from exc
            try:
                yield
            finally:
                self._file_lock.release()
        finally:
            self._process_lock.release()

    def replace_values(self, values: Mapping[str, str | None]) -> DotenvSnapshot:
        self._validate_values(values)
        with self.locked():
            snapshot = self.snapshot()
            current = snapshot.content.decode("utf-8") if snapshot.exists else ""
            updated = _replace_dotenv_values(current, values)
            self._atomic_write(updated.encode("utf-8"), mode=0o600)
            return snapshot

    def restore(self, snapshot: DotenvSnapshot) -> None:
        with self.locked():
            if not snapshot.exists:
                self._dotenv_path.unlink(missing_ok=True)
                return
            self._atomic_write(snapshot.content, mode=snapshot.mode or 0o600)

    def _validate_values(self, values: Mapping[str, str | None]) -> None:
        if not values:
            raise CredentialSettingsError(
                code="credential_update_invalid",
                message="At least one credential value must be supplied.",
                status_code=422,
            )
        unsupported_fields = set(values).difference(self._allowed_fields)
        if unsupported_fields:
            raise CredentialSettingsError(
                code="credential_update_invalid",
                message="The credential update contains an unsupported field.",
                status_code=422,
            )
        for value in values.values():
            if value is not None:
                normalize_credential_value(value)

    def _atomic_write(self, content: bytes, *, mode: int) -> None:
        self._project_root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_path_string = tempfile.mkstemp(
            prefix=".env.",
            suffix=".tmp",
            dir=self._project_root,
        )
        temporary_path = Path(temporary_path_string)
        try:
            os.fchmod(descriptor, mode)
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self._dotenv_path)
            os.chmod(self._dotenv_path, mode)
            _fsync_directory(self._project_root)
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            raise


def _process_lock_for(project_root: Path) -> threading.RLock:
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(project_root)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[project_root] = lock
        return lock


def _replace_dotenv_values(content: str, values: Mapping[str, str | None]) -> str:
    lines = content.splitlines(keepends=True)
    output: list[str] = []
    replaced_fields: set[str] = set()
    for line in lines:
        match = _DOTENV_ASSIGNMENT.match(line)
        field = match.group(1) if match else None
        if field not in values:
            output.append(line)
            continue
        if field in replaced_fields:
            continue
        if values[field] is None:
            replaced_fields.add(field)
            continue
        line_ending = "\r\n" if line.endswith("\r\n") else "\n"
        output.append(_dotenv_assignment(field, values[field] or "", line_ending))
        replaced_fields.add(field)

    if output and not output[-1].endswith(("\n", "\r")):
        output[-1] = f"{output[-1]}\n"
    for field, value in values.items():
        if field not in replaced_fields and value is not None:
            output.append(_dotenv_assignment(field, value, "\n"))
    return "".join(output)


def _dotenv_assignment(field: str, value: str, line_ending: str) -> str:
    return f"{field}={json.dumps(value)}{line_ending}"


def _fsync_directory(directory: Path) -> None:
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, os.O_RDONLY | directory_flag)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class RuntimeSettingsReloader:
    """Hot-applies a supplied subset of managed environment fields."""

    def __init__(
        self,
        *,
        settings_loader: Callable[[], Settings] = get_settings,
        cache_clear: Callable[[], None] = get_settings.cache_clear,
    ) -> None:
        self._settings_loader = settings_loader
        self._cache_clear = cache_clear

    def snapshot(
        self,
        bindings: Iterable[ConsumerCredentialBinding],
    ) -> ManagedEnvironmentSnapshot:
        fields = tuple(binding.dotenv_field for binding in bindings)
        return ManagedEnvironmentSnapshot(values={field: os.environ.get(field) for field in fields})

    def apply(
        self,
        values: Mapping[str, str | None],
        bindings: Iterable[ConsumerCredentialBinding],
    ) -> Settings:
        bindings_by_field = {binding.dotenv_field: binding for binding in bindings}
        _validate_runtime_values(values, bindings_by_field)
        for field, value in values.items():
            if value is None:
                os.environ.pop(field, None)
            else:
                os.environ[field] = value
        self._cache_clear()
        refreshed_settings = self._settings_loader()
        for field, value in values.items():
            setting_value = getattr(refreshed_settings, bindings_by_field[field].settings_field)
            if setting_value != value:
                raise CredentialSettingsError(
                    code="credential_runtime_reload_failed",
                    message="The updated credential could not be applied at runtime.",
                    status_code=500,
                )
        return refreshed_settings

    def restore(self, snapshot: ManagedEnvironmentSnapshot) -> Settings:
        for field, value in snapshot.values.items():
            if value is None:
                os.environ.pop(field, None)
            else:
                os.environ[field] = value
        self._cache_clear()
        return self._settings_loader()


def _validate_runtime_values(
    values: Mapping[str, str | None],
    bindings_by_field: Mapping[str, ConsumerCredentialBinding],
) -> None:
    if not values or set(values).difference(bindings_by_field):
        raise CredentialSettingsError(
            code="credential_runtime_reload_failed",
            message="The updated credential fields could not be applied at runtime.",
            status_code=500,
        )


@dataclass(frozen=True)
class CredentialUpdateResult:
    credentials: VolcengineCredentialSetStatus
    updated_consumers: tuple[ProviderCredentialConsumer, ...]
    applied_at: datetime


class RuntimeCredentialService:
    """Coordinates status, atomic updates, and non-destructive connection tests."""

    def __init__(
        self,
        *,
        registry: ProviderCredentialRegistry,
        dotenv_store: DotenvCredentialStore,
        settings_loader: Callable[[], Settings] = get_settings,
        reloader: RuntimeSettingsReloader | None = None,
        tester: VolcengineArkConnectionTester | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._registry = registry
        self._dotenv_store = dotenv_store
        self._settings_loader = settings_loader
        self._reloader = reloader or RuntimeSettingsReloader()
        self._tester = tester or VolcengineArkConnectionTester()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def status(self, provider_id: str) -> VolcengineCredentialSetStatus:
        definition = self._registry.get(provider_id)
        try:
            return self._status_for(definition, self._settings_loader())
        except CredentialSettingsError:
            raise
        except Exception as exc:
            raise CredentialSettingsError(
                code="credential_status_failed",
                message="Credential status could not be read.",
                status_code=500,
            ) from exc

    def update(
        self,
        provider_id: str,
        candidates: Mapping[ProviderCredentialConsumer, str],
    ) -> CredentialUpdateResult:
        definition = self._registry.get(provider_id)
        consumers, values_by_field, bindings = _ordered_update_values(definition, candidates)

        with self._dotenv_store.locked():
            dotenv_snapshot = self._dotenv_store.snapshot()
            environment_snapshot = self._reloader.snapshot(bindings)
            try:
                self._dotenv_store.replace_values(values_by_field)
            except CredentialSettingsError:
                raise
            except Exception as exc:
                raise CredentialSettingsError(
                    code="credential_persistence_failed",
                    message="Credential values could not be saved.",
                    status_code=500,
                ) from exc

            try:
                refreshed_settings = self._reloader.apply(values_by_field, bindings)
            except Exception as exc:
                self._restore_update(dotenv_snapshot, environment_snapshot)
                raise CredentialSettingsError(
                    code="credential_runtime_reload_failed",
                    message="Credential values could not be applied at runtime.",
                    status_code=500,
                ) from exc

        return CredentialUpdateResult(
            credentials=self._status_for(definition, refreshed_settings),
            updated_consumers=consumers,
            applied_at=self._clock(),
        )

    def test(
        self,
        provider_id: str,
        consumer: ProviderCredentialConsumer,
        candidate: str | None = None,
    ) -> CredentialTestResult:
        definition = self._registry.get(provider_id)
        normalized_candidate = (
            normalize_credential_value(candidate) if candidate is not None else None
        )
        return self._tester.test(
            definition=definition,
            consumer=consumer,
            candidate=normalized_candidate,
            settings=self._settings_loader(),
        )

    def _status_for(
        self,
        definition: ProviderCredentialDefinition,
        settings: Settings,
    ) -> VolcengineCredentialSetStatus:
        dotenv_values_by_field = self._dotenv_store.values(
            binding.dotenv_field for binding in definition.bindings.values()
        )
        statuses: dict[ProviderCredentialConsumer, ProviderCredentialConsumerStatus] = {}
        for consumer, binding in definition.bindings.items():
            effective_value = getattr(settings, binding.settings_field)
            dotenv_value = dotenv_values_by_field[binding.dotenv_field]
            if not effective_value:
                statuses[consumer] = ProviderCredentialConsumerStatus(
                    configured=False,
                    masked_api_key=None,
                    source="unconfigured",
                    test_capability=binding.test_capability,
                )
                continue
            source = "project_dotenv" if dotenv_value == effective_value else "process_environment"
            statuses[consumer] = ProviderCredentialConsumerStatus(
                configured=True,
                masked_api_key=mask_credential_value(effective_value),
                source=source,
                test_capability=binding.test_capability,
            )
        return VolcengineCredentialSetStatus(
            llm=statuses["llm"],
            image=statuses["image"],
            video=statuses["video"],
        )

    def _restore_update(
        self,
        dotenv_snapshot: DotenvSnapshot,
        environment_snapshot: ManagedEnvironmentSnapshot,
    ) -> None:
        restoration_error: Exception | None = None
        try:
            self._dotenv_store.restore(dotenv_snapshot)
        except Exception as exc:
            restoration_error = exc
        try:
            self._reloader.restore(environment_snapshot)
        except Exception as exc:
            restoration_error = restoration_error or exc
        if restoration_error is not None:
            raise CredentialSettingsError(
                code="credential_runtime_reload_failed",
                message="Credential values could not be restored after a failed update.",
                status_code=500,
            ) from restoration_error


@dataclass(frozen=True)
class ProviderCredentialCapabilitySnapshot:
    configured: bool
    fingerprint: str | None
    source: str
    test_capability: CredentialTestCapability
    masked_api_key: str | None = None


@dataclass(frozen=True)
class ProviderConnectionSnapshot:
    provider_id: str
    display_name: str
    capabilities: tuple[str, ...]
    connection_state: str
    credentials: Mapping[str, ProviderCredentialCapabilitySnapshot]
    credential_revision: int
    updated_at: datetime | None


@dataclass(frozen=True)
class ProviderConnectionUpdateResult:
    provider: ProviderConnectionSnapshot
    updated_capabilities: tuple[str, ...]
    cleared_capabilities: tuple[str, ...]
    applied_at: datetime


@dataclass(frozen=True)
class ProviderConnectionTestResult:
    provider_id: str
    capability: str
    model_ref: str | None


class ProviderConnectionService:
    """Coordinates secret-store mutations with secret-safe SQLite metadata."""

    def __init__(
        self,
        *,
        registry: ProviderCredentialRegistry,
        dotenv_store: DotenvCredentialStore,
        metadata_repository: ProviderModelRepository,
        settings_loader: Callable[[], Settings] = get_settings,
        reloader: RuntimeSettingsReloader | None = None,
        tester: VolcengineArkConnectionTester | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._registry = registry
        self._dotenv_store = dotenv_store
        self._metadata_repository = metadata_repository
        self._settings_loader = settings_loader
        self._reloader = reloader or RuntimeSettingsReloader()
        self._tester = tester or VolcengineArkConnectionTester()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def list(self) -> tuple[ProviderConnectionSnapshot, ...]:
        return tuple(self.status(provider_id) for provider_id in self._registry.provider_ids)

    def synchronize_metadata(self, *, updated_at: str | None = None) -> None:
        """Persist the current secret-safe credential state without mutating credentials."""

        settings = self._settings_loader()
        synchronized_at = updated_at or self._clock().isoformat()
        for provider_id in self._registry.provider_ids:
            definition = self._registry.get(provider_id)
            metadata = self._metadata_status(definition, settings)
            connection_state = _connection_state_from_metadata(metadata)
            try:
                current = self._metadata_repository.get_connection(provider_id)
            except ValueError:
                current = None
            if (
                current is not None
                and current.connection_state == connection_state
                and current.credential_status == metadata
            ):
                continue
            self._metadata_repository.upsert_connection(
                provider_id=provider_id,
                connection_state=connection_state,
                credential_status=metadata,
                updated_at=synchronized_at,
            )

    def migrate_legacy_siliconflow_text_key(self) -> ProviderConnectionUpdateResult | None:
        """Copy a recognized legacy SiliconFlow text key exactly once without exposing it."""

        settings = self._settings_loader()
        if (
            settings.siliconflow_api_key
            or not settings.llm_api_key
            or not _is_siliconflow_base_url(settings.llm_base_url)
        ):
            return None
        stored = self._dotenv_store.values(("SILICONFLOW_API_KEY",))["SILICONFLOW_API_KEY"]
        if stored:
            return None
        return self.update(
            "siliconflow",
            api_keys={"text": settings.llm_api_key},
        )

    def status(self, provider_id: str) -> ProviderConnectionSnapshot:
        definition = self._registry.get(provider_id)
        settings = self._settings_loader()
        credential_status = self._credential_status(definition, settings)
        try:
            persisted = self._metadata_repository.get_connection(provider_id)
        except ValueError:
            return ProviderConnectionSnapshot(
                provider_id=provider_id,
                display_name=definition.display_name,
                capabilities=definition.capabilities,
                connection_state=_connection_state(credential_status),
                credentials=credential_status,
                credential_revision=0,
                updated_at=None,
            )
        return ProviderConnectionSnapshot(
            provider_id=provider_id,
            display_name=definition.display_name,
            capabilities=definition.capabilities,
            connection_state=persisted.connection_state,
            credentials=credential_status,
            credential_revision=persisted.credential_revision,
            updated_at=_parse_timestamp(persisted.updated_at),
        )

    def update(
        self,
        provider_id: str,
        *,
        api_keys: Mapping[str, str],
        clear_capabilities: Iterable[str] = (),
    ) -> ProviderConnectionUpdateResult:
        definition = self._registry.get(provider_id)
        cleared = tuple(dict.fromkeys(clear_capabilities))
        if set(api_keys).intersection(cleared):
            raise CredentialSettingsError(
                code="credential_update_invalid",
                message="Credential capabilities cannot be set and cleared together.",
                status_code=422,
            )
        requested = tuple(dict.fromkeys((*api_keys, *cleared)))
        if not requested:
            raise CredentialSettingsError(
                code="credential_update_invalid",
                message="At least one credential capability must be supplied.",
                status_code=422,
            )
        try:
            bindings = tuple(
                definition.binding_for_capability(capability) for capability in requested
            )
        except CredentialSettingsError:
            raise
        values_by_field: dict[str, str | None] = {}
        for capability, credential in api_keys.items():
            values_by_field[definition.binding_for_capability(capability).dotenv_field] = (
                normalize_credential_value(credential)
            )
        for capability in cleared:
            values_by_field[definition.binding_for_capability(capability).dotenv_field] = None

        with self._dotenv_store.locked():
            dotenv_snapshot = self._dotenv_store.snapshot()
            environment_snapshot = self._reloader.snapshot(bindings)
            try:
                self._dotenv_store.replace_values(values_by_field)
                refreshed_settings = self._reloader.apply(values_by_field, bindings)
                metadata = self._metadata_status(definition, refreshed_settings)
                persisted = self._metadata_repository.upsert_connection(
                    provider_id=provider_id,
                    connection_state=_connection_state_from_metadata(metadata),
                    credential_status=metadata,
                    updated_at=self._clock().isoformat(),
                )
            except CredentialSettingsError:
                self._restore(dotenv_snapshot, environment_snapshot)
                raise
            except Exception as exc:
                self._restore(dotenv_snapshot, environment_snapshot)
                raise CredentialSettingsError(
                    code="credential_persistence_failed",
                    message="Credential values could not be saved.",
                    status_code=500,
                ) from exc

        snapshots = self._credential_status(definition, refreshed_settings)
        provider = ProviderConnectionSnapshot(
            provider_id=provider_id,
            display_name=definition.display_name,
            capabilities=definition.capabilities,
            connection_state=persisted.connection_state,
            credentials=snapshots,
            credential_revision=persisted.credential_revision,
            updated_at=_parse_timestamp(persisted.updated_at),
        )
        return ProviderConnectionUpdateResult(
            provider=provider,
            updated_capabilities=tuple(api_keys),
            cleared_capabilities=cleared,
            applied_at=self._clock(),
        )

    def test(
        self,
        provider_id: str,
        *,
        capability: str,
        candidate: str | None = None,
        model_ref: str | None = None,
    ) -> ProviderConnectionTestResult:
        definition = self._registry.get(provider_id)
        binding = definition.binding_for_capability(capability)
        self._tester.test(
            definition=definition,
            consumer=binding.consumer,
            candidate=normalize_credential_value(candidate) if candidate is not None else None,
            settings=self._settings_loader(),
        )
        return ProviderConnectionTestResult(
            provider_id=provider_id,
            capability=capability,
            model_ref=model_ref,
        )

    def _credential_status(
        self,
        definition: ProviderCredentialDefinition,
        settings: Settings,
    ) -> dict[str, ProviderCredentialCapabilitySnapshot]:
        dotenv_values_by_field = self._dotenv_store.values(
            binding.dotenv_field for binding in definition.bindings.values()
        )
        snapshots: dict[str, ProviderCredentialCapabilitySnapshot] = {}
        for capability in definition.capabilities:
            binding = definition.binding_for_capability(capability)
            value = getattr(settings, binding.settings_field)
            dotenv_value = dotenv_values_by_field[binding.dotenv_field]
            source = "unconfigured"
            if value:
                source = "project_dotenv" if dotenv_value == value else "process_environment"
            snapshots[capability] = ProviderCredentialCapabilitySnapshot(
                configured=bool(value),
                fingerprint=(
                    ProviderModelRepository.credential_fingerprint(
                        provider_id=definition.provider_id,
                        capability=capability,
                        credential=value,
                    )
                    if value
                    else None
                ),
                source=source,
                test_capability=binding.test_capability,
                masked_api_key=mask_credential_value(value) if value else None,
            )
        return snapshots

    def _metadata_status(
        self,
        definition: ProviderCredentialDefinition,
        settings: Settings,
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for capability, status in self._credential_status(definition, settings).items():
            result[capability] = {
                "configured": status.configured,
                "fingerprint": status.fingerprint,
                "source": status.source,
                "test_capability": status.test_capability,
            }
        return result

    def _restore(
        self,
        dotenv_snapshot: DotenvSnapshot,
        environment_snapshot: ManagedEnvironmentSnapshot,
    ) -> None:
        try:
            self._dotenv_store.restore(dotenv_snapshot)
            self._reloader.restore(environment_snapshot)
        except Exception as exc:
            raise CredentialSettingsError(
                code="credential_runtime_reload_failed",
                message="Credential values could not be restored after a failed update.",
                status_code=500,
            ) from exc


class LegacyVolcengineCredentialAdapter:
    """Expose the temporary Volcengine API contract over the canonical service."""

    def __init__(self, service: ProviderConnectionService) -> None:
        self._service = service

    def status(self, provider_id: str) -> VolcengineCredentialSetStatus:
        return _legacy_volcengine_status(self._service.status(provider_id))

    def update(
        self,
        provider_id: str,
        candidates: Mapping[ProviderCredentialConsumer, str],
    ) -> CredentialUpdateResult:
        canonical = {"llm": "text", "image": "image", "video": "video"}
        if not set(candidates).issubset(canonical):
            raise CredentialSettingsError(
                code="credential_update_invalid",
                message="The credential update contains an unsupported consumer.",
                status_code=422,
            )
        result = self._service.update(
            provider_id,
            api_keys={canonical[consumer]: value for consumer, value in candidates.items()},
        )
        return CredentialUpdateResult(
            credentials=_legacy_volcengine_status(result.provider),
            updated_consumers=tuple(candidates),
            applied_at=result.applied_at,
        )

    def test(
        self,
        provider_id: str,
        consumer: ProviderCredentialConsumer,
        candidate: str | None = None,
    ) -> CredentialTestResult:
        canonical = {"llm": "text", "image": "image", "video": "video"}
        if consumer not in canonical:
            raise CredentialSettingsError(
                code="credential_update_invalid",
                message="The credential consumer is not supported.",
                status_code=422,
            )
        result = self._service.test(
            provider_id,
            capability=canonical[consumer],
            candidate=candidate,
        )
        return CredentialTestResult(accepted=True, model_id=result.model_ref)


def _ordered_update_values(
    definition: ProviderCredentialDefinition,
    candidates: Mapping[ProviderCredentialConsumer, str],
) -> tuple[
    tuple[ProviderCredentialConsumer, ...],
    dict[str, str],
    tuple[ConsumerCredentialBinding, ...],
]:
    unknown_consumers = set(candidates).difference(definition.bindings)
    if not candidates or unknown_consumers:
        raise CredentialSettingsError(
            code="credential_update_invalid",
            message="The credential update contains an unsupported consumer.",
            status_code=422,
        )
    consumers: list[ProviderCredentialConsumer] = []
    values_by_field: dict[str, str] = {}
    bindings: list[ConsumerCredentialBinding] = []
    for consumer, binding in definition.bindings.items():
        candidate = candidates.get(consumer)
        if candidate is None:
            continue
        consumers.append(consumer)
        values_by_field[binding.dotenv_field] = normalize_credential_value(candidate)
        bindings.append(binding)
    return tuple(consumers), values_by_field, tuple(bindings)


@dataclass(frozen=True)
class ProviderHttpResponse:
    status_code: int
    body: bytes


class ProviderHttpTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> ProviderHttpResponse: ...


@dataclass(frozen=True)
class CredentialTestResult:
    accepted: bool
    model_id: str | None


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


class UrllibProviderHttpTransport:
    """Minimal standard-library transport with redirects disabled for credential probes."""

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> ProviderHttpResponse:
        request = Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        opener = build_opener(_NoRedirectHandler())
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read(max_response_bytes + 1)
                if len(body) > max_response_bytes:
                    raise OSError("Provider test response exceeded the configured limit.")
                return ProviderHttpResponse(status_code=int(response.status), body=body)
        except HTTPError as error:
            body = error.read(max_response_bytes + 1)
            if len(body) > max_response_bytes:
                body = b""
            return ProviderHttpResponse(status_code=error.code, body=body)


class VolcengineArkConnectionTester:
    """Runs the one supported non-generative Volcengine credential probe."""

    def __init__(
        self,
        *,
        transport: ProviderHttpTransport | None = None,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 64 * 1024,
    ) -> None:
        self._transport = transport or UrllibProviderHttpTransport()
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    def test(
        self,
        *,
        definition: ProviderCredentialDefinition,
        consumer: ProviderCredentialConsumer,
        candidate: str | None,
        settings: Settings,
    ) -> CredentialTestResult:
        binding = definition.binding(consumer)
        if binding.test_capability == "unsupported":
            raise CredentialSettingsError(
                code="credential_test_not_supported",
                message="This credential consumer does not support a safe connection test.",
                status_code=409,
            )

        raw_value = candidate or getattr(settings, binding.settings_field)
        if not raw_value:
            raise CredentialSettingsError(
                code="credential_not_configured",
                message="The requested credential is not configured.",
                status_code=409,
            )
        credential = normalize_credential_value(raw_value)
        endpoint = _allowlisted_chat_completions_url(
            getattr(settings, binding.endpoint_field),
            definition.allowed_test_origins,
        )
        model_id = settings.llm_front_desk_model
        payload: dict[str, object] = {
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
        }
        try:
            response = self._transport.post_json(
                url=endpoint,
                headers={
                    "Authorization": f"Bearer {credential}",
                    "Content-Type": "application/json",
                },
                payload=payload,
                timeout_seconds=self._timeout_seconds,
                max_response_bytes=self._max_response_bytes,
            )
        except (OSError, TimeoutError, URLError) as exc:
            raise CredentialSettingsError(
                code="provider_test_unavailable",
                message="The provider connection test is temporarily unavailable.",
                status_code=503,
            ) from exc

        if 200 <= response.status_code < 300:
            return CredentialTestResult(accepted=True, model_id=model_id)
        if response.status_code in {401, 403}:
            raise CredentialSettingsError(
                code="credential_test_failed",
                message="The provider rejected the supplied credential.",
                status_code=422,
            )
        if 300 <= response.status_code < 400:
            raise CredentialSettingsError(
                code="credential_test_configuration_invalid",
                message="The configured provider test endpoint redirected the request.",
                status_code=409,
            )
        raise CredentialSettingsError(
            code="provider_test_unavailable",
            message="The provider connection test is temporarily unavailable.",
            status_code=503,
        )


def _allowlisted_chat_completions_url(
    base_url: str | None,
    allowed_origins: tuple[str, ...],
) -> str:
    if not base_url:
        raise CredentialSettingsError(
            code="credential_test_configuration_invalid",
            message="The configured provider test endpoint is not valid.",
            status_code=409,
        )
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as exc:
        raise CredentialSettingsError(
            code="credential_test_configuration_invalid",
            message="The configured provider test endpoint is not valid.",
            status_code=409,
        ) from exc

    normalized_origin = (
        f"{parsed.scheme}://{parsed.hostname}" if parsed.hostname is not None else None
    )
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or port not in {None, 443}
        or normalized_origin not in allowed_origins
    ):
        raise CredentialSettingsError(
            code="credential_test_configuration_invalid",
            message="The configured provider test endpoint is not valid.",
            status_code=409,
        )

    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path = f"{path}/chat/completions"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _volcengine_ark_definition() -> ProviderCredentialDefinition:
    bindings: Mapping[ProviderCredentialConsumer, ConsumerCredentialBinding] = MappingProxyType(
        {
            "llm": ConsumerCredentialBinding(
                consumer="llm",
                dotenv_field="LLM_API_KEY",
                settings_field="llm_api_key",
                endpoint_field="llm_base_url",
                test_capability="minimal_request",
            ),
            "image": ConsumerCredentialBinding(
                consumer="image",
                dotenv_field="IMAGE_GENERATION_API_KEY",
                settings_field="image_generation_api_key",
                endpoint_field="image_generation_endpoint",
                test_capability="unsupported",
            ),
            "video": ConsumerCredentialBinding(
                consumer="video",
                dotenv_field="VIDEO_GENERATION_API_KEY",
                settings_field="video_generation_api_key",
                endpoint_field="video_generation_endpoint",
                test_capability="unsupported",
            ),
        }
    )
    return ProviderCredentialDefinition(
        provider_id="volcengine_ark",
        bindings=bindings,
        allowed_test_origins=("https://ark.cn-beijing.volces.com",),
        display_name="Volcengine Ark",
        capability_consumers=MappingProxyType({"text": "llm", "image": "image", "video": "video"}),
    )


def _siliconflow_definition() -> ProviderCredentialDefinition:
    bindings: Mapping[ProviderCredentialConsumer, ConsumerCredentialBinding] = MappingProxyType(
        {
            "text": ConsumerCredentialBinding(
                consumer="text",
                dotenv_field="SILICONFLOW_API_KEY",
                settings_field="siliconflow_api_key",
                endpoint_field="siliconflow_base_url",
                test_capability="minimal_request",
            ),
        }
    )
    return ProviderCredentialDefinition(
        provider_id="siliconflow",
        bindings=bindings,
        allowed_test_origins=("https://api.siliconflow.cn",),
        display_name="SiliconFlow",
        capability_consumers=MappingProxyType({"text": "text"}),
    )


def _tianpuyue_definition() -> ProviderCredentialDefinition:
    bindings: Mapping[ProviderCredentialConsumer, ConsumerCredentialBinding] = MappingProxyType(
        {
            "audio": ConsumerCredentialBinding(
                consumer="audio",
                dotenv_field="BGM_API_KEY",
                settings_field="bgm_api_key",
                endpoint_field="bgm_endpoint",
                test_capability="unsupported",
            ),
        }
    )
    return ProviderCredentialDefinition(
        provider_id="tianpuyue",
        bindings=bindings,
        allowed_test_origins=("https://api.tianpuyue.cn",),
        display_name="Tianpuyue",
        capability_consumers=MappingProxyType({"audio": "audio"}),
    )


def _connection_state(
    statuses: Mapping[str, ProviderCredentialCapabilitySnapshot],
) -> str:
    return (
        "configured" if any(status.configured for status in statuses.values()) else "unconfigured"
    )


def _connection_state_from_metadata(metadata: Mapping[str, object]) -> str:
    return (
        "configured"
        if any(
            isinstance(value, Mapping) and value.get("configured") is True
            for value in metadata.values()
        )
        else "unconfigured"
    )


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_siliconflow_base_url(value: str | None) -> bool:
    if not value:
        return False
    try:
        return urlsplit(value).hostname == "api.siliconflow.cn"
    except ValueError:
        return False


def _legacy_volcengine_status(
    snapshot: ProviderConnectionSnapshot,
) -> VolcengineCredentialSetStatus:
    if snapshot.provider_id != "volcengine_ark":
        raise CredentialSettingsError(
            code="credential_provider_not_supported",
            message="The requested credential provider is not supported.",
            status_code=404,
        )

    def status(capability: str) -> ProviderCredentialConsumerStatus:
        item = snapshot.credentials[capability]
        return ProviderCredentialConsumerStatus(
            configured=item.configured,
            masked_api_key=item.masked_api_key,
            source=item.source,  # type: ignore[arg-type]
            test_capability=item.test_capability,
        )

    return VolcengineCredentialSetStatus(
        llm=status("text"),
        image=status("image"),
        video=status("video"),
    )
