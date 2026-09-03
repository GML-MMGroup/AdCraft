"""Provider-specific payload projections behind the canonical adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Protocol

from app.schemas.provider_models import (
    ProviderAdapterProfileV1,
    ReferenceInputModeV1,
    ReferenceInputPolicyV1,
)


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
        response = transport.submit(request.payload)
        task_id = _required_string(response, "task_id", "provider_task_id")
        return ProviderSubmission(
            provider_task_id=task_id,
            request_fingerprint=str(request.audit["request_fingerprint"]),
            raw=dict(response),
        )

    def poll(self, submission: ProviderSubmission) -> ProviderStatus:
        transport = self._require_transport()
        response = transport.poll(submission.provider_task_id)
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
        response = transport.download(value)
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
        return ()

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


class OpenAIImageAdapter(ProviderNativeAdapter):
    """Project the canonical image request into the OpenAI Images API shape."""

    profile = ProviderAdapterProfileV1(
        model_ref="openai:gpt-image-2",
        adapter_id="openai-image-native",
        transport_kind="openai_images_native",
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
        parameter_schema_id="openai-gpt-image-2-v1",
        result_protocol="image_data",
        supports_remote_task_lookup=False,
        supports_provider_idempotency=False,
        release_tier="optional",
        conformance_status="unverified",
        adapter_revision="openai-image-native-v1",
        capability_revision="openai-gpt-image-2-v1",
    )

    def _compile_payload(self, request: CanonicalProviderRequest) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "model": request.provider_model_id,
            "prompt": request.prompt,
        }
        payload.update(request.parameters)
        if request.references:
            payload["image"] = [
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
        allowed = {"size", "quality", "background", "output_format", "moderation"}
        unknown = set(parameters).difference(allowed)
        return ("model_parameter_incompatible",) if unknown else ()

    def submit(self, request: NativeProviderRequest) -> ProviderSubmission:
        transport = self._require_transport()
        response = dict(transport.submit(request.payload))
        if not isinstance(response.get("data"), list):
            raise ValueError("provider_response_contract_invalid")
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
        if not isinstance(data, list) or not data or not isinstance(data[0], Mapping):
            raise ValueError("provider_response_contract_invalid")
        item = data[0]
        value = _required_string(item, "b64_json", "url")
        return ProviderArtifact(
            media_type="image",
            value=value,
            provider_task_id=status.provider_task_id,
            request_fingerprint=status.request_fingerprint,
            raw={"result_keys": tuple(sorted(item))},
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
        allowed = {"duration", "resolution", "aspect_ratio", "generate_audio"}
        unknown = set(parameters).difference(allowed)
        if unknown:
            return ("model_parameter_incompatible",)
        duration = parameters.get("duration")
        if duration is not None and duration not in {6, 10}:
            return ("model_parameter_incompatible",)
        resolution = parameters.get("resolution")
        if resolution is not None and resolution not in {"768P", "1080P"}:
            return ("model_parameter_incompatible",)
        return ()

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


def _required_string(source: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise ValueError("provider_response_contract_invalid")


def _fingerprint(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
