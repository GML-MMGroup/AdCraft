from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.schemas.workflow_v2 import (
    WorkflowEdgeV2,
    WorkflowItemV2,
    WorkflowMediaTypeV2,
    WorkflowNodeV2,
    WorkflowRuntimeV2,
    WorkflowSlotV2,
    WorkflowV2,
)
from app.schemas.workflow_v2_planning import (
    V2ScriptCharacter,
    V2ScriptLocation,
    V2ScriptScene,
)
from app.schemas.workflow_v2_screenplay import V2ScriptPlanV2, V2ScriptShotV2
from app.schemas.workflow_v2_authoring import WorkflowRevisionChangeSource
from app.services.agent_trace import utc_now
from app.services.v2_screenplay_renderer import V2ScreenplayRenderer
from app.services.v2_script_versions import V2ScriptVersionService
from app.services.v2_workflow_authoring import create_workflow_authoring_runtime
from app.services.v2_workflow_planner import build_slot
from app.services.v2_workflow_store import V2WorkflowStore

from tests.helpers.asset_factories import make_v2_asset_relation, make_v2_asset_version


def make_v2_workflow(
    data_dir: Path,
    *,
    workflow_id: str = "adwf_v2_test",
    audio_mode: str = "bgm_only",
    save: bool = True,
) -> WorkflowV2:
    now = utc_now().isoformat()
    script_plan = _canonical_script_plan(workflow_id)
    workflow = WorkflowV2(
        workflow_id=workflow_id,
        name="Lemon Tea",
        description="Compact test workflow.",
        prompt="Create a summer launch ad for Lemon Tea.",
        duration_seconds=30,
        aspect_ratio="16:9",
        audio_mode=audio_mode,  # type: ignore[arg-type]
        nodes=[
            _script_node(workflow_id),
            _media_node(
                workflow_id,
                node_id="product-generation",
                title="Product Generation",
                item=_item_with_slots(
                    node_id="product-generation",
                    item_id="product-1",
                    item_type="product",
                    display_name="Lemon Tea",
                    slots=[
                        _slot(
                            "product-generation",
                            "product-1",
                            "product_main_image",
                            "image",
                        ),
                        _slot(
                            "product-generation",
                            "product-1",
                            "product_multi_view_grid",
                            "image",
                            status="blocked",
                            dependency_slot_ids=["product-1:product_main_image"],
                        ),
                    ],
                ),
            ),
            _media_node(
                workflow_id,
                node_id="character-generation",
                title="Character Generation",
                item=_item_with_slots(
                    node_id="character-generation",
                    item_id="character-1",
                    item_type="character",
                    display_name="Hero Character",
                    slots=[
                        _slot(
                            "character-generation",
                            "character-1",
                            "character_main_image",
                            "image",
                        ),
                        _slot(
                            "character-generation",
                            "character-1",
                            "character_three_view",
                            "image",
                            status="blocked",
                            dependency_slot_ids=["character-1:character_main_image"],
                        ),
                    ],
                ),
            ),
            _media_node(
                workflow_id,
                node_id="scene-generation",
                title="Scene Generation",
                item=_item_with_slots(
                    node_id="scene-generation",
                    item_id="scene-1",
                    item_type="scene",
                    display_name="Summer Office",
                    slots=[
                        _slot("scene-generation", "scene-1", "scene_main_image", "image"),
                        _slot(
                            "scene-generation",
                            "scene-1",
                            "scene_multi_view_grid",
                            "image",
                            status="blocked",
                            dependency_slot_ids=["scene-1:scene_main_image"],
                        ),
                    ],
                ),
            ),
            _media_node(
                workflow_id,
                node_id="bgm",
                title="BGM",
                item=_item_with_slots(
                    node_id="bgm",
                    item_id="bgm-1",
                    item_type="bgm",
                    display_name="BGM",
                    slots=[_slot("bgm", "bgm-1", "bgm_audio", "audio")],
                ),
            ),
            WorkflowNodeV2(
                node_id="storyboard",
                node_type="storyboard",
                title="Storyboard",
                status="ready",
                position={"x": 680, "y": 0},
                items=[_storyboard_item("shot-1", 1), _storyboard_item("shot-2", 2)],
                metadata={"workflow_id": workflow_id},
            ),
            WorkflowNodeV2(
                node_id="final-composition",
                node_type="final-composition",
                title="Final Composition",
                status="ready",
                position={"x": 1040, "y": 0},
                items=[
                    _item_with_slots(
                        node_id="final-composition",
                        item_id="final-composition-1",
                        item_type="final_composition",
                        display_name="Final Video",
                        slots=[
                            _slot(
                                "final-composition",
                                "final-composition-1",
                                "final_video",
                                "video",
                            )
                        ],
                    )
                ],
                metadata={"workflow_id": workflow_id},
            ),
        ],
        edges=_display_edges(workflow_id),
        runtime=WorkflowRuntimeV2(workflow_id=workflow_id),
        metadata={
            "original_user_prompt": "Create a summer launch ad for Lemon Tea.",
            "script_plan": script_plan.model_dump(mode="json"),
            "request": {
                "prompt": "Create a summer launch ad for Lemon Tea.",
                "product_name": "Lemon Tea",
            },
        },
        created_at=now,
        updated_at=now,
    )
    if save:
        projection = V2WorkflowStore(data_dir)
        projection.write_projection_atomic(workflow)
        V2ScriptVersionService(data_dir).read_selected(workflow_id)
        workflow = projection.read_projection_source(workflow_id)
        workflow = create_workflow_authoring_runtime(data_dir).service.create_planned_workflow(
            workflow, source="create"
        )
    return workflow


