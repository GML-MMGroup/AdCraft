"""V2 Recommended Assets catalog and frontend-safe entity read endpoints."""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.core.config import Settings, get_settings
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import create_v2_database
from app.persistence.errors import V2PersistenceError
from app.schemas.v2_asset_library import (
    AssetLibraryEntityDetailResponseV2,
    AssetLibraryEntityListResponseV2,
    AssetLibraryEntityResponseV2,
    AssetLibraryMemberResponseV2,
    AssetEntityScopeV2,
    AssetLibraryScopeV2,
    CreateAssetLibraryEntityRequestV2,
    RecommendedCatalogStatusResponseV2,
)
from app.services.v2_asset_catalog import V2AssetCatalogError
from app.services.v2_asset_catalog_coordinator import V2AssetCatalogCoordinator
from app.services.v2_asset_library import V2AssetLibraryError, V2AssetLibraryService
from app.services.v2_storage_adapter import StorageAdapter


router = APIRouter(prefix="/asset-library", tags=["v2-asset-library"])


def get_v2_asset_library_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> V2AssetLibraryRepository:
    """Create the focused repository after router-level persistence readiness."""

    return V2AssetLibraryRepository(create_v2_database(settings.media_data_dir))


def get_v2_asset_catalog_coordinator(request: Request) -> V2AssetCatalogCoordinator:
    """Return the lifespan-owned catalog coordinator or a safe configuration error."""

    coordinator = getattr(request.app.state, "v2_asset_catalog_coordinator", None)
    if not isinstance(coordinator, V2AssetCatalogCoordinator):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "recommended_catalog_unconfigured",
                "message": "Recommended catalog is not configured.",
            },
        )
    return coordinator


def get_v2_asset_library_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> V2AssetLibraryService:
    """Create the focused My Assets service over the configured V2 database."""

    return V2AssetLibraryService(
        data_dir=settings.media_data_dir,
        repository=V2AssetLibraryRepository(create_v2_database(settings.media_data_dir)),
    )


@router.get(
    "/catalogs/recommended/status",
    response_model=RecommendedCatalogStatusResponseV2,
)
def get_recommended_catalog_status(
    coordinator: Annotated[V2AssetCatalogCoordinator, Depends(get_v2_asset_catalog_coordinator)],
) -> RecommendedCatalogStatusResponseV2:
    """Return the durable status of the configured pinned catalog."""

    try:
        return coordinator.get_recommended_status()
    except V2AssetCatalogError as error:
        raise _catalog_http_error(error) from error


@router.post(
    "/catalogs/recommended/install",
    response_model=RecommendedCatalogStatusResponseV2,
)
def start_recommended_catalog_install(
    response: Response,
    coordinator: Annotated[V2AssetCatalogCoordinator, Depends(get_v2_asset_catalog_coordinator)],
) -> RecommendedCatalogStatusResponseV2:
    """Schedule the configured catalog install without blocking the HTTP request."""

    try:
        catalog_status = coordinator.start_recommended_install()
    except V2AssetCatalogError as error:
        raise _catalog_http_error(error) from error
    response.status_code = (
        status.HTTP_200_OK if catalog_status.status == "ready" else status.HTTP_202_ACCEPTED
    )
    return catalog_status


@router.get("/entities", response_model=AssetLibraryEntityListResponseV2)
def list_asset_library_entities(
    scope: AssetLibraryScopeV2,
    repository: Annotated[V2AssetLibraryRepository, Depends(get_v2_asset_library_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
    coordinator: Annotated[
        V2AssetCatalogCoordinator | None, Depends(_optional_catalog_coordinator)
    ],
    category: Literal["characters", "scenes", "props"] | None = None,
    search: str | None = None,
    cursor: str | None = None,
    limit: int = 40,
) -> AssetLibraryEntityListResponseV2:
    """Return deterministic entities without exposing local media paths."""

    try:
        page = repository.list_entities(
            scope=cast(AssetEntityScopeV2, "user" if scope == "my" else "recommended"),
            category=category,
            search=search,
            cursor=cursor,
            limit=limit,
        )
    except V2PersistenceError as error:
        raise _query_http_error(error) from error

    catalog_status: str | None = None
    if scope == "recommended":
        if coordinator is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "recommended_catalog_unconfigured",
                    "message": "Recommended catalog is not configured.",
                },
            )
        try:
            catalog_status = coordinator.get_recommended_status().status
        except V2AssetCatalogError as error:
            raise _catalog_http_error(error) from error

    storage = StorageAdapter(settings.media_data_dir)
    try:
        entities = tuple(
            _entity_response(repository.get_entity(entity.entity_id), storage)
            for entity in page.items
        )
    except V2PersistenceError as error:
        raise _query_http_error(error) from error
    return AssetLibraryEntityListResponseV2(
        entities=entities,
        next_cursor=page.next_cursor,
        catalog_status=catalog_status,
    )


