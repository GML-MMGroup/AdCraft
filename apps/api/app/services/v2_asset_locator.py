from pathlib import Path

from app.schemas.workflow_v2 import V2AssetLocatorResponse, WorkflowV2
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_workflow_assets import _display_name, _normalize_semantic_type
from app.services.v2_workflow_authoring import create_workflow_authoring_runtime


class V2AssetLocatorError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2AssetLocatorResolver:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._authoring_runtime = create_workflow_authoring_runtime(data_dir)
        self._asset_store = V2AssetStoreService(data_dir)

    def resolve(self, workflow_id: str, locator: str) -> V2AssetLocatorResponse:
        workflow = self._authoring_runtime.read_model.assemble(workflow_id)
        kind, value = _parse_locator(locator)
        if kind == "slot":
            slot = _find_slot(workflow, value)
            if slot is None:
                raise V2AssetLocatorError("slot_not_found")
            item = _find_item(workflow, slot.item_id)
            owner_type = _owner_type_for_node(slot.node_id)
            return V2AssetLocatorResponse(
                locator=locator,
                target_type="slot",
                slot_id=slot.slot_id,
                node_id=slot.node_id,
                display_name=_display_name_for_slot(slot.slot_type),
                owner_type=owner_type,
                owner_node_id=slot.node_id,
                owner_item_id=slot.item_id,
                owner_slot_id=slot.slot_id,
                owner_display_name=item.get("display_name") if item else None,
                resolved_owner={
                    "node_id": slot.node_id,
                    "item_id": slot.item_id,
                    "slot_id": slot.slot_id,
                    "slot_type": slot.slot_type,
                },
            )
        if kind == "free_node":
            node = next((node for node in workflow.nodes if node.node_id == value), None)
            if node is None or node.node_type != "free-generation":
                raise V2AssetLocatorError("free_node_not_found")
            return V2AssetLocatorResponse(
                locator=locator,
                target_type="free_node",
                node_id=node.node_id,
                display_name=node.title,
                owner_type="free",
                owner_node_id=node.node_id,
                owner_item_id=None,
                owner_slot_id=None,
                owner_display_name=node.title,
                resolved_owner=None,
            )
        asset_id, version_id = _parse_asset_locator_value(value)
        relation = _owner_relation(self._asset_store, workflow_id, asset_id)
        resolved_version_id = (
            version_id or str(relation.metadata.get("version_id") or "") if relation else version_id
        )
        if not resolved_version_id:
            resolved_version_id = _first_version_id(self._data_dir, asset_id)
        record = (
            self._asset_store.load_asset_version(asset_id, resolved_version_id)
            if resolved_version_id
            else None
        )
        if record is None:
            raise V2AssetLocatorError("asset_version_not_found")
        semantic_type = _normalize_semantic_type(record.semantic_type or "", record.media_type)
        owner = _resolved_owner(workflow, relation, semantic_type)
        return V2AssetLocatorResponse(
            locator=locator,
            target_type="asset",
            asset_id=asset_id,
            version_id=resolved_version_id,
            display_name=_display_name(record, semantic_type),
            owner_type=owner["owner_type"],
            owner_node_id=owner["owner_node_id"],
            owner_item_id=owner["owner_item_id"],
            owner_slot_id=owner["owner_slot_id"],
            owner_display_name=owner["owner_display_name"],
            resolved_owner=owner["resolved_owner"],
        )


def _parse_locator(locator: str) -> tuple[str, str]:
    if ":" not in locator:
        raise V2AssetLocatorError("invalid_locator")
    kind, value = locator.split(":", 1)
    if kind not in {"asset", "slot", "free_node"} or not value:
        raise V2AssetLocatorError("invalid_locator")
    return kind, value


def _parse_asset_locator_value(value: str) -> tuple[str, str | None]:
    if "@" not in value:
        return value, None
    asset_id, version_id = value.split("@", 1)
    if not asset_id or not version_id:
        raise V2AssetLocatorError("invalid_locator")
    return asset_id, version_id


def _owner_relation(asset_store: V2AssetStoreService, workflow_id: str, asset_id: str):
    for relation_type in (
        "selected_for_slot",
        "working_version_for_slot",
        "history_version_for_slot",
        "absorbed_into",
        "reference_for_slot",
        "reference_for_item",
        "available_for_composition",
        "selected_for_timeline",
    ):
        relations = asset_store.list_relations(
            target_workflow_id=workflow_id,
            source_asset_id=asset_id,
            relation_type=relation_type,  # type: ignore[arg-type]
        )
        if relations:
            return relations[0]
    return None


def _first_version_id(data_dir: Path, asset_id: str) -> str | None:
    root = data_dir / "assets" / "metadata" / asset_id
    if not root.exists():
        return None
    first = next(iter(sorted(root.glob("*.json"))), None)
    return first.stem if first else None


def _find_slot(workflow: WorkflowV2, slot_id: str):
    return next(
        (
            slot
            for node in workflow.nodes
            for item in node.items
            for slot in item.slots
            if slot.slot_id == slot_id
        ),
        None,
    )


def _find_item(workflow: WorkflowV2, item_id: str | None) -> dict | None:
    if not item_id:
        return None
    for node in workflow.nodes:
        for item in node.items:
            if item.item_id == item_id:
                return item.model_dump(mode="json")
    return None


def _owner_type_for_node(node_id: str | None) -> str | None:
    return {
        "product-generation": "product",
        "character-generation": "character",
        "scene-generation": "scene",
        "storyboard": "storyboard",
        "bgm": "bgm",
        "final-composition": "final_composition",
    }.get(node_id or "")


def _resolved_owner(workflow: WorkflowV2, relation, semantic_type: str) -> dict[str, object | None]:
    if relation is None:
        return {
            "owner_type": None,
            "owner_node_id": None,
            "owner_item_id": None,
            "owner_slot_id": None,
            "owner_display_name": None,
            "resolved_owner": None,
        }
    item = _find_item(workflow, relation.target_item_id)
    slot = _find_slot(workflow, relation.target_slot_id) if relation.target_slot_id else None
    slot_type = slot.slot_type if slot else relation.metadata.get("slot_type")
    owner_type = _owner_type_for_node(relation.target_node_id)
    if owner_type is None and isinstance(semantic_type, str):
        owner_type = semantic_type.split("_", 1)[0] if "_" in semantic_type else None
    return {
        "owner_type": owner_type,
        "owner_node_id": relation.target_node_id,
        "owner_item_id": relation.target_item_id,
        "owner_slot_id": relation.target_slot_id,
        "owner_display_name": item.get("display_name") if item else None,
        "resolved_owner": {
            "node_id": relation.target_node_id,
            "item_id": relation.target_item_id,
            "slot_id": relation.target_slot_id,
            "slot_type": slot_type,
        },
    }


def _display_name_for_slot(slot_type: str) -> str:
    semantic_type = _normalize_semantic_type(slot_type, None)
    return {
        "product_main": "Product main image",
        "product_multi_view": "Product multi-view image",
        "character_main": "Character main image",
        "character_three_view": "Character three-view image",
        "scene_main": "Scene main image",
        "scene_multi_view": "Scene multi-view image",
        "shot_cell_image": "Storyboard cell image",
        "shot_video_segment": "Storyboard video segment",
        "bgm": "Background music",
        "final_video": "Final video",
        "free_image": "Free image",
    }.get(semantic_type, "Workflow slot")