def _canonical_script_plan(workflow_id: str) -> V2ScriptPlanV2:
    shots = [
        V2ScriptShotV2(
            shot_id=f"shot-{index}",
            scene_id="scene-1",
            shot_index=index,
            product_ids=["product-1"],
            character_ids=["character-1"],
            scene_ids=["scene-1"],
            reference_item_ids=["product-1", "character-1", "scene-1"],
            description=f"Shot {index} advances the Lemon Tea summer story.",
            dialogue=[],
            narration=None,
            visual_prompt=f"Shot {index} summary with stable product identity.",
            duration_seconds=15,
        )
        for index in range(1, 3)
    ]
    plan = V2ScriptPlanV2(
        script_brief_id=f"script-brief-{workflow_id}",
        script_version_id=f"script-ver-{workflow_id}",
        language="en",
        script_title="Lemon Tea Summer Launch",
        script_text="",
        scenes=[
            V2ScriptScene(
                scene_id="scene-1",
                title="Summer Office",
                description="A bright summer office with clean product visibility.",
                location_id="scene-1",
                shot_ids=["shot-1", "shot-2"],
                duration_seconds=30,
            )
        ],
        shots=shots,
        characters=[
            V2ScriptCharacter(
                character_id="character-1",
                display_name="Hero Character",
                description="A confident customer in a summer campaign.",
                role="lead",
                visual_notes="Consistent wardrobe and natural styling.",
            )
        ],
        locations=[
            V2ScriptLocation(
                location_id="scene-1",
                display_name="Summer Office",
                description="A bright summer office.",
                visual_notes="Clean daylight and neutral surfaces.",
            )
        ],
        product_beats=["Show Lemon Tea clearly", "Connect refreshment to the summer moment"],
        tone="Fresh and confident",
        visual_style="Bright commercial realism",
        duration_seconds=30,
        aspect_ratio="16:9",
        materializer_mode="mock",
        materializer_version="test-v2-script-factory",
    )
    return V2ScreenplayRenderer().rendered_plan(plan)


def make_v2_completed_asset_workflow(
    data_dir: Path,
    *,
    workflow_id: str = "adwf_v2_assets",
    audio_mode: str = "bgm_only",
    selected_slots: Iterable[str] = (
        "product-1:product_main_image",
        "character-1:character_main_image",
        "scene-1:scene_main_image",
    ),
    selected_asset_overrides: dict[str, dict[str, Any]] | None = None,
) -> WorkflowV2:
    workflow = make_v2_workflow(data_dir, workflow_id=workflow_id, audio_mode=audio_mode)
    for slot_id in selected_slots:
        add_selected_asset_to_slot(
            data_dir,
            workflow,
            slot_id,
            **dict((selected_asset_overrides or {}).get(slot_id, {})),
        )
    return workflow


def find_v2_slot(
    workflow: WorkflowV2 | dict[str, Any], slot_id: str
) -> WorkflowSlotV2 | dict[str, Any]:
    nodes = workflow["nodes"] if isinstance(workflow, dict) else workflow.nodes
    for node in nodes:
        items = node["items"] if isinstance(node, dict) else node.items
        for item in items:
            slots = item["slots"] if isinstance(item, dict) else item.slots
            for slot in slots:
                current_id = slot["slot_id"] if isinstance(slot, dict) else slot.slot_id
                if current_id == slot_id:
                    return slot
    raise AssertionError(f"missing slot {slot_id}")


