"""Provider-specific payload projections behind the canonical adapter boundary."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
from http.client import HTTPException
import json
import re
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import BaseHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from app.core.config import Settings
from app.schemas.provider_models import (
    ModelParameterDescriptorV1,
    ModelParameterMatrixV1,
    ProviderAdapterProfileV1,
    ReferenceInputModeV1,
    ReferenceInputPolicyV1,
)
from app.services.openrouter_policy import build_openrouter_routing_policy
from app.services.provider_credentials import (
    ProviderHttpResponse,
    ProviderHttpTransport,
    UrllibProviderHttpTransport,
)
from app.services.provider_model_catalog import TEAMOROUTER_IMAGE_PROFILE
from app.services.workflow_model_call_redaction import redact_model_call
from app.tools.media_provider_protocol import MediaApiError


class ProviderResponseContractError(ValueError):
    """A stable public error code with bounded response-shape diagnostics."""

    def __init__(self, contract_check: str, diagnostics: Mapping[str, Any] | None = None) -> None:
        super().__init__("provider_response_contract_invalid")
        self.diagnostics: dict[str, Any] = {
            **dict(diagnostics or {}),
            "stage": "provider_response",
            "contract_check": contract_check,
        }


class _ImageResponse(dict[str, object]):
    """Keep transport diagnostics outside the provider's result mapping."""

    def __init__(self, body: Mapping[str, object], diagnostics: dict[str, Any]) -> None:
        super().__init__(body)
        self.diagnostics = diagnostics


def _response_shape_diagnostics(
    response: Mapping[str, object], *, api_key: str = "", prompt: str = ""
) -> dict[str, Any]:
    def keys(value: Mapping[str, object]) -> list[str]:
        return sorted(
            _safe_contract_text(key, api_key=api_key, prompt=prompt)[:40]
            for key in value
            if isinstance(key, str)
        )[:10]

    diagnostics: dict[str, Any] = {"response_top_level_keys": keys(response)}
    data = response.get("data")
    if isinstance(data, list):
        diagnostics["data_item_count"] = len(data)
        diagnostics["data_item_keys"] = (
            keys(data[0]) if data and isinstance(data[0], Mapping) else []
        )
    return diagnostics


def _safe_contract_text(value: str, *, api_key: str, prompt: str) -> str:
    if prompt:
        value = value.replace(prompt, "[REDACTED]")
    safe, _ = redact_model_call(value, (api_key,))
    safe = re.sub(r"(?i)\b(?:https?://|data:)[^\s\"'<>]+", "[REDACTED]", safe)
    safe = re.sub(
        r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{32,}={0,2}(?![A-Za-z0-9+/=])", "[REDACTED]", safe
    )
    return " ".join(safe.split())[:300]


@dataclass(frozen=True, slots=True)
class CanonicalProviderReference:
    """A validated reference already authorized by the V2 reference boundary."""

    reference_id: str
    role: str
    input_type: str
    value: str


@dataclass(frozen=True, slots=True)
class CanonicalProviderRequest:
    """Provider-neutral input accepted by native adapter projections."""

    model_ref: str
    provider_model_id: str
    capability: str
    prompt: str
    parameters: Mapping[str, object]
    references: tuple[CanonicalProviderReference, ...] = ()


@dataclass(frozen=True, slots=True)
class AdapterValidationResult:
    accepted: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NativeProviderRequest:
    payload: Mapping[str, object]
    request_fingerprint: str
    audit: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ProviderSubmission:
    provider_task_id: str
    request_fingerprint: str
    raw: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    provider_task_id: str
    request_fingerprint: str
    state: str
    raw: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ProviderArtifact:
    media_type: str
    value: str
    provider_task_id: str
    request_fingerprint: str
    raw: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ProviderResult:
    provider_id: str
    adapter_id: str
    media_type: str
    value: str
    provider_task_id: str
    request_fingerprint: str
    publication_input: Mapping[str, object]
    raw: Mapping[str, object]


class NativeProviderTransport(Protocol):
    """Injected transport used by deterministic tests and the existing executor."""

    def submit(self, payload: Mapping[str, object]) -> Mapping[str, object]: ...

    def poll(self, provider_task_id: str) -> Mapping[str, object]: ...

    def download(self, value: str) -> Mapping[str, object]: ...


