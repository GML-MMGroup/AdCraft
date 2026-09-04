"""Provider-specific payload projections behind the canonical adapter boundary."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

from app.core.config import Settings
from app.schemas.provider_models import (
    ModelParameterDescriptorV1,
    ModelParameterMatrixV1,
    ProviderAdapterProfileV1,
    ReferenceInputModeV1,
    ReferenceInputPolicyV1,
)
from app.services.openrouter_policy import build_openrouter_routing_policy
from app.services.provider_credentials import ProviderHttpTransport, UrllibProviderHttpTransport


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
            raise ValueError("provider_request_failed")
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
                    max_references=4,
                    allowed_roles=("product_reference", "scene_reference", "character_reference"),
                ),
            ),
            max_images=4,
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