@router.get("/entities/{entity_id}", response_model=AssetLibraryEntityDetailResponseV2)
def get_asset_library_entity(
    entity_id: str,
    repository: Annotated[V2AssetLibraryRepository, Depends(get_v2_asset_library_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AssetLibraryEntityDetailResponseV2:
    """Return one entity with declared ordered immutable member versions."""

    try:
        detail = repository.get_entity(entity_id)
    except V2PersistenceError as error:
        raise _query_http_error(error) from error
    return _entity_detail_response(detail, StorageAdapter(settings.media_data_dir))


@router.post(
    "/entities",
    response_model=AssetLibraryEntityDetailResponseV2,
    status_code=status.HTTP_201_CREATED,
)
def create_asset_library_entity(
    request: CreateAssetLibraryEntityRequestV2,
    service: Annotated[V2AssetLibraryService, Depends(get_v2_asset_library_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AssetLibraryEntityDetailResponseV2:
    """Save selected generated or recommended immutable versions to My Assets."""

    try:
        detail = service.create_entity(request)
    except V2AssetLibraryError as error:
        raise _library_http_error(error) from error
    return _entity_detail_response(detail, StorageAdapter(settings.media_data_dir))


def _optional_catalog_coordinator(request: Request) -> V2AssetCatalogCoordinator | None:
    coordinator = getattr(request.app.state, "v2_asset_catalog_coordinator", None)
    return coordinator if isinstance(coordinator, V2AssetCatalogCoordinator) else None


def _entity_response(
    detail: object,
    storage: StorageAdapter,
) -> AssetLibraryEntityResponseV2:
    response = _entity_detail_response(detail, storage)
    return AssetLibraryEntityResponseV2(
        entity_id=response.entity_id,
        scope=response.scope,
        entity_type=response.entity_type,
        library_category=response.library_category,
        display_name=response.display_name,
        description=response.description,
        tags=response.tags,
        is_favorite=response.is_favorite,
        status=response.status,
        preview_member=next(
            (member for member in response.members if member.is_primary),
            response.members[0] if response.members else None,
        ),
        member_count=len(response.members),
    )


def _entity_detail_response(
    detail: object,
    storage: StorageAdapter,
) -> AssetLibraryEntityDetailResponseV2:
    from app.schemas.v2_asset_library import AssetLibraryEntityDetailV2

    typed_detail = cast(AssetLibraryEntityDetailV2, detail)
    members = tuple(_member_response(member, storage) for member in typed_detail.members)
    version_metadata = next(
        (member.version.metadata for member in typed_detail.members if member.version is not None),
        {},
    )
    return AssetLibraryEntityDetailResponseV2(
        entity_id=typed_detail.entity_id,
        scope=typed_detail.scope,
        entity_type=typed_detail.entity_type,
        library_category=typed_detail.library_category,
        display_name=typed_detail.display_name,
        description=typed_detail.description,
        tags=typed_detail.tags,
        is_favorite=typed_detail.is_favorite,
        status=typed_detail.status,
        preview_member=next((member for member in members if member.is_primary), None),
        member_count=len(members),
        members=members,
        catalog_source_url=_optional_metadata_string(version_metadata, "source_url"),
        license_id=_optional_metadata_string(version_metadata, "license_id"),
        attribution=_optional_metadata_string(version_metadata, "attribution"),
    )


def _member_response(
    member: object,
    storage: StorageAdapter,
) -> AssetLibraryMemberResponseV2:
    from app.schemas.v2_asset_library import AssetEntityMemberV2

    typed_member = cast(AssetEntityMemberV2, member)
    if typed_member.version is None:
        raise V2PersistenceError(
            "asset_library_member_version_missing",
            "Asset library member version is missing.",
            stage="asset_library_api",
        )
    version = typed_member.version
    public_url = (
        f"/media/{version.storage_key}"
        if version.status == "ready" and storage.content_exists(version.storage_key, version.sha256)
        else None
    )
    return AssetLibraryMemberResponseV2(
        member_id=typed_member.member_id,
        semantic_type=typed_member.semantic_type,
        asset_id=typed_member.asset_id,
        version_id=typed_member.version_id,
        mime_type=version.mime_type,
        width=version.width,
        height=version.height,
        duration_seconds=version.duration_seconds,
        public_url=public_url,
        is_primary=typed_member.is_primary,
        is_default_reference=typed_member.is_default_reference,
        sort_order=typed_member.sort_order,
    )


def _optional_metadata_string(metadata: object, key: str) -> str | None:
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _catalog_http_error(error: V2AssetCatalogError) -> HTTPException:
    status_code = (
        status.HTTP_422_UNPROCESSABLE_ENTITY
        if error.code == "recommended_catalog_manifest_invalid"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return HTTPException(
        status_code=status_code, detail={"code": error.code, "message": error.message}
    )


def _query_http_error(error: V2PersistenceError) -> HTTPException:
    if error.code == "asset_library_entity_not_found":
        status_code = status.HTTP_404_NOT_FOUND
        code = "asset_library_entity_not_found"
    elif error.code == "asset_library_cursor_invalid":
        status_code = status.HTTP_400_BAD_REQUEST
        code = "asset_library_cursor_invalid"
    elif error.code == "asset_library_page_invalid":
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        code = "asset_library_query_invalid"
    else:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        code = error.code
    return HTTPException(status_code=status_code, detail={"code": code, "message": str(error)})


def _library_http_error(error: V2AssetLibraryError) -> HTTPException:
    if error.code in {"asset_version_not_found", "asset_library_entity_not_found"}:
        status_code = status.HTTP_404_NOT_FOUND
    elif error.code in {"asset_content_unavailable", "asset_library_source_invalid"}:
        status_code = status.HTTP_409_CONFLICT
    else:
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.message},
    )
