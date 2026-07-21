from typing import Any

from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.provider_identity_certification import (
    IdentityCertificationLookupRequest,
    IdentityCertificationRecord,
    IdentityCertificationResult,
)


IDENTITY_REFERENCE_ROLES = {"character_reference", "subject_reference"}
IDENTITY_REFERENCE_SEMANTIC_TYPES = {
    "character_face_id",
    "character_main",
    "character_three_view",
}


class IdentityCertificationRegistryError(ValueError):
    """Raised when identity certification registry data is invalid."""


def default_identity_certification_records() -> list[IdentityCertificationRecord]:
    records: list[IdentityCertificationRecord] = []
    for node_type in ("character-generation", "storyboard"):
        for semantic_type in IDENTITY_REFERENCE_SEMANTIC_TYPES:
            records.append(
                IdentityCertificationRecord(
                    certification_id=f"cert_mock_image_{node_type}_{semantic_type}",
                    provider="mock_image",
                    model_id="mock-image",
                    media_type="image",
                    node_type=node_type,
                    reference_semantic_type=semantic_type,
                    reference_role="character_reference",
                    status="certified",
                    certification_level="strict_identity",
                    certified_at="2026-06-25T00:00:00Z",
                    test_report_id="identity_cert_report_mock_image",
                )
            )
    for semantic_type in ("character_main", "character_three_view"):
        records.append(
            IdentityCertificationRecord(
                certification_id=f"cert_mock_video_storyboard-video-generation_{semantic_type}",
                provider="mock_video",
                model_id="mock-video",
                media_type="video",
                node_type="storyboard-video-generation",
                reference_semantic_type=semantic_type,
                reference_role="character_reference",
                status="certified",
                certification_level="strict_identity",
                certified_at="2026-06-25T00:00:00Z",
                test_report_id="identity_cert_report_mock_video",
            )
        )
    return records


