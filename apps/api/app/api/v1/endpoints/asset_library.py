from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_asset_library_service
from app.schemas.asset_library import (
    AssetLibraryCreateEntityRequest,
    AssetLibraryCreateEntityResponse,
    AssetLibraryEntityDetailResponse,
    AssetLibraryListResponse,
    AssetLibraryPatchEntityRequest,
)
from app.services.asset_library import AssetLibraryError, AssetLibraryService

router = APIRouter(prefix="/asset-library", tags=["asset-library"])


@router.post("/entities", response_model=AssetLibraryCreateEntityResponse)
def create_asset_library_entity(
    request: AssetLibraryCreateEntityRequest,
    service: Annotated[AssetLibraryService, Depends(get_asset_library_service)],
) -> AssetLibraryCreateEntityResponse:
    try:
        return service.create_entity(request)
    except AssetLibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.get("/entities", response_model=AssetLibraryListResponse)
def list_asset_library_entities(
    service: Annotated[AssetLibraryService, Depends(get_asset_library_service)],
    entity_type: str | None = Query(default=None),
    semantic_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    q: str | None = Query(default=None),
    source_workflow_id: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
) -> AssetLibraryListResponse:
    try:
        return service.list_entities(
            entity_type=entity_type,
            semantic_type=semantic_type,
            tag=tag,
            q=q,
            source_workflow_id=source_workflow_id,
            include_archived=include_archived,
        )
    except AssetLibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.get("/entities/{entity_id}", response_model=AssetLibraryEntityDetailResponse)
def get_asset_library_entity(
    entity_id: str,
    service: Annotated[AssetLibraryService, Depends(get_asset_library_service)],
    include_archived: bool = Query(default=True),
) -> AssetLibraryEntityDetailResponse:
    try:
        return service.get_entity(entity_id, include_archived=include_archived)
    except AssetLibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.patch("/entities/{entity_id}", response_model=AssetLibraryEntityDetailResponse)
def patch_asset_library_entity(
    entity_id: str,
    request: AssetLibraryPatchEntityRequest,
    service: Annotated[AssetLibraryService, Depends(get_asset_library_service)],
) -> AssetLibraryEntityDetailResponse:
    try:
        return service.patch_entity(entity_id, request)
    except AssetLibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