class ProviderNativeAdapter:
    """Shared validation, frozen identity, and transport lifecycle behavior."""

    profile: ProviderAdapterProfileV1

    def __init__(self, *, transport: NativeProviderTransport | None = None) -> None:
        self._transport = transport

    def capability_profile(self) -> ProviderAdapterProfileV1:
        return self.active_profile

    @property
    def active_profile(self) -> ProviderAdapterProfileV1:
        return self.profile

    def validate(
        self, request: CanonicalProviderRequest, capability: str
    ) -> AdapterValidationResult:
        profile = self.active_profile
        errors: list[str] = []
        if capability != profile.capability or request.capability != profile.capability:
            errors.append("provider_capability_mismatch")
        if request.model_ref != profile.model_ref:
            errors.append("provider_model_reference_mismatch")
        if not request.prompt.strip():
            errors.append("provider_prompt_empty")
        if len(request.references) > profile.reference_policy.max_images:
            errors.append("reference_count_exceeded")
        errors.extend(self._validate_parameters(request.parameters))
        errors.extend(self._validate_references(request.references))
        return AdapterValidationResult(accepted=not errors, errors=tuple(errors))

    def compile(self, request: CanonicalProviderRequest, resolution: Any) -> NativeProviderRequest:
        profile = self.active_profile
        validation = self.validate(request, profile.capability)
        if not validation.accepted:
            raise ValueError(validation.errors[0])
        _assert_frozen_resolution(resolution, profile)
        payload = self._compile_payload(request)
        request_fingerprint = _fingerprint(
            {
                "model_ref": profile.model_ref,
                "provider_model_id": request.provider_model_id,
                "adapter_id": profile.adapter_id,
                "transport_kind": profile.transport_kind,
                "adapter_revision": profile.adapter_revision,
                "capability_revision": profile.capability_revision,
                "payload": payload,
                "references": [reference.reference_id for reference in request.references],
            }
        )
        return NativeProviderRequest(
            payload=payload,
            request_fingerprint=request_fingerprint,
            audit={
                "provider_id": profile.model_ref.split(":", 1)[0],
                "model_ref": profile.model_ref,
                "provider_model_id": request.provider_model_id,
                "adapter_id": profile.adapter_id,
                "transport_kind": profile.transport_kind,
                "adapter_revision": profile.adapter_revision,
                "capability_revision": profile.capability_revision,
                "reference_ids": tuple(reference.reference_id for reference in request.references),
                "parameters": dict(request.parameters),
                "request_fingerprint": request_fingerprint,
            },
        )

    def submit(self, request: NativeProviderRequest) -> ProviderSubmission:
        transport = self._require_transport()
        response = _bounded_response(
            transport.submit(request.payload),
            allowed_keys={"task_id", "provider_task_id", "request_id"},
        )
        task_id = _required_string(response, "task_id", "provider_task_id")
        return ProviderSubmission(
            provider_task_id=task_id,
            request_fingerprint=str(request.audit["request_fingerprint"]),
            raw=dict(response),
        )

    def poll(self, submission: ProviderSubmission) -> ProviderStatus:
        transport = self._require_transport()
        response = _bounded_response(
            transport.poll(submission.provider_task_id),
            allowed_keys={
                "status",
                "state",
                "file_id",
                "download_url",
                "url",
                "request_id",
                "error_code",
                "message",
            },
        )
        state = _required_string(response, "status", "state")
        return ProviderStatus(
            provider_task_id=submission.provider_task_id,
            request_fingerprint=submission.request_fingerprint,
            state=state,
            raw=dict(response),
        )

    def download(self, status: ProviderStatus) -> ProviderArtifact:
        transport = self._require_transport()
        value = _required_string(status.raw, "file_id", "download_url", "url")
        response = _bounded_response(
            transport.download(value),
            allowed_keys={"value", "file_id", "download_url", "url", "mime_type", "media_type"},
        )
        artifact_value = _required_string(response, "value", "file_id", "download_url", "url")
        return ProviderArtifact(
            media_type=self._media_type,
            value=artifact_value,
            provider_task_id=status.provider_task_id,
            request_fingerprint=status.request_fingerprint,
            raw=dict(response),
        )

    def normalize(self, artifact: ProviderArtifact) -> ProviderResult:
        if not artifact.value.strip():
            raise ValueError("provider_result_contract_invalid")
        return ProviderResult(
            provider_id=self.active_profile.model_ref.split(":", 1)[0],
            adapter_id=self.active_profile.adapter_id,
            media_type=artifact.media_type,
            value=artifact.value,
            provider_task_id=artifact.provider_task_id,
            request_fingerprint=artifact.request_fingerprint,
            publication_input={
                "media_type": artifact.media_type,
                "value": artifact.value,
            },
            raw=artifact.raw,
        )

    def request_fingerprint(self, request: CanonicalProviderRequest) -> str:
        return self.compile(
            request,
            _resolution_for_profile(self.active_profile),
        ).request_fingerprint

    @property
    def _media_type(self) -> str:
        return "image" if self.active_profile.capability == "image" else "video"

    def _require_transport(self) -> NativeProviderTransport:
        if self._transport is None:
            raise ValueError("provider_transport_unavailable")
        return self._transport

    def _compile_payload(self, request: CanonicalProviderRequest) -> Mapping[str, object]:
        raise NotImplementedError

    def _validate_parameters(self, parameters: Mapping[str, object]) -> tuple[str, ...]:
        return _validate_parameter_matrix(self.active_profile.parameter_matrix, parameters)

    def _validate_references(
        self,
        references: tuple[CanonicalProviderReference, ...],
    ) -> tuple[str, ...]:
        profile = self.active_profile
        allowed_modes = {
            mode.mode for mode in profile.reference_policy.modes if mode.max_references > 0
        }
        if references and not allowed_modes.intersection(profile.accepted_input_modes):
            return ("reference_input_mode_unsupported",)
        allowed_roles = {
            role
            for mode in profile.reference_policy.modes
            if mode.mode in allowed_modes
            for role in mode.allowed_roles
        }
        if any(reference.role not in allowed_roles for reference in references):
            return ("reference_input_mode_unsupported",)
        if any(
            reference.input_type not in {"image_url", "data_url", "provider_file_id"}
            for reference in references
        ):
            return ("provider_reference_input_invalid",)
        if any(not reference.value.strip() for reference in references):
            return ("provider_reference_input_invalid",)
        return ()


