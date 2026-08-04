from pathlib import Path
from typing import Any

from app.schemas.workflow_v2 import (
    WorkflowAssetRelationTypeV2,
    WorkflowAssetRelationV2,
    WorkflowAssetVersionV2,
    WorkflowMediaTypeV2,
)
from app.services.agent_trace import utc_now
from app.services.v2_asset_store import V2AssetStoreService

from tests.helpers.media_factories import media_extension, write_dummy_media_file


def make_v2_asset_version(
    data_dir: Path,
    *,
    workflow_id: str,
    asset_id: str,
    version_id: str,
    media_type: WorkflowMediaTypeV2 = "image",
    node_id: str | None = None,
    item_id: str | None = None,
    slot_id: str | None = None,
    semantic_type: str | None = None,
    source_type: str = "generated",
    display_name: str | None = None,
    prompt_summary: str | None = None,
    user_summary_prompt: str | None = None,
    provider_prompt: str | None = None,
    file_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> WorkflowAssetVersionV2:
    relative_file_path = file_path or (
        f"assets/generated/{asset_id}/{version_id}{media_extension(media_type)}"
    )
    write_dummy_media_file(data_dir, relative_file_path)
    record_metadata: dict[str, Any] = {
        "display_name": display_name,
        "prompt_summary_source": "system",
        "provider_prompt": provider_prompt or f"Provider prompt for {asset_id}.",
        "provider": "test-provider",
        **dict(metadata or {}),
    }
    if user_summary_prompt:
        record_metadata["user_summary_prompt"] = user_summary_prompt
        record_metadata["prompt_summary_source"] = "user"
    record = WorkflowAssetVersionV2(
        asset_id=asset_id,
        version_id=version_id,
        media_type=media_type,
        source_type=source_type,  # type: ignore[arg-type]
        file_path=relative_file_path,
        public_url=f"/media/{relative_file_path}",
        workflow_id=workflow_id,
        node_id=node_id,
        item_id=item_id,
        slot_id=slot_id,
        semantic_type=semantic_type,
        prompt_snapshot={"summary_prompt": prompt_summary or f"Summary for {asset_id}."},
        provider_payload_snapshot={
            "provider_prompt": provider_prompt or f"Provider prompt for {asset_id}.",
            "provider": "test-provider",
        },
        created_at=utc_now().isoformat(),
        created_by="test-factory",
        metadata=record_metadata,
    )
    return V2AssetStoreService(data_dir).save_asset_version(record)


def make_v2_asset_relation(
    data_dir: Path,
    *,
    relation_type: WorkflowAssetRelationTypeV2,
    source_asset_id: str,
    workflow_id: str,
    node_id: str | None = None,
    item_id: str | None = None,
    slot_id: str | None = None,
    version_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> WorkflowAssetRelationV2:
    relation_metadata = dict(metadata or {})
    if version_id:
        relation_metadata.setdefault("version_id", version_id)
    return V2AssetStoreService(data_dir).create_relation(
        relation_type=relation_type,
        source_asset_id=source_asset_id,
        target_workflow_id=workflow_id,
        target_node_id=node_id,
        target_item_id=item_id,
        target_slot_id=slot_id,
        metadata=relation_metadata,
    )
