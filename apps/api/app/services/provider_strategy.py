from datetime import timedelta
from typing import Any
import weakref

from app.core.config import Settings
from app.schemas.asset_library import ProviderCapability
from app.schemas.provider_strategy import (
    ProviderCandidate,
    ProviderHealthState,
    ProviderSelectionRequest,
    ProviderSelectionResult,
)
from app.services.agent_trace import utc_now
from app.services.provider_identity_certification import (
    IdentityCertificationRegistry,
    model_id_for_provider,
)
from app.services.provider_capabilities import (
    get_provider_capability,
    list_provider_capabilities,
    provider_for_node,
)
from app.services.reference_policy import build_reference_policy


DEFAULT_PROVIDER_PRIORITIES = {
    "mock_image": 100,
    "mock_video": 100,
    "mock_bgm": 100,
    "volcengine_image": 50,
    "volcengine_video": 50,
    "volcengine_audio": 50,
}
_DEFAULT_HEALTH_BY_SETTINGS_ID: dict[
    int, tuple[weakref.ReferenceType[Settings], dict[str, ProviderHealthState]]
] = {}


class ProviderCapabilityRegistry:
    def __init__(
        self,
        capabilities: list[ProviderCapability] | None = None,
        priorities: dict[str, int] | None = None,
    ) -> None:
        self._capabilities = {
            capability.provider: capability
            for capability in (capabilities or list_provider_capabilities())
        }
        self._priorities = {**DEFAULT_PROVIDER_PRIORITIES, **(priorities or {})}

    def capability(self, provider: str, node_type: str | None = None) -> ProviderCapability:
        return self._capabilities.get(provider) or get_provider_capability(provider, node_type)

    def candidates(
        self,
        *,
        media_type: str,
        node_type: str,
        provider: str | None = None,
        allow_provider_fallback: bool = True,
    ) -> list[ProviderCapability]:
        capabilities = list(self._capabilities.values())
        if provider:
            requested = self.capability(provider, node_type)
            if not allow_provider_fallback:
                capabilities = [requested]
            else:
                capabilities = [
                    requested,
                    *[capability for capability in capabilities if capability.provider != provider],
                ]
        return [
            capability
            for capability in capabilities
            if capability.media_type == media_type
            and (not capability.node_types or node_type in capability.node_types)
        ]

    def priority(self, provider: str) -> int:
        return self._priorities.get(provider, 0)