class OpenRouterImageTransport:
    """Bounded synchronous transport for OpenRouter's dedicated image endpoint."""

    def __init__(
        self,
        settings: Settings,
        *,
        http_transport: ProviderHttpTransport | None = None,
    ) -> None:
        self._api_key = (settings.openrouter_api_key or "").strip()
        self._base_url = settings.openrouter_image_base_url.rstrip("/")
        self._http = http_transport or UrllibProviderHttpTransport()

    def submit(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        if not self._api_key:
            raise ValueError("provider_configuration_missing")
        if self._base_url != "https://openrouter.ai/api/v1":
            raise ValueError("provider_base_url_invalid")
        response = self._http.post_json(
            url=f"{self._base_url}/images",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            payload=dict(payload),
            timeout_seconds=120.0,
            max_response_bytes=28_000_000,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise _image_http_error(response, api_key=self._api_key)
        try:
            parsed = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("provider_response_contract_invalid") from error
        if not isinstance(parsed, Mapping):
            raise ValueError("provider_response_contract_invalid")
        return parsed

    def poll(self, provider_task_id: str) -> Mapping[str, object]:
        del provider_task_id
        raise ValueError("provider_task_not_pollable")

    def download(self, value: str) -> Mapping[str, object]:
        del value
        raise ValueError("provider_task_not_pollable")


class OpenRouterImageAdapter(ProviderNativeAdapter):
    """Project one canonical image request into the fixed OpenRouter route."""

    profile = ProviderAdapterProfileV1(
        model_ref="openrouter:openai/gpt-image-2",
        adapter_id="openrouter-image-native",
        transport_kind="openrouter_images_native",
        capability="image",
        request_mode="image_generation",
        accepted_input_modes=("text_only", "native_reference_slots"),
        reference_policy=ReferenceInputPolicyV1(
            modes=(
                ReferenceInputModeV1(mode="text_only", max_references=0),
                ReferenceInputModeV1(
                    mode="native_reference_slots",
                    max_references=16,
                    allowed_roles=("product_reference", "scene_reference", "character_reference"),
                ),
            ),
            max_images=16,
        ),
        parameter_schema_id="openrouter-gpt-image-2-v1",
        parameter_matrix=ModelParameterMatrixV1(
            schema_id="openrouter-gpt-image-2-v1",
            revision="openrouter-gpt-image-2-v1-v1",
            descriptors=(
                ModelParameterDescriptorV1(
                    name="size",
                    value_type="enum",
                    allowed_values=("1024x1024", "1536x1024", "1024x1536", "auto"),
                ),
                ModelParameterDescriptorV1(
                    name="quality",
                    value_type="enum",
                    allowed_values=("low", "medium", "high", "auto"),
                ),
                ModelParameterDescriptorV1(
                    name="background",
                    value_type="enum",
                    allowed_values=("transparent", "opaque", "auto"),
                ),
                ModelParameterDescriptorV1(
                    name="output_format",
                    value_type="enum",
                    allowed_values=("png", "jpeg", "webp"),
                ),
                ModelParameterDescriptorV1(
                    name="output_compression",
                    value_type="integer",
                    minimum=0,
                    maximum=100,
                ),
                ModelParameterDescriptorV1(
                    name="resolution",
                    value_type="enum",
                    allowed_values=("1K", "2K", "4K"),
                ),
                ModelParameterDescriptorV1(
                    name="aspect_ratio",
                    value_type="enum",
                    allowed_values=("1:1", "16:9", "9:16", "4:3", "3:4"),
                ),
            ),
        ),
        result_protocol="image_data",
        supports_remote_task_lookup=False,
        supports_provider_idempotency=False,
        release_tier="optional",
        conformance_status="unverified",
        adapter_revision="openrouter-image-native-v1",
        capability_revision="openrouter-openai/gpt-image-2-v1",
    )
    routing_policy = build_openrouter_routing_policy(
        model_ref=profile.model_ref,
        adapter_revision=profile.adapter_revision,
        capability_revision=profile.capability_revision,
        operation_contract="openrouter-gpt-image-2-v1",
    )

    def compile(self, request: CanonicalProviderRequest, resolution: Any) -> NativeProviderRequest:
        validation = self.validate(request, self.profile.capability)
        if not validation.accepted:
            raise ValueError(validation.errors[0])
        _assert_frozen_resolution(resolution, self.profile)
        routing_id = _resolution_value(resolution, "openrouter_routing_policy_id")
        routing_digest = _resolution_value(resolution, "openrouter_routing_policy_digest")
        if (
            routing_id != self.routing_policy.routing_policy_id
            or routing_digest != self.routing_policy.routing_policy_digest
        ):
            raise ValueError("openrouter_routing_contract_invalid")
        payload = self._compile_payload(request)
        audit = {
            "provider_id": "openrouter",
            "model_ref": self.profile.model_ref,
            "provider_model_id": request.provider_model_id,
            "adapter_id": self.profile.adapter_id,
            "transport_kind": self.profile.transport_kind,
            "adapter_revision": self.profile.adapter_revision,
            "capability_revision": self.profile.capability_revision,
            "credential_revision": _resolution_value(resolution, "credential_revision"),
            "reference_ids": tuple(reference.reference_id for reference in request.references),
            "parameters": dict(request.parameters),
            "openrouter_routing_policy_id": routing_id,
            "openrouter_routing_policy_digest": routing_digest,
        }
        request_fingerprint = _fingerprint({**audit, "payload": payload})
        return NativeProviderRequest(
            payload=payload,
            request_fingerprint=request_fingerprint,
            audit={**audit, "request_fingerprint": request_fingerprint},
        )

    def request_fingerprint(self, request: CanonicalProviderRequest) -> str:
        return self.compile(
            request,
            {
                **_resolution_for_profile(self.profile),
                "openrouter_routing_policy_id": self.routing_policy.routing_policy_id,
                "openrouter_routing_policy_digest": self.routing_policy.routing_policy_digest,
            },
        ).request_fingerprint

    def _compile_payload(self, request: CanonicalProviderRequest) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "model": request.provider_model_id,
            "prompt": request.prompt,
            "n": 1,
            "provider": {
                "only": list(self.routing_policy.provider_only),
                "require_parameters": self.routing_policy.require_parameters,
                "allow_fallbacks": self.routing_policy.allow_fallbacks,
            },
        }
        payload.update(request.parameters)
        if request.references:
            payload["input_references"] = [
                {
                    "type": "input_image",
                    "role": reference.role,
                    "source": {
                        "type": reference.input_type,
                        "value": reference.value,
                    },
                }
                for reference in request.references
            ]
        return payload

    def _validate_parameters(self, parameters: Mapping[str, object]) -> tuple[str, ...]:
        errors = super()._validate_parameters(parameters)
        if errors:
            return errors
        if "size" in parameters and ({"resolution", "aspect_ratio"} & set(parameters)):
            return ("model_parameter_incompatible",)
        return ()

    def _validate_references(
        self,
        references: tuple[CanonicalProviderReference, ...],
    ) -> tuple[str, ...]:
        errors = super()._validate_references(references)
        if errors:
            return errors
        for reference in references:
            if reference.input_type == "image_url":
                parsed = urlsplit(reference.value)
                if parsed.scheme != "https" or not parsed.netloc or len(reference.value) > 8_192:
                    return ("provider_reference_input_invalid",)
            elif reference.input_type == "data_url":
                if (
                    not reference.value.startswith("data:image/")
                    or len(reference.value) > 8_000_000
                ):
                    return ("provider_reference_input_invalid",)
            else:
                return ("provider_reference_input_invalid",)
        return ()

    def submit(self, request: NativeProviderRequest) -> ProviderSubmission:
        transport = self._require_transport()
        response = _bounded_openrouter_image_response(transport.submit(request.payload))
        return ProviderSubmission(
            provider_task_id=f"sync:{request.request_fingerprint}",
            request_fingerprint=request.request_fingerprint,
            raw=response,
        )

    def poll(self, submission: ProviderSubmission) -> ProviderStatus:
        return ProviderStatus(
            provider_task_id=submission.provider_task_id,
            request_fingerprint=submission.request_fingerprint,
            state="completed",
            raw=submission.raw,
        )

    def download(self, status: ProviderStatus) -> ProviderArtifact:
        data = status.raw.get("data")
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
            raise ValueError("provider_response_contract_invalid")
        item = data[0]
        value = _required_string(item, "b64_json")
        media_type = _required_string(item, "media_type")
        decoded = _decode_raster(value, media_type)
        return ProviderArtifact(
            media_type="image",
            value=value,
            provider_task_id=status.provider_task_id,
            request_fingerprint=status.request_fingerprint,
            raw={"media_type": media_type, "decoded_size": len(decoded)},
        )


_TEAMOROUTER_BASE_URL = "https://api.teamorouter.com/v1"
# GPT Image 2 can take minutes; TeamoRouter recommends a 300 s client timeout.
_TEAMOROUTER_TIMEOUT_SECONDS = 300.0
_TEAMOROUTER_MAX_RESPONSE_BYTES = 64_000_000
# The OpenAI edits endpoint treats input images as the canvas to modify, while
# Canvas bindings are references (as with Seedream). Live checks (2026-10-20)
# showed a descriptive node prompt returns the reference almost unchanged; a
# layout-first edit instruction with high input fidelity yields the requested
# views while keeping the subject's identity.
TEAMOROUTER_REFERENCE_INSTRUCTION = (
    "Turn the attached reference image into a NEW image that satisfies the required "
    "layout below. Keep the subject's exact identity, shape, materials and colors; change "
    "the composition, framing and viewpoints as the layout requires."
)
_TEAMOROUTER_REQUEST_FIELDS = (
    "size",
    "quality",
    "background",
    "output_format",
    "output_compression",
)


class RawHttpPostTransport(Protocol):
    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> ProviderHttpResponse: ...

    def get(
        self,
        *,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> ProviderHttpResponse: ...


class _NoImageRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class UrllibRawHttpPostTransport:
    """POST prepared bytes or GET an HTTPS image, optionally via one proxy."""

    def __init__(self, *, proxy_url: str | None = None) -> None:
        self.proxy_url = proxy_url

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> ProviderHttpResponse:
        return UrllibProviderHttpTransport._open(
            request=Request(url, data=body, headers=headers, method="POST"),
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            proxy_url=self.proxy_url,
        )

    def get(
        self,
        *,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> ProviderHttpResponse:
        handlers: list[BaseHandler] = [_NoImageRedirectHandler()]
        if self.proxy_url is not None:
            handlers.append(ProxyHandler({"http": self.proxy_url, "https": self.proxy_url}))
        opener = build_opener(*handlers)
        redirects_remaining = 3
        while True:
            if not url.startswith("https://"):
                raise ValueError("Image download requires HTTPS.")
            try:
                response = opener.open(
                    Request(url, headers=headers, method="GET"), timeout=timeout_seconds
                )
            except HTTPError as error:
                response = error
            with response:
                body = response.read(max_response_bytes + 1)
                if len(body) > max_response_bytes:
                    raise OSError("Image download exceeded the configured limit.")
                status = int(response.status)
                location = response.headers.get("Location")
            if status not in {301, 302, 303, 307, 308} or not location:
                return ProviderHttpResponse(status_code=status, body=body)
            if not redirects_remaining:
                raise OSError("Image download redirect limit exceeded.")
            url = urljoin(url, location)
            redirects_remaining -= 1


class TeamoRouterImageTransport:
    """Synchronous OpenAI Images transport fixed to the TeamoRouter endpoint."""

    def __init__(
        self,
        settings: Settings,
        *,
        http_transport: RawHttpPostTransport | None = None,
    ) -> None:
        self._api_key = (settings.teamorouter_api_key or "").strip()
        self._base_url = settings.teamorouter_base_url.rstrip("/")
        # Only TeamoRouter traffic uses this proxy; other providers stay direct.
        self._proxy_url = (settings.teamorouter_proxy_url or "").strip() or None
        self._http = http_transport or UrllibRawHttpPostTransport(proxy_url=self._proxy_url)

    def submit(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        if not self._api_key:
            raise ValueError("provider_configuration_missing")
        if self._base_url != _TEAMOROUTER_BASE_URL:
            raise ValueError("provider_base_url_invalid")
        if self._proxy_url is not None and not _valid_http_proxy_url(self._proxy_url):
            raise ValueError("provider_proxy_invalid")
        fields = payload.get("fields")
        images = payload.get("images")
        if not isinstance(fields, Mapping) or not isinstance(images, list):
            raise ValueError("provider_request_contract_invalid")
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if images:
            boundary = f"adcraft-{uuid4().hex}"
            url = f"{self._base_url}/images/edits"
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            body = _multipart_body(boundary, fields, [_data_url_file(item) for item in images])
        else:
            url = f"{self._base_url}/images/generations"
            headers["Content-Type"] = "application/json"
            body = json.dumps(dict(fields), separators=(",", ":")).encode("utf-8")
        response = self._http.post(
            url=url,
            headers=headers,
            body=body,
            timeout_seconds=_TEAMOROUTER_TIMEOUT_SECONDS,
            max_response_bytes=_TEAMOROUTER_MAX_RESPONSE_BYTES,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise _image_http_error(response, api_key=self._api_key)
        diagnostics: dict[str, Any] = {
            "http_status": response.status_code,
            "response_body_bytes": len(response.body),
        }
        try:
            parsed = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderResponseContractError("body_not_json", diagnostics) from error
        if not isinstance(parsed, Mapping):
            raise ProviderResponseContractError("body_not_object", diagnostics)
        prompt = fields.get("prompt")
        prompt = prompt if isinstance(prompt, str) else ""
        diagnostics.update(
            _response_shape_diagnostics(parsed, api_key=self._api_key, prompt=prompt)
        )
        nested = parsed.get("error")
        sources = (nested, parsed) if isinstance(nested, Mapping) else (parsed,)
        for source_key, diagnostic_key in (
            ("code", "provider_error_code"),
            ("message", "provider_message"),
        ):
            for source in sources:
                value = source.get(source_key)
                if isinstance(value, str) and value.strip():
                    diagnostics[diagnostic_key] = _safe_contract_text(
                        value, api_key=self._api_key, prompt=prompt
                    )
                    break
        self._inline_image_url(parsed, diagnostics)
        return _ImageResponse(parsed, diagnostics)

    def _inline_image_url(
        self, response: Mapping[str, object], diagnostics: dict[str, Any]
    ) -> None:
        data = response.get("data")
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            return
        item = data[0]
        value = item.get("b64_json")
        if isinstance(value, str) and value:
            return
        url = item.get("url")
        if not isinstance(url, str):
            return
        diagnostics["image_url"] = True
        try:
            if not url.startswith("https://"):
                raise ValueError("Image download requires HTTPS.")
            downloaded = self._http.get(
                url=url,
                headers={},
                timeout_seconds=120.0,
                max_response_bytes=_TEAMOROUTER_MAX_RESPONSE_BYTES,
            )
            if (
                not 200 <= downloaded.status_code < 300
                or len(downloaded.body) > _TEAMOROUTER_MAX_RESPONSE_BYTES
            ):
                raise ValueError("Image download response rejected.")
        except (OSError, ValueError, HTTPException):
            # Signed URLs and transport exception messages must never cross this boundary.
            raise ProviderResponseContractError(
                "image_url_download_failed", {**diagnostics, "retryable": True}
            ) from None
        item["b64_json"] = base64.b64encode(downloaded.body).decode("ascii")

    def poll(self, provider_task_id: str) -> Mapping[str, object]:
        del provider_task_id
        raise ValueError("provider_task_not_pollable")

    def download(self, value: str) -> Mapping[str, object]:
        del value
        raise ValueError("provider_task_not_pollable")


def _image_http_error(response: ProviderHttpResponse, *, api_key: str) -> MediaApiError:
    metadata: dict[str, Any] = {"http_status": response.status_code}
    if len(response.body) <= 16_384:
        try:
            parsed = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            parsed = None
        if isinstance(parsed, dict):
            nested = parsed.get("error")
            sources = (nested, parsed) if isinstance(nested, dict) else (parsed,)
            details: dict[str, str] = {}
            for key in ("code", "message", "request_id", "requestId"):
                for source in sources:
                    value = source.get(key)
                    if isinstance(value, str) and value.strip():
                        details[key] = value
                        break
            # Only bounded standard diagnostic fields cross the transport boundary.
            # Never retain a raw response, provider stack, or echoed credentials.
            safe_details, _ = redact_model_call(details, (api_key,))
            metadata["response_body"] = safe_details
    return MediaApiError("provider_request_failed", metadata)


class TeamoRouterImageAdapter(ProviderNativeAdapter):
    """Project one canonical image request into TeamoRouter GPT Image 2."""

    profile = ProviderAdapterProfileV1.model_validate(TEAMOROUTER_IMAGE_PROFILE)

    def __init__(
        self,
        *,
        transport: NativeProviderTransport | None = None,
        profile: ProviderAdapterProfileV1 | None = None,
    ) -> None:
        super().__init__(transport=transport)
        if profile is not None:
            if profile.transport_kind != "teamorouter_images_native":
                raise ValueError("provider_adapter_profile_invalid")
            self.profile = profile

    def _compile_payload(self, request: CanonicalProviderRequest) -> Mapping[str, object]:
        prompt = _layout_first_edit_prompt(request.prompt) if request.references else request.prompt
        fields: dict[str, object] = {
            "model": request.provider_model_id,
            "prompt": prompt,
            "n": 1,
        }
        if request.references:
            fields["input_fidelity"] = "high"
        fields.update(
            {
                name: request.parameters[name]
                for name in _TEAMOROUTER_REQUEST_FIELDS
                if name in request.parameters
            }
        )
        return {
            "fields": fields,
            "images": [reference.value for reference in request.references],
        }

    def _validate_references(
        self,
        references: tuple[CanonicalProviderReference, ...],
    ) -> tuple[str, ...]:
        # The OpenAI Images API has no reference roles; order alone is meaningful.
        if references and "native_reference_slots" not in self.profile.accepted_input_modes:
            return ("reference_input_mode_unsupported",)
        for reference in references:
            if reference.input_type != "data_url":
                return ("provider_reference_input_invalid",)
            try:
                _data_url_file(reference.value)
            except ValueError:
                return ("provider_reference_input_invalid",)
        return ()

    def submit(self, request: NativeProviderRequest) -> ProviderSubmission:
        transport = self._require_transport()
        response = transport.submit(request.payload)
        value, media_type = _single_b64_raster(response)
        return ProviderSubmission(
            provider_task_id=f"sync:{request.request_fingerprint}",
            request_fingerprint=request.request_fingerprint,
            raw={"data": [{"b64_json": value, "media_type": media_type}]},
        )

    def poll(self, submission: ProviderSubmission) -> ProviderStatus:
        return ProviderStatus(
            provider_task_id=submission.provider_task_id,
            request_fingerprint=submission.request_fingerprint,
            state="completed",
            raw=submission.raw,
        )

    def download(self, status: ProviderStatus) -> ProviderArtifact:
        value, media_type = _single_b64_raster(status.raw)
        return ProviderArtifact(
            media_type="image",
            value=value,
            provider_task_id=status.provider_task_id,
            request_fingerprint=status.request_fingerprint,
            raw={"media_type": media_type},
        )


def _valid_http_proxy_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        parsed.port  # noqa: B018 - raises ValueError for a malformed port.
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


def _layout_first_edit_prompt(prompt: str) -> str:
    """Lead an edit with its deterministic layout rules, then the descriptive prompt."""

    requirements: list[str] = []
    prohibited: list[str] = []
    section: list[str] | None = None
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped == "Required assertions:":
            section = requirements
        elif stripped == "Prohibited behavior:":
            section = prohibited
        elif section is not None and stripped.startswith("- "):
            item = stripped[2:]
            if item.startswith("[") and "]" in item:
                item = item.split("]", 1)[1].strip()
            section.append(item)
        elif stripped:
            section = None
    rules = ""
    if requirements:
        rules += "Required layout and rules:\n" + "".join(f"- {item}\n" for item in requirements)
    if prohibited:
        rules += "Prohibited:\n" + "".join(f"- {item}\n" for item in prohibited)
    return f"{TEAMOROUTER_REFERENCE_INSTRUCTION}\n{rules}\nSubject and style details:\n{prompt}"


def _single_b64_raster(response: Mapping[str, object]) -> tuple[str, str]:
    diagnostics = (
        response.diagnostics
        if isinstance(response, _ImageResponse)
        else _response_shape_diagnostics(response)
        if isinstance(response, Mapping)
        else {}
    )
    data = response.get("data") if isinstance(response, Mapping) else None
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise ProviderResponseContractError("data_not_single_item", diagnostics)
    value = data[0].get("b64_json")
    if not isinstance(value, str) or not value:
        raise ProviderResponseContractError("b64_json_missing", diagnostics)
    try:
        head = base64.b64decode(value[:64], validate=True)
    except (binascii.Error, ValueError) as error:
        raise ProviderResponseContractError("b64_json_invalid", diagnostics) from error
    try:
        media_type = _raster_media_type(head)
    except ProviderResponseContractError as error:
        raise ProviderResponseContractError("raster_type_unsupported", diagnostics) from error
    try:
        _decode_raster(value, media_type)
    except ValueError as error:
        raise ProviderResponseContractError("raster_decode_failed", diagnostics) from error
    return value, media_type


def _raster_media_type(head: bytes) -> str:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    raise ProviderResponseContractError("raster_type_unsupported")


def _data_url_file(value: object) -> tuple[str, bytes]:
    if not isinstance(value, str) or not value.startswith("data:image/"):
        raise ValueError("provider_reference_input_invalid")
    header, separator, encoded = value.partition(",")
    mime_type = header[len("data:") :].split(";", 1)[0]
    if not separator or ";base64" not in header or len(value) > 8_000_000:
        raise ValueError("provider_reference_input_invalid")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("provider_reference_input_invalid") from error
    if not content:
        raise ValueError("provider_reference_input_invalid")
    return mime_type, content


def _multipart_body(
    boundary: str,
    fields: Mapping[str, object],
    files: list[tuple[str, bytes]],
) -> bytes:
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
            ).encode("utf-8")
        )
    for index, (mime_type, content) in enumerate(files, start=1):
        extension = mime_type.split("/", 1)[1]
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="image[]"; '
                f'filename="reference-{index}.{extension}"\r\n'
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8")
            + content
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts)


class MiniMaxVideoAdapter(ProviderNativeAdapter):
    """Project first-frame image-to-video requests into MiniMax task payloads."""

    def __init__(
        self,
        *,
        provider_model_id: str | None = None,
        transport: NativeProviderTransport | None = None,
    ) -> None:
        super().__init__(transport=transport)
        if provider_model_id is not None:
            self._profile_for_model = self._profile_for_provider_model(provider_model_id)
        else:
            self._profile_for_model = None

    @property
    def effective_profile(self) -> ProviderAdapterProfileV1:
        return self._profile_for_model or self.profile

    @property
    def active_profile(self) -> ProviderAdapterProfileV1:
        return self.effective_profile

    profile = ProviderAdapterProfileV1(
        model_ref="minimax:MiniMax-Hailuo-2.3",
        adapter_id="minimax-video-native",
        transport_kind="minimax_video_native",
        capability="video",
        request_mode="video_generation",
        accepted_input_modes=("text_only", "text_plus_single_first_frame_image"),
        reference_policy=ReferenceInputPolicyV1(
            modes=(
                ReferenceInputModeV1(mode="text_only", max_references=0),
                ReferenceInputModeV1(
                    mode="text_plus_single_first_frame_image",
                    max_references=1,
                    allowed_roles=("storyboard", "scene_reference", "character_turnaround"),
                ),
            ),
            max_images=1,
        ),
        parameter_schema_id="minimax-hailuo-i2v-v1",
        parameter_matrix=ModelParameterMatrixV1(
            schema_id="minimax-hailuo-i2v-v1",
            revision="minimax-hailuo-i2v-v1",
            descriptors=(
                ModelParameterDescriptorV1(
                    name="duration",
                    value_type="integer",
                    minimum=6,
                    maximum=10,
                ),
                ModelParameterDescriptorV1(
                    name="resolution",
                    value_type="enum",
                    allowed_values=("768P", "1080P"),
                ),
                ModelParameterDescriptorV1(
                    name="aspect_ratio",
                    value_type="enum",
                    allowed_values=("16:9", "9:16", "1:1"),
                ),
                ModelParameterDescriptorV1(name="generate_audio", value_type="boolean"),
            ),
            legal_combinations=(
                {"duration": 6, "resolution": "768P"},
                {"duration": 6, "resolution": "1080P"},
                {"duration": 10, "resolution": "768P"},
                {"duration": 10, "resolution": "1080P"},
            ),
        ),
        result_protocol="async_file",
        supports_remote_task_lookup=True,
        supports_provider_idempotency=True,
        release_tier="optional",
        conformance_status="unverified",
        adapter_revision="minimax-video-native-v1",
        capability_revision="minimax-hailuo-i2v-v1",
    )

    _MODELS = (
        "MiniMax-Hailuo-2.3",
        "MiniMax-Hailuo-2.3-Fast",
        "MiniMax-Hailuo-02",
    )

    def _profile_for_provider_model(self, provider_model_id: str) -> ProviderAdapterProfileV1:
        if provider_model_id not in self._MODELS:
            raise ValueError("model_adapter_unavailable")
        return self.profile.model_copy(
            update={
                "model_ref": f"minimax:{provider_model_id}",
                "capability_revision": f"minimax-{provider_model_id}-i2v-v1",
            }
        )

    def _compile_payload(self, request: CanonicalProviderRequest) -> Mapping[str, object]:
        if len(request.references) > 1:
            raise ValueError("reference_count_exceeded")
        payload: dict[str, object] = {
            "model": request.provider_model_id,
            "prompt": request.prompt,
        }
        payload.update(request.parameters)
        if request.references:
            payload["first_frame_image"] = request.references[0].value
        return payload

    def _validate_parameters(self, parameters: Mapping[str, object]) -> tuple[str, ...]:
        return super()._validate_parameters(parameters)

    def normalize(self, artifact: ProviderArtifact) -> ProviderResult:
        result = super().normalize(artifact)
        return result


class ArkMediaAdapter(ProviderNativeAdapter):
    """Common adapter registration facade for the existing Ark native paths."""

    def __init__(
        self,
        profile: ProviderAdapterProfileV1,
        *,
        transport: NativeProviderTransport | None = None,
    ) -> None:
        super().__init__(transport=transport)
        if profile.transport_kind not in {"ark_image_native", "ark_video_native"}:
            raise ValueError("provider_adapter_profile_invalid")
        self.profile = profile

    def _compile_payload(self, request: CanonicalProviderRequest) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "model": request.provider_model_id,
            "prompt": request.prompt,
        }
        payload.update(request.parameters)
        if request.references:
            payload["references"] = [
                {
                    "role": reference.role,
                    "input_type": reference.input_type,
                    "value": reference.value,
                }
                for reference in request.references
            ]
        return payload


def _assert_frozen_resolution(resolution: Any, profile: ProviderAdapterProfileV1) -> None:
    if isinstance(resolution, Mapping):
        actual = resolution
        for field, expected in (
            ("model_ref", profile.model_ref),
            ("adapter_id", profile.adapter_id),
            ("transport_kind", profile.transport_kind),
            ("adapter_revision", profile.adapter_revision),
            ("capability_revision", profile.capability_revision),
        ):
            if actual.get(field) != expected:
                raise ValueError("provider_payload_resolution_mismatch")
        return
    for field, expected in (
        ("model_ref", profile.model_ref),
        ("adapter_id", profile.adapter_id),
        ("transport_kind", profile.transport_kind),
        ("adapter_revision", profile.adapter_revision),
        ("capability_revision", profile.capability_revision),
    ):
        if getattr(resolution, field, None) != expected:
            raise ValueError("provider_payload_resolution_mismatch")


def _resolution_for_profile(profile: ProviderAdapterProfileV1) -> dict[str, str]:
    return {
        "model_ref": profile.model_ref,
        "adapter_id": profile.adapter_id,
        "transport_kind": profile.transport_kind,
        "adapter_revision": profile.adapter_revision,
        "capability_revision": profile.capability_revision,
    }


def _resolution_value(resolution: Any, field: str) -> object:
    if isinstance(resolution, Mapping):
        return resolution.get(field)
    return getattr(resolution, field, None)


def _required_string(source: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise ValueError("provider_response_contract_invalid")


def _validate_parameter_matrix(
    matrix: ModelParameterMatrixV1 | None,
    parameters: Mapping[str, object],
) -> tuple[str, ...]:
    if matrix is None:
        return ()
    descriptors = {descriptor.name: descriptor for descriptor in matrix.descriptors}
    if set(parameters).difference(descriptors):
        return ("model_parameter_incompatible",)
    if any(
        descriptor.required and descriptor.name not in parameters
        for descriptor in matrix.descriptors
    ):
        return ("model_parameter_incompatible",)
    if any(
        not _parameter_value_matches(descriptors[name], value) for name, value in parameters.items()
    ):
        return ("model_parameter_incompatible",)
    constrained_keys = {key for combination in matrix.legal_combinations for key in combination}
    constrained_parameters = {
        key: value for key, value in parameters.items() if key in constrained_keys
    }
    if constrained_parameters and not any(
        all(combination.get(key) == value for key, value in constrained_parameters.items())
        for combination in matrix.legal_combinations
    ):
        return ("model_parameter_incompatible",)
    return ()


def _parameter_value_matches(
    descriptor: ModelParameterDescriptorV1,
    value: object,
) -> bool:
    if descriptor.value_type == "integer" and (
        not isinstance(value, int) or isinstance(value, bool)
    ):
        return False
    if descriptor.value_type == "number" and (
        not isinstance(value, (int, float)) or isinstance(value, bool)
    ):
        return False
    if descriptor.value_type in {"string", "enum"} and not isinstance(value, str):
        return False
    if descriptor.value_type == "boolean" and not isinstance(value, bool):
        return False
    if descriptor.allowed_values and value not in descriptor.allowed_values:
        return False
    if descriptor.minimum is not None and value < descriptor.minimum:
        return False
    if descriptor.maximum is not None and value > descriptor.maximum:
        return False
    return True


def _bounded_response(
    response: Mapping[str, object],
    *,
    allowed_keys: set[str],
) -> dict[str, object]:
    if not isinstance(response, Mapping) or set(response).difference(allowed_keys):
        raise ValueError("provider_response_contract_invalid")
    bounded: dict[str, object] = {}
    for key, value in response.items():
        if isinstance(value, str):
            if len(value) > 4_096:
                raise ValueError("provider_response_contract_invalid")
            bounded[key] = value
        elif value is None or isinstance(value, (bool, int, float)):
            bounded[key] = value
        else:
            raise ValueError("provider_response_contract_invalid")
    if len(json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))) > 65_536:
        raise ValueError("provider_response_contract_invalid")
    return bounded