class IdentityCertificationRegistry:
    def __init__(
        self,
        records: list[IdentityCertificationRecord] | None = None,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings
        self._records = (
            list(records) if records is not None else default_identity_certification_records()
        )
        self._records_by_key = {
            _record_key(
                record.provider,
                record.model_id,
                record.media_type,
                record.node_type,
                record.reference_semantic_type,
            ): record
            for record in self._records
        }

    @classmethod
    def from_raw_records(
        cls,
        records: list[dict[str, Any]],
        *,
        settings: Settings | None = None,
    ) -> "IdentityCertificationRegistry":
        try:
            parsed = [IdentityCertificationRecord.model_validate(record) for record in records]
        except ValidationError as exc:
            raise IdentityCertificationRegistryError(
                f"identity_certification_registry_invalid: {exc}"
            ) from exc
        return cls(records=parsed, settings=settings)

    def records(
        self,
        *,
        provider: str | None = None,
        model_id: str | None = None,
        media_type: str | None = None,
        node_type: str | None = None,
        reference_semantic_type: str | None = None,
        status: str | None = None,
    ) -> list[IdentityCertificationRecord]:
        return [
            record
            for record in self._records
            if (provider is None or record.provider == provider)
            and (model_id is None or record.model_id == model_id)
            and (media_type is None or record.media_type == media_type)
            and (node_type is None or record.node_type == node_type)
            and (
                reference_semantic_type is None
                or record.reference_semantic_type == reference_semantic_type
            )
            and (status is None or record.status == status)
        ]

    def lookup(
        self,
        *,
        workflow_id: str,
        node_id: str,
        node_type: str,
        media_type: str,
        provider: str,
        model_id: str,
        reference_mode: str,
        asset_references: list[dict[str, Any]],
    ) -> IdentityCertificationResult:
        return self.lookup_request(
            IdentityCertificationLookupRequest(
                workflow_id=workflow_id,
                node_id=node_id,
                node_type=node_type,
                media_type=media_type,
                provider=provider,
                model_id=model_id,
                reference_mode="strict" if reference_mode == "strict" else "best_effort",
                asset_references=asset_references,
            )
        )

    def lookup_request(
        self,
        request: IdentityCertificationLookupRequest,
    ) -> IdentityCertificationResult:
        requirements = _identity_requirements(request.asset_references)
        if not requirements:
            return IdentityCertificationResult(
                required=False,
                mode=request.reference_mode,
                status="not_required",
                provider=request.provider,
                model_id=request.model_id,
                media_type=request.media_type,
                node_type=request.node_type,
            )

        warnings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        certification_ids: list[str] = []
        statuses: list[str] = []
        lookup_keys: list[dict[str, Any]] = []
        reference_ids = sorted(
            {
                reference_id
                for item in requirements
                for reference_id in item.get("reference_ids", [])
                if reference_id
            }
        )
        semantic_types = sorted({str(item["reference_semantic_type"]) for item in requirements})

        for semantic_type in semantic_types:
            key_payload = {
                "provider": request.provider,
                "model_id": request.model_id,
                "media_type": request.media_type,
                "node_type": request.node_type,
                "reference_semantic_type": semantic_type,
            }
            lookup_keys.append(key_payload)
            record = self._records_by_key.get(
                _record_key(
                    request.provider,
                    request.model_id,
                    request.media_type,
                    request.node_type,
                    semantic_type,
                )
            )
            status = record.status if record else "uncertified"
            statuses.append(status)
            if record:
                certification_ids.append(record.certification_id)

            if status == "certified":
                continue
            issue = _certification_issue(
                "identity_certification_revoked"
                if status == "revoked"
                else "identity_certification_required",
                request,
                semantic_type,
                status=status,
            )
            if request.reference_mode == "strict" or status == "revoked":
                errors.append(issue)
            else:
                warnings.append(
                    _certification_issue(
                        "identity_certification_warning",
                        request,
                        semantic_type,
                        status=status,
                    )
                )

        return IdentityCertificationResult(
            required=True,
            mode=request.reference_mode,
            status=_result_status(statuses),
            provider=request.provider,
            model_id=request.model_id,
            media_type=request.media_type,
            node_type=request.node_type,
            reference_semantic_types=semantic_types,
            reference_ids=reference_ids,
            certification_lookup_keys=lookup_keys,
            certification_ids=certification_ids,
            warnings=_dedupe_issues(warnings),
            errors=_dedupe_issues(errors),
        )


def model_id_for_provider(provider: str, settings: Settings) -> str:
    if provider == "mock_image":
        return "mock-image"
    if provider == "mock_video":
        return "mock-video"
    if provider == "mock_bgm":
        return "mock-bgm"
    if provider == "volcengine_image":
        return settings.image_generation_model
    if provider == "volcengine_video":
        return settings.video_generation_model
    if provider == "volcengine_audio":
        return settings.bgm_model or "configured-bgm"
    return provider


def _identity_requirements(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for reference in references:
        if not isinstance(reference, dict):
            continue
        role = str(reference.get("role") or "")
        if role not in IDENTITY_REFERENCE_ROLES:
            continue
        if not bool(reference.get("lock_identity", False)):
            continue
        reference_ids: list[str] = []
        semantic_types: set[str] = set()
        for asset in reference.get("assets", []):
            if not isinstance(asset, dict):
                continue
            semantic_type = str(asset.get("semantic_type") or "")
            if semantic_type not in IDENTITY_REFERENCE_SEMANTIC_TYPES:
                continue
            semantic_types.add(semantic_type)
            asset_id = str(asset.get("asset_id") or "")
            if asset_id:
                reference_ids.append(asset_id)
        for semantic_type in sorted(semantic_types):
            requirements.append(
                {
                    "reference_semantic_type": semantic_type,
                    "reference_ids": reference_ids,
                    "role": role,
                }
            )
    return requirements


def _certification_issue(
    code: str,
    request: IdentityCertificationLookupRequest,
    semantic_type: str,
    *,
    status: str,
) -> dict[str, Any]:
    if code == "identity_certification_warning":
        message = (
            "This provider/model is not certified for strict identity lock; "
            "identity will be handled as best effort."
        )
    elif code == "identity_certification_revoked":
        message = (
            "The provider/model identity certification for this reference type has been revoked."
        )
    else:
        message = (
            "Strict identity lock requires a certified provider/model for this reference type."
        )
    return {
        "code": code,
        "message": message,
        "provider": request.provider,
        "model_id": request.model_id,
        "node_type": request.node_type,
        "reference_semantic_type": semantic_type,
        "certification_status": status,
    }


def _record_key(
    provider: str,
    model_id: str,
    media_type: str,
    node_type: str,
    semantic_type: str,
) -> tuple[str, str, str, str, str]:
    return (provider, model_id, media_type, node_type, semantic_type)


def _result_status(statuses: list[str]) -> str:
    for status in ("revoked", "uncertified", "experimental"):
        if status in statuses:
            return status
    return "certified"


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for issue in issues:
        key = (
            str(issue.get("code") or ""),
            str(issue.get("provider") or ""),
            str(issue.get("model_id") or ""),
            str(issue.get("reference_semantic_type") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped
