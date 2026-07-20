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

    def binding(self, consumer: ProviderCredentialConsumer) -> ConsumerCredentialBinding:
        return self.bindings[consumer]


class ProviderCredentialRegistry:
    """Owns the provider-to-consumer credential mapping used by settings services."""

    def __init__(
        self,
        definitions: tuple[ProviderCredentialDefinition, ...] | None = None,
    ) -> None:
        provider_definitions = definitions or (_volcengine_ark_definition(),)
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

    def replace_values(self, values: Mapping[str, str]) -> DotenvSnapshot:
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

    def _validate_values(self, values: Mapping[str, str]) -> None:
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


def _replace_dotenv_values(content: str, values: Mapping[str, str]) -> str:
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
        line_ending = "\r\n" if line.endswith("\r\n") else "\n"
        output.append(_dotenv_assignment(field, values[field], line_ending))
        replaced_fields.add(field)

    if output and not output[-1].endswith(("\n", "\r")):
        output[-1] = f"{output[-1]}\n"
    for field, value in values.items():
        if field not in replaced_fields:
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
        values: Mapping[str, str],
        bindings: Iterable[ConsumerCredentialBinding],
    ) -> Settings:
        bindings_by_field = {binding.dotenv_field: binding for binding in bindings}
        _validate_runtime_values(values, bindings_by_field)
        for field, value in values.items():
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
    values: Mapping[str, str],
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
    )