def _bounded_openrouter_image_response(response: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(response, Mapping) or set(response).difference({"data", "model"}):
        raise ValueError("provider_response_contract_invalid")
    model = response.get("model")
    if model is not None and model != "openai/gpt-image-2":
        raise ValueError("provider_response_contract_invalid")
    data = response.get("data")
    if not isinstance(data, list) or len(data) != 1:
        raise ValueError("provider_response_contract_invalid")
    item = data[0]
    if not isinstance(item, Mapping) or set(item) != {"b64_json", "media_type"}:
        raise ValueError("provider_response_contract_invalid")
    value = _required_string(item, "b64_json")
    media_type = _required_string(item, "media_type")
    _decode_raster(value, media_type)
    bounded: dict[str, object] = {
        "data": [{"b64_json": value, "media_type": media_type}],
    }
    if isinstance(model, str):
        bounded["model"] = model
    return bounded


def _decode_raster(value: str, media_type: str) -> bytes:
    if media_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError("provider_response_contract_invalid")
    if len(value) > 28_000_000:
        raise ValueError("provider_response_contract_invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("provider_response_contract_invalid") from error
    if not decoded or len(decoded) > 20 * 1024 * 1024:
        raise ValueError("provider_response_contract_invalid")
    valid_signature = (media_type == "image/png" and decoded.startswith(b"\x89PNG\r\n\x1a\n")) or (
        media_type == "image/jpeg" and decoded.startswith(b"\xff\xd8\xff")
    )
    if media_type == "image/webp":
        valid_signature = (
            len(decoded) >= 12 and decoded.startswith(b"RIFF") and decoded[8:12] == b"WEBP"
        )
    if not valid_signature:
        raise ValueError("provider_response_contract_invalid")
    return decoded


def _fingerprint(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