def add_selected_asset_to_slot(
    data_dir: Path,
    workflow: WorkflowV2,
    slot_id: str,
    *,
    asset_id: str | None = None,
    version_id: str | None = None,
    display_name: str | None = None,
    prompt_summary: str | None = None,
    user_summary_prompt: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    slot = find_v2_slot(workflow, slot_id)
    assert isinstance(slot, WorkflowSlotV2)
    resolved_asset_id = asset_id or _asset_id_for_slot(slot, suffix="selected")
    resolved_version_id = version_id or f"ver_{resolved_asset_id}"
    make_v2_asset_version(
        data_dir,
        workflow_id=workflow.workflow_id,
        asset_id=resolved_asset_id,
        version_id=resolved_version_id,
        media_type=slot.media_type,
        node_id=slot.node_id,
        item_id=slot.item_id,
        slot_id=slot.slot_id,
        semantic_type=_semantic_type_for_slot(slot),
        display_name=_display_name_for_slot(slot) if display_name is None else display_name,
        prompt_summary=prompt_summary or f"Summary for {slot.slot_id}.",
        user_summary_prompt=user_summary_prompt,
        provider_prompt=f"Provider prompt for {slot.slot_id}.",
        metadata=metadata,
    )
    make_v2_asset_relation(
        data_dir,
        relation_type="selected_for_slot",
        source_asset_id=resolved_asset_id,
        workflow_id=workflow.workflow_id,
        node_id=slot.node_id,
        item_id=slot.item_id,
        slot_id=slot.slot_id,
        version_id=resolved_version_id,
        metadata={
            "slot_type": slot.slot_type,
            "media_type": slot.media_type,
            "semantic_type": _semantic_type_for_slot(slot),
            "source_action": "test_factory",
        },
    )
    make_v2_asset_relation(
        data_dir,
        relation_type="working_version_for_slot",
        source_asset_id=resolved_asset_id,
        workflow_id=workflow.workflow_id,
        node_id=slot.node_id,
        item_id=slot.item_id,
        slot_id=slot.slot_id,
        version_id=resolved_version_id,
        metadata={
            "slot_type": slot.slot_type,
            "media_type": slot.media_type,
            "semantic_type": _semantic_type_for_slot(slot),
            "source_action": "test_factory",
        },
    )
    slot.selected_asset_id = resolved_asset_id
    slot.selected_version_id = resolved_version_id
    slot.current_working_asset_id = resolved_asset_id
    slot.current_working_version_id = resolved_version_id
    slot.status = "completed"
    persist_v2_workflow_semantic(workflow, data_dir, source="selected_version_change")
    return resolved_asset_id, resolved_version_id


def add_working_asset_to_slot(
    data_dir: Path,
    workflow: WorkflowV2,
    slot_id: str,
    *,
    asset_id: str | None = None,
    version_id: str | None = None,
) -> tuple[str, str]:
    slot = find_v2_slot(workflow, slot_id)
    assert isinstance(slot, WorkflowSlotV2)
    resolved_asset_id = asset_id or _asset_id_for_slot(slot, suffix="working")
    resolved_version_id = version_id or f"ver_{resolved_asset_id}"
    make_v2_asset_version(
        data_dir,
        workflow_id=workflow.workflow_id,
        asset_id=resolved_asset_id,
        version_id=resolved_version_id,
        media_type=slot.media_type,
        node_id=slot.node_id,
        item_id=slot.item_id,
        slot_id=slot.slot_id,
        semantic_type=_semantic_type_for_slot(slot),
        display_name=_display_name_for_slot(slot),
        prompt_summary=f"Working summary for {slot.slot_id}.",
        provider_prompt=f"Working provider prompt for {slot.slot_id}.",
    )
    make_v2_asset_relation(
        data_dir,
        relation_type="working_version_for_slot",
        source_asset_id=resolved_asset_id,
        workflow_id=workflow.workflow_id,
        node_id=slot.node_id,
        item_id=slot.item_id,
        slot_id=slot.slot_id,
        version_id=resolved_version_id,
        metadata={
            "slot_type": slot.slot_type,
            "media_type": slot.media_type,
            "semantic_type": _semantic_type_for_slot(slot),
            "source_action": "test_factory",
        },
    )
    slot.current_working_asset_id = resolved_asset_id
    slot.current_working_version_id = resolved_version_id
    slot.status = "completed"
    persist_v2_workflow_operational(workflow, data_dir)
    return resolved_asset_id, resolved_version_id


def persist_v2_workflow_semantic(
    workflow: WorkflowV2,
    data_dir: Path,
    *,
    source: WorkflowRevisionChangeSource,
) -> None:
    """Persist fixture authoring state without using the retired generic writer."""

    if workflow.state_version is None:
        raise AssertionError("test workflow is missing an authoring state version")
    operational = workflow.model_copy(deep=True)
    runtime = create_workflow_authoring_runtime(data_dir)
    committed = runtime.service.commit_semantic_workflow(
        workflow,
        expected_version=workflow.state_version,
        source=source,
    )
    _copy_operational_fields(committed, operational)
    runtime.projection.save_operational_overlay(
        committed,
        expected_revision_no=committed.semantic_revision_no or 0,
    )
    _replace_workflow(workflow, runtime.read_model.assemble(workflow.workflow_id))


def persist_v2_workflow_operational(workflow: WorkflowV2, data_dir: Path) -> None:
    """Persist fixture-only runtime fields through the typed operational overlay."""

    if workflow.semantic_revision_no is None:
        raise AssertionError("test workflow is missing an authoring revision")
    runtime = create_workflow_authoring_runtime(data_dir)
    runtime.projection.save_operational_overlay(
        workflow,
        expected_revision_no=workflow.semantic_revision_no,
    )
    _replace_workflow(workflow, runtime.read_model.assemble(workflow.workflow_id))


def _copy_operational_fields(target: WorkflowV2, source: WorkflowV2) -> None:
    source_slots = {
        slot.slot_id: slot for node in source.nodes for item in node.items for slot in item.slots
    }
    for node in target.nodes:
        source_node = next(
            (candidate for candidate in source.nodes if candidate.node_id == node.node_id),
            None,
        )
        if source_node is not None:
            node.status = source_node.status
        for item in node.items:
            source_item = (
                next(
                    (
                        candidate
                        for candidate in source_node.items
                        if candidate.item_id == item.item_id
                    ),
                    None,
                )
                if source_node is not None
                else None
            )
            if source_item is not None:
                item.status = source_item.status
            for slot in item.slots:
                source_slot = source_slots.get(slot.slot_id)
                if source_slot is None:
                    continue
                slot.status = source_slot.status
                slot.current_working_asset_id = source_slot.current_working_asset_id
                slot.current_working_version_id = source_slot.current_working_version_id


def _replace_workflow(target: WorkflowV2, source: WorkflowV2) -> None:
    target.__dict__.clear()
    target.__dict__.update(source.model_copy(deep=True).__dict__)


def add_free_asset(
    data_dir: Path,
    workflow: WorkflowV2,
    *,
    media_type: WorkflowMediaTypeV2 = "image",
    asset_id: str | None = None,
    version_id: str | None = None,
) -> tuple[str, str]:
    resolved_asset_id = asset_id or f"asset_free_{media_type}"
    resolved_version_id = version_id or f"ver_{resolved_asset_id}"
    semantic_type = {
        "audio": "free_audio",
        "video": "free_video",
    }.get(media_type, "free_image")
    make_v2_asset_version(
        data_dir,
        workflow_id=workflow.workflow_id,
        asset_id=resolved_asset_id,
        version_id=resolved_version_id,
        media_type=media_type,
        node_id="free-generation-1",
        item_id="free-item-1",
        slot_id="free-item-1:free_output",
        semantic_type=semantic_type,
        display_name=f"Free {media_type}",
        prompt_summary=f"Free {media_type} summary.",
    )
    return resolved_asset_id, resolved_version_id


def _script_node(workflow_id: str) -> WorkflowNodeV2:
    return WorkflowNodeV2(
        node_id="script",
        node_type="script",
        title="Script",
        status="completed",
        position={"x": 0, "y": 0},
        items=[
            WorkflowItemV2(
                item_id="script-1",
                node_id="script",
                item_type="script",
                display_name="Script",
                description="Compact test script.",
                item_prompt="A bright summer Lemon Tea ad.",
                status="completed",
                metadata={"script_text": "A bright summer Lemon Tea ad."},
            )
        ],
        metadata={"workflow_id": workflow_id},
    )


def _media_node(
    workflow_id: str,
    *,
    node_id: str,
    title: str,
    item: WorkflowItemV2,
) -> WorkflowNodeV2:
    return WorkflowNodeV2(
        node_id=node_id,
        node_type=node_id,
        title=title,
        status="ready",
        position={"x": 320, "y": 0},
        items=[item],
        metadata={"workflow_id": workflow_id},
    )


def _item_with_slots(
    *,
    node_id: str,
    item_id: str,
    item_type: str,
    display_name: str,
    slots: list[WorkflowSlotV2],
    shot_id: str | None = None,
    shot_index: int | None = None,
) -> WorkflowItemV2:
    return WorkflowItemV2(
        item_id=item_id,
        node_id=node_id,
        item_type=item_type,  # type: ignore[arg-type]
        display_name=display_name,
        description=f"{display_name} test item.",
        item_prompt=f"{display_name} prompt.",
        status="empty",
        shot_id=shot_id,
        shot_index=shot_index,
        slots=slots,
    )


def _storyboard_item(shot_id: str, shot_index: int) -> WorkflowItemV2:
    summary = f"Shot {shot_index} summary."
    cell_slots = [
        _slot("storyboard", shot_id, f"shot_cell_{index}", "image") for index in range(1, 5)
    ]
    video_slot = _slot(
        "storyboard",
        shot_id,
        "shot_video_segment",
        "video",
        status="blocked",
        dependency_slot_ids=[f"{shot_id}:shot_cell_{index}" for index in range(1, 5)],
    )
    return _item_with_slots(
        node_id="storyboard",
        item_id=shot_id,
        item_type="shot",
        display_name=f"Shot {shot_index}",
        shot_id=shot_id,
        shot_index=shot_index,
        slots=[*cell_slots, video_slot],
    ).model_copy(
        update={
            "shot_summary_prompt": summary,
            "duration_seconds": 5,
            "reference_item_ids": ["product-1", "character-1", "scene-1"],
            "primary_scene_item_id": "scene-1",
            "detail_prompts": {
                "shot_id": shot_id,
                "shot_index": shot_index,
                "required_shot_cell_slot_ids": [
                    f"{shot_id}:shot_cell_{index}" for index in range(1, 5)
                ],
                "storyboard_content": f"0.0-5.0s: {summary}",
                "dialogue": f"Dialogue direction for shot {shot_index}.",
                "audio_description": f"Audio atmosphere for shot {shot_index}.",
                "frames": [
                    {
                        "slot_type": f"shot_cell_{index}",
                        "prompt": f"{summary} frame {index}.",
                    }
                    for index in range(1, 5)
                ],
                "video_prompt": f"{summary} video.",
                "time_segments": [],
            },
            "metadata": {
                "desired_duration_seconds": 5,
                "provider_duration_seconds": 5,
                "time_segments": [],
                "detail_prompt_dirty_fields": [],
                "detail_prompts_outdated": False,
                "source_script_shot": {
                    "shot_id": shot_id,
                    "shot_index": shot_index,
                    "summary": summary,
                    "duration_seconds": 5,
                },
            },
        }
    )


def _slot(
    node_id: str,
    item_id: str,
    slot_type: str,
    media_type: WorkflowMediaTypeV2,
    *,
    status: str = "empty",
    dependency_slot_ids: list[str] | None = None,
) -> WorkflowSlotV2:
    return build_slot(
        node_id=node_id,
        item_id=item_id,
        slot_type=slot_type,
        media_type=media_type,
        status=status,
        prompt=f"{slot_type} prompt.",
        dependency_slot_ids=dependency_slot_ids,
    )


def _display_edges(workflow_id: str) -> list[WorkflowEdgeV2]:
    pairs = [
        ("script", "product-generation"),
        ("script", "character-generation"),
        ("script", "scene-generation"),
        ("script", "bgm"),
        ("product-generation", "storyboard"),
        ("character-generation", "storyboard"),
        ("scene-generation", "storyboard"),
        ("storyboard", "final-composition"),
        ("bgm", "final-composition"),
    ]
    return [
        WorkflowEdgeV2(
            edge_id=f"{source}->{target}",
            source_node_id=source,
            target_node_id=target,
            metadata={"workflow_id": workflow_id},
        )
        for source, target in pairs
    ]


def _asset_id_for_slot(slot: WorkflowSlotV2, *, suffix: str) -> str:
    normalized_slot = slot.slot_id.replace(":", "_").replace("-", "_")
    return f"asset_{normalized_slot}_{suffix}"


def _display_name_for_slot(slot: WorkflowSlotV2) -> str:
    return {
        "product_main_image": "Product main image",
        "character_main_image": "Character main image",
        "scene_main_image": "Scene main image",
        "bgm_audio": "BGM",
        "final_video": "Final video",
        "shot_video_segment": "Shot video segment",
    }.get(slot.slot_type, "Workflow asset")


def _semantic_type_for_slot(slot: WorkflowSlotV2) -> str:
    if slot.slot_type.startswith("shot_cell_"):
        return "shot_cell_image"
    return slot.slot_type
