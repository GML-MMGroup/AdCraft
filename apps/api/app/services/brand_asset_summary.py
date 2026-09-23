"""Metadata-only review of explicit project-owned, target-scoped asset Bindings."""

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.persistence.models import (
    AgentCanvasBindingRow,
    AgentCanvasWorkflowRow,
    AssetRow,
    AssetVersionRow,
    BrandRow,
)
from app.schemas.brand_professional_mode import BrandAssetReferenceV1


def brand_asset_references(
    connection: Connection, brand_id: str
) -> tuple[BrandAssetReferenceV1, ...]:
    bindings = AgentCanvasBindingRow.__table__
    workflows = AgentCanvasWorkflowRow.__table__
    source_workflows = workflows.alias("asset_source_workflows")
    assets = AssetRow.__table__
    versions = AssetVersionRow.__table__
    brands = BrandRow.__table__
    rows = connection.execute(
        select(
            bindings.c.binding_id,
            bindings.c.workflow_id,
            bindings.c.target_node_id,
            assets.c.asset_id,
            versions.c.version_id,
            assets.c.display_name,
            bindings.c.input_role,
        )
        .select_from(bindings)
        .join(workflows, workflows.c.workflow_id == bindings.c.workflow_id)
        .join(brands, brands.c.project_id == workflows.c.project_id)
        .join(assets, assets.c.asset_id == bindings.c.source_asset_id)
        .join(
            versions,
            (versions.c.version_id == bindings.c.source_asset_version_id)
            & (versions.c.asset_id == assets.c.asset_id),
        )
        .join(source_workflows, source_workflows.c.workflow_id == versions.c.source_workflow_id)
        .where(
            brands.c.brand_id == brand_id,
            bindings.c.enabled.is_(True),
            bindings.c.source_kind == "image_asset",
            assets.c.status == "active",
            versions.c.status == "ready",
            source_workflows.c.project_id == brands.c.project_id,
        )
        .order_by(
            bindings.c.workflow_id,
            bindings.c.target_node_id,
            bindings.c.order_index,
            bindings.c.binding_id,
        )
    ).mappings()
    return tuple(BrandAssetReferenceV1.model_validate(dict(row)) for row in rows)
