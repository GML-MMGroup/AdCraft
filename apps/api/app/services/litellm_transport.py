"""Transport-only boundary for generated local LiteLLM projections."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from typing import Protocol

from app.schemas.provider_models import (
    LiteLLMGatewayProjectionV1,
    LiteLLMRouteV1,
    ProviderAdapterProfileV1,
)


class LiteLLMGateway(Protocol):
    """Small injected interface used by deterministic tests and the runtime."""

    def health(self) -> Mapping[str, object]: ...

    def complete(self, payload: dict[str, object]) -> Mapping[str, object]: ...


class LiteLLMRequestV1:
    """Frozen request identity handed to the transport exactly once."""

    __slots__ = ("profile", "operation", "contract_digest", "payload", "request_fingerprint")

    def __init__(
        self,
        *,
        profile: ProviderAdapterProfileV1,
        operation: str,
        contract_digest: str,
        payload: Mapping[str, object],
        request_fingerprint: str,
    ) -> None:
        self.profile = profile
        self.operation = operation
        self.contract_digest = contract_digest
        self.payload = dict(payload)
        self.request_fingerprint = request_fingerprint


def build_litellm_gateway_projection(
    *,
    gateway_id: str,
    endpoint: str,
    routes: tuple[LiteLLMRouteV1, ...],
) -> LiteLLMGatewayProjectionV1:
    """Build the deterministic secret-free gateway projection and digest."""

    route_keys = {(route.model_alias, route.operation) for route in routes}
    if len(route_keys) != len(routes):
        raise ValueError("provider_gateway_projection_conflict")
    body = {
        "schema_version": "1",
        "gateway_id": gateway_id,
        "endpoint": endpoint,
        "routes": [route.model_dump(mode="json") for route in routes],
    }
    digest = f"sha256:{sha256(_canonical_bytes(body)).hexdigest()}"
    return LiteLLMGatewayProjectionV1(
        **body,
        projection_digest=digest,
    )


class LiteLLMTransportAdapter:
    """Validate a frozen route and relay one bounded request to LiteLLM."""

    def __init__(
        self,
        gateway: LiteLLMGateway,
        *,
        projection: LiteLLMGatewayProjectionV1,
        maximum_payload_bytes: int = 1_048_576,
    ) -> None:
        self._gateway = gateway
        self._projection = projection
        self._maximum_payload_bytes = maximum_payload_bytes

    def prepare(
        self,
        profile: ProviderAdapterProfileV1,
        *,
        operation: str,
        contract_digest: str,
        payload: Mapping[str, object],
    ) -> LiteLLMRequestV1:
        if profile.transport_kind not in {"litellm_chat", "litellm_openai_image"}:
            raise ValueError("provider_transport_unsupported")
        gateway_profile = profile.gateway_profile
        if gateway_profile is None or profile.conformance_status != "certified":
            raise ValueError("agent_model_incompatible")
        try:
            health = dict(self._gateway.health())
        except Exception as error:
            raise ValueError("provider_gateway_unavailable") from error
        if health.get("status") != "ready":
            raise ValueError("provider_gateway_unavailable")
        route = next(
            (
                item
                for item in self._projection.routes
                if item.model_ref == profile.model_ref and item.operation == operation
            ),
            None,
        )
        if route is None or not _route_matches(
            profile,
            route,
            contract_digest,
            projection=self._projection,
        ):
            raise ValueError("provider_gateway_config_stale")
        aliases = health.get("aliases")
        if (
            health.get("projection_digest") != self._projection.projection_digest
            or not isinstance(aliases, Mapping)
            or aliases.get(gateway_profile.model_alias) != profile.model_ref
        ):
            raise ValueError("provider_gateway_config_stale")
        request_payload = dict(payload)
        supplied_alias = request_payload.pop("model", gateway_profile.model_alias)
        if supplied_alias != gateway_profile.model_alias:
            raise ValueError("provider_gateway_config_stale")
        if _contains_forbidden_transport(request_payload):
            raise ValueError("provider_gateway_request_invalid")
        request_payload["model"] = gateway_profile.model_alias
        payload_bytes = _canonical_bytes(request_payload)
        if len(payload_bytes) > self._maximum_payload_bytes:
            raise ValueError("provider_gateway_request_too_large")
        fingerprint = f"sha256:{sha256(payload_bytes).hexdigest()}"
        return LiteLLMRequestV1(
            profile=profile,
            operation=operation,
            contract_digest=contract_digest,
            payload=request_payload,
            request_fingerprint=fingerprint,
        )

    def invoke(self, request: LiteLLMRequestV1) -> Mapping[str, object]:
        """Send one already-authorized request; retry policy stays above this layer."""

        try:
            response = self._gateway.complete(dict(request.payload))
        except Exception as error:
            raise ValueError("provider_gateway_unavailable") from error
        if not isinstance(response, Mapping) or _contains_forbidden_transport(response):
            raise ValueError("provider_response_contract_invalid")
        if len(_canonical_bytes(response)) > self._maximum_payload_bytes:
            raise ValueError("provider_response_contract_invalid")
        return dict(response)


def _route_matches(
    profile: ProviderAdapterProfileV1,
    route: LiteLLMRouteV1,
    contract_digest: str,
    *,
    projection: LiteLLMGatewayProjectionV1,
) -> bool:
    return (
        route.model_alias == profile.gateway_profile.model_alias
        and route.provider_model_id == profile.model_ref.split(":", 1)[-1]
        and route.contract_digest == contract_digest
        and profile.gateway_profile.gateway_id == projection.gateway_id
        and profile.gateway_profile.endpoint == projection.endpoint
        and profile.gateway_profile.projection_digest == projection.projection_digest
    )


def _contains_forbidden_transport(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            key.lower() in {"api_key", "authorization", "credential", "provider_model_id"}
            or _contains_forbidden_transport(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_transport(item) for item in value)
    return False


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