class ProviderStrategyService:
    def __init__(
        self,
        settings: Settings,
        registry: ProviderCapabilityRegistry | None = None,
        identity_registry: IdentityCertificationRegistry | None = None,
        health_store: dict[str, ProviderHealthState] | None = None,
    ) -> None:
        self._settings = settings
        self._registry = registry or ProviderCapabilityRegistry()
        self._identity_registry = identity_registry or IdentityCertificationRegistry(
            settings=settings
        )
        self._health = health_store if health_store is not None else _default_health_store(settings)

    def select_candidates(self, request: ProviderSelectionRequest) -> ProviderSelectionResult:
        fallback_allowed = request.allow_provider_fallback
        max_attempts = self.max_attempts_for_media_type(request.media_type)
        warnings: list[dict[str, Any]] = []
        capabilities = self._registry.candidates(
            media_type=request.media_type,
            node_type=request.node_type,
            provider=request.provider,
            allow_provider_fallback=fallback_allowed,
        )
        if request.provider and not capabilities:
            requested = self._registry.capability(request.provider, request.node_type)
            if requested.media_type != request.media_type:
                warnings.append(
                    {
                        "code": "provider_media_type_mismatch",
                        "provider": request.provider,
                        "message": "Requested provider does not match requested media_type.",
                    }
                )
            elif requested.node_types and request.node_type not in requested.node_types:
                warnings.append(
                    {
                        "code": "provider_node_type_unsupported",
                        "provider": request.provider,
                        "message": "Requested provider does not support node_type.",
                    }
                )

        candidates: list[ProviderCandidate] = []
        identity_certifications: list[dict[str, Any]] = []
        for capability in capabilities:
            health = self.health_state(capability.provider)
            identity_certification = self._identity_registry.lookup(
                workflow_id=request.workflow_id,
                node_id=request.node_id,
                node_type=request.node_type,
                media_type=request.media_type,
                provider=capability.provider,
                model_id=model_id_for_provider(capability.provider, self._settings),
                reference_mode=request.reference_mode,
                asset_references=request.asset_references,
            )
            identity_payload = identity_certification.model_dump(mode="json")
            if identity_payload["required"]:
                identity_certifications.append(identity_payload)
            policy_capability = (
                capability.model_copy(update={"supports_identity_lock": True})
                if identity_certification.required
                else capability
            )
            policy = build_reference_policy(
                request.asset_references,
                node_type=request.node_type,
                provider=capability.provider,
                request_reference_mode=request.reference_mode,
                capability=policy_capability,
            )
            policy_payload = policy.model_dump(mode="json")
            if identity_certification.errors:
                warnings.extend(identity_certification.errors)
            if policy.errors:
                warnings.extend(policy.errors)
                warnings.extend(_provider_compatibility_warnings(policy.errors))
            if identity_certification.errors or policy.errors:
                continue
            warnings.extend(identity_certification.warnings)
            if health.status == "cooldown" and not (
                request.provider == capability.provider and not request.allow_provider_fallback
            ):
                warnings.append(
                    {
                        "code": "provider_cooldown",
                        "provider": capability.provider,
                        "message": "Provider is in cooldown after consecutive failures.",
                    }
                )
                continue
            candidates.append(
                ProviderCandidate(
                    provider=capability.provider,
                    media_type=capability.media_type,
                    node_types=capability.node_types,
                    capability=capability.model_dump(mode="json"),
                    priority=self._registry.priority(capability.provider),
                    health=health,
                    reference_policy=policy_payload,
                    provider_reference_plan=policy_payload.get("reference_plan") or {},
                    identity_certification=identity_payload,
                )
            )

        candidates = self._sort_candidates(candidates, request)
        limited = candidates[:max_attempts] if max_attempts > 0 else []
        selected_provider = limited[0].provider if limited else None
        reason = (
            f"Selected {selected_provider} for {request.node_type}."
            if selected_provider
            else "No provider can satisfy the selection request."
        )
        return ProviderSelectionResult(
            selected_provider=selected_provider,
            candidates=limited,
            fallback_allowed=fallback_allowed,
            selection_reason=reason,
            warnings=_dedupe_warnings(warnings),
            provider_hints=request.provider_hints,
            max_attempts=max_attempts,
            identity_certifications=identity_certifications,
        )

    def health_state(self, provider: str) -> ProviderHealthState:
        return self._health.get(provider) or ProviderHealthState(provider=provider)

    def record_failure(self, provider: str, reason_code: str) -> ProviderHealthState:
        now = utc_now()
        previous = self.health_state(provider)
        failures = previous.consecutive_failures + 1
        threshold = self._settings.provider_failure_cooldown_threshold
        cooldown_until = None
        status = "healthy"
        if failures >= threshold:
            cooldown_until = (
                now + timedelta(seconds=self._settings.provider_cooldown_seconds)
            ).isoformat()
            status = "cooldown"
        health = ProviderHealthState(
            provider=provider,
            status=status,
            consecutive_failures=failures,
            last_failure_at=now.isoformat(),
            cooldown_until=cooldown_until,
            last_error_code=reason_code,
        )
        self._health[provider] = health
        return health

    def record_success(self, provider: str) -> ProviderHealthState:
        health = ProviderHealthState(provider=provider)
        self._health[provider] = health
        return health

    def max_attempts_for_media_type(self, media_type: str) -> int:
        if media_type == "image":
            return self._settings.provider_max_attempts_image
        if media_type == "video":
            return self._settings.provider_max_attempts_video
        if media_type == "audio":
            return self._settings.provider_max_attempts_audio
        return 0

    def provider_for_node(self, node_type: str) -> str:
        return provider_for_node(node_type, media_mode=self._settings.media_mode)

    def _sort_candidates(
        self,
        candidates: list[ProviderCandidate],
        request: ProviderSelectionRequest,
    ) -> list[ProviderCandidate]:
        requested_provider = request.provider
        preferred_provider = self.provider_for_node(request.node_type)
        return sorted(
            candidates,
            key=lambda candidate: (
                0 if candidate.provider == requested_provider else 1,
                -_identity_certification_score(candidate),
                0 if candidate.provider == preferred_provider else 1,
                -_capability_score(candidate),
                -candidate.priority,
                candidate.provider,
            ),
        )


def _capability_score(candidate: ProviderCandidate) -> int:
    policy = candidate.reference_policy
    return len(policy.get("accepted_assets", [])) - len(policy.get("prompt_only_assets", []))


def _identity_certification_score(candidate: ProviderCandidate) -> int:
    certification = candidate.identity_certification
    if not certification.get("required"):
        return 0
    status = certification.get("status")
    if status == "certified":
        return 3
    if status == "experimental":
        return 2
    if status == "uncertified":
        return 1
    return 0


def _default_health_store(settings: Settings) -> dict[str, ProviderHealthState]:
    key = id(settings)
    entry = _DEFAULT_HEALTH_BY_SETTINGS_ID.get(key)
    if entry is None or entry[0]() is not settings:
        entry = (weakref.ref(settings), {})
        _DEFAULT_HEALTH_BY_SETTINGS_ID[key] = entry
    return entry[1]


def _dedupe_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for warning in warnings:
        key = (
            str(warning.get("code") or ""),
            str(warning.get("provider") or ""),
            str(warning.get("asset_id") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return deduped


def _provider_compatibility_warnings(
    policy_errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for error in policy_errors:
        if error.get("code") != "strict_reference_not_supported":
            continue
        warnings.append(
            {
                **error,
                "code": "provider_reference_type_unsupported",
                "message": "Provider does not support this reference type.",
            }
        )
    return warnings
