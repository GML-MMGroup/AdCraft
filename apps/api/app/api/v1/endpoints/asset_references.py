from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_asset_reference_suggestion_service
from app.schemas.asset_references import AssetReferenceSuggestResponse
from app.services.asset_reference_suggestions import AssetReferenceSuggestionService


router = APIRouter(prefix="/asset-references", tags=["asset-references"])


@router.get("/suggest", response_model=AssetReferenceSuggestResponse)
def suggest_asset_references(
    service: Annotated[
        AssetReferenceSuggestionService,
        Depends(get_asset_reference_suggestion_service),
    ],
    q: str | None = Query(default=None),
    types: str | None = Query(default=None),
    workflow_id: str | None = Query(default=None),
    node_id: str | None = Query(default=None),
    include_canvas_assets: bool = Query(default=True),
    include_library_assets: bool = Query(default=True),
    limit: int = Query(default=30, ge=1, le=100),
) -> AssetReferenceSuggestResponse:
    return service.suggest(
        q=q,
        types=types,
        workflow_id=workflow_id,
        node_id=node_id,
        include_canvas_assets=include_canvas_assets,
        include_library_assets=include_library_assets,
        limit=limit,
    )
