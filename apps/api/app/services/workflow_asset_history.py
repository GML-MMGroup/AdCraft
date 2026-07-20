import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.services.agent_trace import utc_now
from app.services.asset_lifecycle import (
    compact_lifecycle_hint,
    lifecycle_record_for_asset_run,
    mark_missing_file,
    normalize_asset_lifecycle,
    mark_asset_active,
    mark_asset_archived,
)
from app.services.media_paths import with_public_urls
from app.services.output_assets import dedupe_output_assets


SEMANTIC_FIELD_BY_TYPE: dict[str, str] = {
    "character_main": "roleMainImageUri",
    "character_face_id": "roleFaceIdImageUri",
    "character_three_view": "roleThreeViewImageUri",
    "character_concept": "roleConceptImageUri",
    "scene_main": "sceneMainImageUri",
    "scene_multi_view": "sceneMultiViewImageUri",
    "storyboard_image": "storyboardImageUri",
    "storyboard_video": "storyboardVideoUri",
    "final_video": "finalVideoUri",
    "bgm": "musicUri",
}

ENTITY_KEYS = (
    "entity_id",
    "shotId",
    "shot_id",
    "sceneId",
    "scene_id",
    "roleId",
    "role_id",
    "characterId",
    "character_id",
    "id",
)


def asset_history_path(data_dir: Path, workflow_id: str, node_id: str) -> Path:
    return data_dir / "workflows" / workflow_id / "nodes" / node_id / "assets.json"


def asset_lifecycle_path(data_dir: Path, workflow_id: str, node_id: str) -> Path:
    return data_dir / "workflows" / workflow_id / "nodes" / node_id / "asset-lifecycle.json"


def load_node_asset_history(data_dir: Path, workflow_id: str, node_id: str) -> list[dict[str, Any]]:
    path = asset_history_path(data_dir, workflow_id, node_id)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    assets = (
        [asset for asset in payload if isinstance(asset, dict)] if isinstance(payload, list) else []
    )
    return [_history_asset_with_inferred_lifecycle(asset, data_dir) for asset in assets]


def _history_asset_with_inferred_lifecycle(
    asset: dict[str, Any],
    data_dir: Path,
) -> dict[str, Any]:
    inferred = dict(asset)
    if not inferred.get("asset_state") or not inferred.get("asset_origin"):
        lifecycle = normalize_asset_lifecycle(inferred, default_origin="migration")
        inferred = {**inferred, **compact_lifecycle_hint(lifecycle)}
    return mark_missing_file(inferred, data_dir)


def persist_node_asset_history(
    *,
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    run_id: str,
    output_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not output_assets:
        return load_node_asset_history(data_dir, workflow_id, node_id)
    history = load_node_asset_history(data_dir, workflow_id, node_id)
    updated = _merge_assets_by_id(history, [])
    lifecycle_records = _load_asset_lifecycle(data_dir, workflow_id, node_id)
    now = utc_now().isoformat()
    for raw_asset in output_assets:
        lifecycle = lifecycle_record_for_asset_run(
            raw_asset,
            workflow_id=workflow_id,
            node_id=node_id,
            node_run_id=run_id,
            default_origin="provider_generation",
        )
        asset = _enrich_asset(
            raw_asset,
            workflow_id=workflow_id,
            node_id=node_id,
            run_id=run_id,
            created_at=now,
        )
        if asset.get("is_active") is not False:
            _deactivate_same_slot(updated, asset, lifecycle_records)
            asset = mark_asset_active(asset)
            lifecycle.update(compact_lifecycle_hint(asset))
        asset.update(compact_lifecycle_hint(lifecycle))
        lifecycle_records[str(asset["asset_id"])] = lifecycle
        updated[str(asset["asset_id"])] = asset
    _write_asset_lifecycle(data_dir, workflow_id, node_id, lifecycle_records)
    return write_node_asset_history(data_dir, workflow_id, node_id, list(updated.values()))


def write_node_asset_history(
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    path = asset_history_path(data_dir, workflow_id, node_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    deduped = dedupe_output_assets(assets)
    path.write_text(
        json.dumps(deduped, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return deduped


def _load_asset_lifecycle(
    data_dir: Path,
    workflow_id: str,
    node_id: str,
) -> dict[str, dict[str, Any]]:
    path = asset_lifecycle_path(data_dir, workflow_id, node_id)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, list):
        return {
            str(record.get("asset_id")): record
            for record in payload
            if isinstance(record, dict) and record.get("asset_id")
        }
    if isinstance(payload, dict):
        return {
            str(asset_id): record
            for asset_id, record in payload.items()
            if isinstance(record, dict)
        }
    return {}


def _write_asset_lifecycle(
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    records: dict[str, dict[str, Any]],
) -> None:
    path = asset_lifecycle_path(data_dir, workflow_id, node_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(list(records.values()), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def select_existing_asset(
    *,
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    active_result: dict[str, Any],
    revision: dict[str, Any],
    state_change_run_id: str,
    persist: bool = True,
) -> dict[str, Any]:
    run_history = _load_assets_from_node_runs(data_dir, workflow_id, node_id)
    history = list(
        _merge_assets_by_id(
            run_history, load_node_asset_history(data_dir, workflow_id, node_id)
        ).values()
    )
    output = deepcopy(active_result.get("output") or {})
    active_assets = _assets_from_active_result(active_result)
    all_assets_by_id = _merge_assets_by_id(history, active_assets)
    selected = _resolve_revision_asset(list(all_assets_by_id.values()), revision)
    selected_id = str(selected.get("asset_id") or "")
    entity_id = _revision_entity_id(revision, selected)
    semantic_type = str(revision.get("semantic_type") or selected.get("semantic_type") or "")
    field_name = _target_field_for_revision_asset(revision, selected, semantic_type=semantic_type)
    if not entity_id or not semantic_type:
        raise ValueError("revision target must include a resolvable entity_id and semantic_type.")
    if not field_name:
        raise ValueError(f"unsupported semantic_type for structured output update: {semantic_type}")

    previous_active_asset_id = ""
    for asset in all_assets_by_id.values():
        if not _same_entity_slot(asset, entity_id, semantic_type):
            continue
        if asset.get("is_active") is True and asset.get("asset_id") != selected_id:
            previous_active_asset_id = str(asset.get("asset_id") or "")
        asset["is_active"] = asset.get("asset_id") == selected_id
        asset["is_archived"] = bool(asset.get("is_archived", False))
        if asset.get("asset_id") == selected_id:
            asset["workflow_id"] = workflow_id
            asset["node_id"] = node_id
            asset.setdefault("metadata", {})
            asset["metadata"]["selected_by_run_id"] = state_change_run_id

    _update_structured_output_uri(
        output,
        entity_id=entity_id,
        field_name=field_name,
        uri=_asset_uri(selected),
        revision=revision,
        state_change_run_id=state_change_run_id,
    )
    updated_assets = list(all_assets_by_id.values())
    updated_assets = (
        write_node_asset_history(data_dir, workflow_id, node_id, updated_assets)
        if persist
        else dedupe_output_assets(updated_assets)
    )
    output_assets = _updated_output_assets(
        active_assets, selected, updated_assets, entity_id, semantic_type
    )
    output["assets"] = output_assets
    output["output_assets"] = output_assets
    return {
        "output": output,
        "output_assets": with_public_urls(output_assets),
        "selected_asset": with_public_urls(selected),
        "previous_active_asset_id": previous_active_asset_id,
    }


def apply_generated_revision_asset(
    *,
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    active_result: dict[str, Any],
    revision: dict[str, Any],
    generated_asset: dict[str, Any],
    state_change_run_id: str,
    persist: bool = True,
) -> dict[str, Any]:
    output = deepcopy(active_result.get("output") or {})
    active_assets = _assets_from_active_result(active_result)
    history = list(
        _merge_assets_by_id(
            _load_assets_from_node_runs(data_dir, workflow_id, node_id),
            load_node_asset_history(data_dir, workflow_id, node_id),
        ).values()
    )
    all_assets_by_id = _merge_assets_by_id(history, active_assets)
    selected = _enrich_asset(
        generated_asset,
        workflow_id=workflow_id,
        node_id=node_id,
        run_id=state_change_run_id,
        created_at=utc_now().isoformat(),
    )
    entity_id = _revision_entity_id(revision, selected)
    semantic_type = str(revision.get("semantic_type") or selected.get("semantic_type") or "")
    field_name = _target_field_for_revision_asset(revision, selected, semantic_type=semantic_type)
    if not entity_id or not semantic_type:
        raise ValueError("revision target must include a resolvable entity_id and semantic_type.")
    if not field_name:
        raise ValueError(f"unsupported semantic_type for structured output update: {semantic_type}")

    previous_active_asset_id = ""
    for asset in all_assets_by_id.values():
        if not _same_entity_slot(asset, entity_id, semantic_type):
            continue
        if asset.get("is_active") is True:
            previous_active_asset_id = str(asset.get("asset_id") or "")
        asset["is_active"] = False
        asset["is_archived"] = bool(asset.get("is_archived", False))
    selected["workflow_id"] = workflow_id
    selected["node_id"] = node_id
    selected["entity_id"] = entity_id
    selected["semantic_type"] = semantic_type
    selected["is_active"] = True
    selected["is_archived"] = bool(selected.get("is_archived", False))
    selected.setdefault("metadata", {})
    selected["metadata"]["revision_id"] = state_change_run_id
    all_assets_by_id[str(selected["asset_id"])] = selected

    _update_structured_output_uri(
        output,
        entity_id=entity_id,
        field_name=field_name,
        uri=_asset_uri(selected),
        revision=revision,
        state_change_run_id=state_change_run_id,
    )
    updated_assets = list(all_assets_by_id.values())
    updated_assets = (
        write_node_asset_history(data_dir, workflow_id, node_id, updated_assets)
        if persist
        else dedupe_output_assets(updated_assets)
    )
    output_assets = _updated_output_assets(
        active_assets, selected, updated_assets, entity_id, semantic_type
    )
    output["assets"] = output_assets
    output["output_assets"] = output_assets
    return {
        "output": output,
        "output_assets": with_public_urls(output_assets),
        "selected_asset": with_public_urls(selected),
        "previous_active_asset_id": previous_active_asset_id,
    }


def apply_generated_revision_assets(
    *,
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    active_result: dict[str, Any],
    revision: dict[str, Any],
    generated_assets: list[dict[str, Any]],
    state_change_run_id: str,
    persist: bool = True,
) -> dict[str, Any]:
    if not generated_assets:
        raise ValueError("revision candidate has no generated assets.")
    output = deepcopy(active_result.get("output") or {})
    active_assets = _assets_from_active_result(active_result)
    history = list(
        _merge_assets_by_id(
            _load_assets_from_node_runs(data_dir, workflow_id, node_id),
            load_node_asset_history(data_dir, workflow_id, node_id),
        ).values()
    )
    all_assets_by_id = _merge_assets_by_id(history, active_assets)
    selected_assets: list[dict[str, Any]] = []
    previous_active_asset_ids: list[str] = []
    now = utc_now().isoformat()
    for generated_asset in generated_assets:
        selected = _enrich_asset(
            generated_asset,
            workflow_id=workflow_id,
            node_id=node_id,
            run_id=state_change_run_id,
            created_at=now,
        )
        entity_id = _revision_entity_id(revision, selected)
        semantic_type = str(selected.get("semantic_type") or revision.get("semantic_type") or "")
        field_name = _target_field_for_revision_asset(revision, selected)
        if not entity_id or not semantic_type:
            raise ValueError(
                "revision target must include a resolvable entity_id and semantic_type."
            )
        if not field_name:
            raise ValueError(
                f"unsupported semantic_type for structured output update: {semantic_type}"
            )

        previous_active_asset_id = ""
        for asset in all_assets_by_id.values():
            if not _same_entity_slot(asset, entity_id, semantic_type):
                continue
            if asset.get("is_active") is True:
                previous_active_asset_id = str(asset.get("asset_id") or "")
            asset["is_active"] = False
            asset["is_archived"] = bool(asset.get("is_archived", False))
        if previous_active_asset_id:
            previous_active_asset_ids.append(previous_active_asset_id)

        selected["workflow_id"] = workflow_id
        selected["node_id"] = node_id
        selected["entity_id"] = entity_id
        selected["semantic_type"] = semantic_type
        selected["target_field"] = field_name
        selected["is_active"] = True
        selected["is_archived"] = bool(selected.get("is_archived", False))
        selected.setdefault("metadata", {})
        selected["metadata"]["revision_id"] = state_change_run_id
        all_assets_by_id[str(selected["asset_id"])] = selected
        selected_assets.append(selected)

        _update_structured_output_uri(
            output,
            entity_id=entity_id,
            field_name=field_name,
            uri=_asset_uri(selected),
            revision={
                **revision,
                "target_entity_id": entity_id,
                "semantic_type": semantic_type,
                "target_field": field_name,
            },
            state_change_run_id=state_change_run_id,
        )

    updated_assets = list(all_assets_by_id.values())
    updated_assets = (
        write_node_asset_history(data_dir, workflow_id, node_id, updated_assets)
        if persist
        else dedupe_output_assets(updated_assets)
    )
    output_assets = _active_output_assets(active_assets, updated_assets)
    output["assets"] = output_assets
    output["output_assets"] = output_assets
    public_selected_assets = with_public_urls(selected_assets)
    previous_active_asset_ids = list(dict.fromkeys(previous_active_asset_ids))
    return {
        "output": output,
        "output_assets": with_public_urls(output_assets),
        "selected_asset": public_selected_assets[0],
        "selected_assets": public_selected_assets,
        "previous_active_asset_id": previous_active_asset_ids[0]
        if previous_active_asset_ids
        else "",
        "previous_active_asset_ids": previous_active_asset_ids,
    }


def prepare_generated_revision_candidate(
    *,
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    active_result: dict[str, Any],
    revision: dict[str, Any],
    generated_asset: dict[str, Any],
    state_change_run_id: str,
    persist: bool = True,
) -> dict[str, Any]:
    active_assets = _assets_from_active_result(active_result)
    history = list(
        _merge_assets_by_id(
            _load_assets_from_node_runs(data_dir, workflow_id, node_id),
            load_node_asset_history(data_dir, workflow_id, node_id),
        ).values()
    )
    all_assets_by_id = _merge_assets_by_id(history, active_assets)
    candidate = _enrich_asset(
        generated_asset,
        workflow_id=workflow_id,
        node_id=node_id,
        run_id=state_change_run_id,
        created_at=utc_now().isoformat(),
    )
    entity_id = _revision_entity_id(revision, candidate)
    semantic_type = str(revision.get("semantic_type") or candidate.get("semantic_type") or "")
    field_name = _target_field_for_revision_asset(revision, candidate, semantic_type=semantic_type)
    if not entity_id or not semantic_type:
        raise ValueError("revision target must include a resolvable entity_id and semantic_type.")
    if not field_name:
        raise ValueError(f"unsupported semantic_type for structured output update: {semantic_type}")

    previous_active_asset_id = ""
    for asset in all_assets_by_id.values():
        if _same_entity_slot(asset, entity_id, semantic_type) and asset.get("is_active") is True:
            previous_active_asset_id = str(asset.get("asset_id") or "")
            break
    candidate["workflow_id"] = workflow_id
    candidate["node_id"] = node_id
    candidate["source_node_id"] = node_id
    candidate["entity_id"] = entity_id
    candidate["semantic_type"] = semantic_type
    candidate["target_field"] = field_name
    candidate["is_active"] = False
    candidate["is_archived"] = False
    candidate["candidate_status"] = "pending"
    candidate["acceptance_status"] = "pending"
    candidate["visibility_status"] = "visible"
    candidate.setdefault("metadata", {})
    candidate["metadata"]["revision_id"] = state_change_run_id
    all_assets_by_id[str(candidate["asset_id"])] = candidate

    updated_assets = list(all_assets_by_id.values())
    updated_assets = (
        write_node_asset_history(data_dir, workflow_id, node_id, updated_assets)
        if persist
        else dedupe_output_assets(updated_assets)
    )
    return {
        "candidate_asset": with_public_urls(candidate),
        "previous_active_asset_id": previous_active_asset_id,
        "history": with_public_urls(updated_assets),
    }


def prepare_generated_revision_candidates(
    *,
    data_dir: Path,
    workflow_id: str,
    node_id: str,
    active_result: dict[str, Any],
    revision: dict[str, Any],
    generated_assets: list[dict[str, Any]],
    state_change_run_id: str,
    persist: bool = True,
) -> dict[str, Any]:
    if not generated_assets:
        raise ValueError("revision candidate has no generated assets.")
    active_assets = _assets_from_active_result(active_result)
    history = list(
        _merge_assets_by_id(
            _load_assets_from_node_runs(data_dir, workflow_id, node_id),
            load_node_asset_history(data_dir, workflow_id, node_id),
        ).values()
    )
    all_assets_by_id = _merge_assets_by_id(history, active_assets)
    candidate_assets: list[dict[str, Any]] = []
    previous_active_asset_ids: list[str] = []
    now = utc_now().isoformat()
    for generated_asset in generated_assets:
        candidate = _enrich_asset(
            generated_asset,
            workflow_id=workflow_id,
            node_id=node_id,
            run_id=state_change_run_id,
            created_at=now,
        )
        entity_id = _revision_entity_id(revision, candidate)
        semantic_type = str(candidate.get("semantic_type") or revision.get("semantic_type") or "")
        field_name = _target_field_for_revision_asset(revision, candidate)
        if not entity_id or not semantic_type:
            raise ValueError(
                "revision target must include a resolvable entity_id and semantic_type."
            )
        if not field_name:
            raise ValueError(
                f"unsupported semantic_type for structured output update: {semantic_type}"
            )

        previous_active_asset_id = ""
        for asset in all_assets_by_id.values():
            if (
                _same_entity_slot(asset, entity_id, semantic_type)
                and asset.get("is_active") is True
            ):
                previous_active_asset_id = str(asset.get("asset_id") or "")
                break
        if previous_active_asset_id:
            previous_active_asset_ids.append(previous_active_asset_id)

        candidate["workflow_id"] = workflow_id
        candidate["node_id"] = node_id
        candidate["source_node_id"] = node_id
        candidate["entity_id"] = entity_id
        candidate["semantic_type"] = semantic_type
        candidate["target_field"] = field_name
        candidate["is_active"] = False
        candidate["is_archived"] = False
        candidate["candidate_status"] = "pending"
        candidate["acceptance_status"] = "pending"
        candidate["visibility_status"] = "visible"
        candidate.setdefault("metadata", {})
        candidate["metadata"]["revision_id"] = state_change_run_id
        all_assets_by_id[str(candidate["asset_id"])] = candidate
        candidate_assets.append(candidate)

    updated_assets = list(all_assets_by_id.values())
    updated_assets = (
        write_node_asset_history(data_dir, workflow_id, node_id, updated_assets)
        if persist
        else dedupe_output_assets(updated_assets)
    )
    previous_active_asset_ids = list(dict.fromkeys(previous_active_asset_ids))
    return {
        "candidate_assets": with_public_urls(candidate_assets),
        "candidate_asset": with_public_urls(candidate_assets)[0],
        "previous_active_asset_ids": previous_active_asset_ids,
        "previous_active_asset_id": previous_active_asset_ids[0]
        if previous_active_asset_ids
        else "",
        "history": with_public_urls(updated_assets),
    }


def _merge_assets_by_id(
    history: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for asset in [*history, *incoming]:
        asset_id = str(asset.get("asset_id") or "")
        if not asset_id:
            continue
        merged[asset_id] = deepcopy(asset)
    return merged


def _load_assets_from_node_runs(
    data_dir: Path,
    workflow_id: str,
    node_id: str,
) -> list[dict[str, Any]]:
    node_dir = data_dir / "runs" / workflow_id / "nodes" / node_id
    if not node_dir.exists():
        return []
    assets: list[dict[str, Any]] = []
    for run_path in sorted(node_dir.glob("nrun_*.json")):
        try:
            payload = json.loads(run_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("status") != "completed":
            continue
        run_id = str(payload.get("node_run_id") or run_path.stem)
        run_active = bool(payload.get("active"))
        for asset in _assets_from_run_payload(payload):
            enriched = _enrich_asset(
                asset,
                workflow_id=workflow_id,
                node_id=node_id,
                run_id=run_id,
                created_at=str(payload.get("finished_at") or payload.get("started_at") or ""),
            )
            enriched["is_active"] = bool(enriched.get("is_active")) and run_active
            assets.append(enriched)
    return dedupe_output_assets(assets)


def _assets_from_run_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    output_assets = payload.get("output_assets")
    if isinstance(output_assets, list):
        assets.extend(asset for asset in output_assets if isinstance(asset, dict))
    output = payload.get("output")
    if isinstance(output, dict):
        for key in ("assets", "output_assets"):
            value = output.get(key)
            if isinstance(value, list):
                assets.extend(asset for asset in value if isinstance(asset, dict))
    return dedupe_output_assets(assets)


def _assets_from_active_result(active_result: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    output_assets = active_result.get("output_assets")
    if isinstance(output_assets, list):
        assets.extend(asset for asset in output_assets if isinstance(asset, dict))
    output = active_result.get("output")
    if isinstance(output, dict):
        for key in ("assets", "output_assets"):
            value = output.get(key)
            if isinstance(value, list):
                assets.extend(asset for asset in value if isinstance(asset, dict))
    return dedupe_output_assets(assets)


def _enrich_asset(
    asset: dict[str, Any],
    *,
    workflow_id: str,
    node_id: str,
    run_id: str,
    created_at: str,
) -> dict[str, Any]:
    enriched = deepcopy(asset)
    enriched.setdefault("asset_id", f"{node_id}-{run_id}-{len(enriched)}")
    enriched.setdefault("workflow_id", workflow_id)
    enriched.setdefault("node_id", node_id)
    enriched.setdefault("run_id", run_id)
    enriched.setdefault("entity_id", _entity_id(enriched))
    enriched.setdefault("asset_type", enriched.get("type") or enriched.get("media_type"))
    enriched.setdefault("semantic_type", enriched.get("role") or enriched.get("kind"))
    enriched.setdefault("is_active", True)
    enriched.setdefault("is_archived", False)
    enriched.setdefault("created_at", created_at)
    enriched.setdefault("metadata", {})
    return enriched


def _deactivate_same_slot(
    assets_by_id: dict[str, dict[str, Any]],
    selected: dict[str, Any],
    lifecycle_records: dict[str, dict[str, Any]] | None = None,
) -> None:
    entity_id = _entity_id(selected)
    semantic_type = str(selected.get("semantic_type") or "")
    if not entity_id or not semantic_type:
        return
    for asset in assets_by_id.values():
        if _same_entity_slot(asset, entity_id, semantic_type):
            archived = mark_asset_archived(asset)
            asset.update(archived)
            if lifecycle_records is not None:
                asset_id = str(asset.get("asset_id") or "")
                if asset_id:
                    lifecycle_records[asset_id] = {
                        **lifecycle_records.get(asset_id, {"asset_id": asset_id}),
                        **compact_lifecycle_hint(archived),
                    }


def _resolve_revision_asset(
    assets: list[dict[str, Any]],
    revision: dict[str, Any],
) -> dict[str, Any]:
    target_asset_id = str(revision.get("target_asset_id") or "")
    if target_asset_id:
        matches = [asset for asset in assets if asset.get("asset_id") == target_asset_id]
        if not matches:
            raise ValueError(f"target_asset_id not found: {target_asset_id}")
        selected = deepcopy(matches[0])
        _validate_selected_asset_matches_revision(selected, revision)
        return selected

    target_entity_id = str(revision.get("target_entity_id") or "")
    semantic_type = str(revision.get("semantic_type") or "")
    matches = [
        asset
        for asset in assets
        if _same_entity_slot(asset, target_entity_id, semantic_type)
        and asset.get("is_archived") is not True
    ]
    if len(matches) != 1:
        raise ValueError("revision target must resolve to a unique asset; provide target_asset_id.")
    return deepcopy(matches[0])


def _validate_selected_asset_matches_revision(
    asset: dict[str, Any],
    revision: dict[str, Any],
) -> None:
    target_entity_id = str(revision.get("target_entity_id") or "")
    semantic_type = str(revision.get("semantic_type") or "")
    if target_entity_id and _entity_id(asset) != target_entity_id:
        raise ValueError("target_asset_id does not match target_entity_id.")
    if semantic_type and str(asset.get("semantic_type") or "") != semantic_type:
        raise ValueError("target_asset_id does not match semantic_type.")


def _revision_entity_id(revision: dict[str, Any], selected: dict[str, Any]) -> str:
    return str(revision.get("target_entity_id") or _entity_id(selected) or "")


def _target_field_for_revision_asset(
    revision: dict[str, Any],
    selected: dict[str, Any],
    *,
    semantic_type: str | None = None,
) -> str:
    semantic = str(
        semantic_type or selected.get("semantic_type") or revision.get("semantic_type") or ""
    )
    return str(
        SEMANTIC_FIELD_BY_TYPE.get(semantic)
        or revision.get("target_field")
        or selected.get("target_field")
        or ""
    )


def _same_entity_slot(asset: dict[str, Any], entity_id: str, semantic_type: str) -> bool:
    return _entity_id(asset) == entity_id and str(asset.get("semantic_type") or "") == semantic_type


def _entity_id(asset: dict[str, Any]) -> str:
    for key in ENTITY_KEYS:
        value = asset.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _asset_uri(asset: dict[str, Any]) -> str:
    for key in ("uri", "local_path", "public_url", "remote_url", "url"):
        value = asset.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise ValueError("selected asset has no usable uri/local_path/public_url.")


def _update_structured_output_uri(
    output: dict[str, Any],
    *,
    entity_id: str,
    field_name: str,
    uri: str,
    revision: dict[str, Any],
    state_change_run_id: str,
) -> None:
    structured = output.setdefault("structured_output", {})
    if field_name == "finalVideoUri":
        structured[field_name] = uri
        output["status"] = "ready"
        output["composition_status"] = "ready"
        output["local_path"] = uri
        metadata = output.setdefault("metadata", {})
        metadata["lastRevisionPrompt"] = str(revision.get("instruction") or "")
        metadata["lastRevisionRunId"] = state_change_run_id
        for field in (
            "optimizedRevisionPrompt",
            "providerRevisionPrompt",
            "revisionRequirements",
        ):
            if revision.get(field) not in (None, ""):
                metadata[field] = revision[field]
        return
    updated = _update_item_collection(
        structured,
        entity_id=entity_id,
        field_name=field_name,
        uri=uri,
        revision=revision,
        state_change_run_id=state_change_run_id,
    )
    if not updated:
        updated = _update_item_collection(
            output,
            entity_id=entity_id,
            field_name=field_name,
            uri=uri,
            revision=revision,
            state_change_run_id=state_change_run_id,
        )
    if not updated:
        raise ValueError(f"could not locate structured output item for entity_id: {entity_id}")


def _update_item_collection(
    container: dict[str, Any],
    *,
    entity_id: str,
    field_name: str,
    uri: str,
    revision: dict[str, Any],
    state_change_run_id: str,
) -> bool:
    for value in container.values():
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict) or _entity_id(item) != entity_id:
                continue
            item[field_name] = uri
            metadata = item.setdefault("metadata", {})
            metadata["lastRevisionPrompt"] = str(revision.get("instruction") or "")
            metadata["lastRevisionRunId"] = state_change_run_id
            for field in (
                "optimizedRevisionPrompt",
                "providerRevisionPrompt",
                "revisionRequirements",
            ):
                if revision.get(field) not in (None, ""):
                    metadata[field] = revision[field]
            return True
    return False


def _updated_output_assets(
    active_assets: list[dict[str, Any]],
    selected: dict[str, Any],
    history: list[dict[str, Any]],
    entity_id: str,
    semantic_type: str,
) -> list[dict[str, Any]]:
    history_by_id = {str(asset.get("asset_id") or ""): asset for asset in history}
    updated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for asset in active_assets:
        asset_id = str(asset.get("asset_id") or "")
        replacement = history_by_id.get(asset_id, asset)
        if replacement.get("is_active") is not False:
            updated.append(deepcopy(replacement))
        seen.add(asset_id)
    selected_id = str(selected.get("asset_id") or "")
    if selected_id not in seen and selected_id in history_by_id:
        updated.append(deepcopy(history_by_id[selected_id]))
    for asset in history:
        asset_id = str(asset.get("asset_id") or "")
        if asset_id in seen or asset_id == selected_id:
            continue
        if asset.get("is_active") is False:
            continue
        if _same_entity_slot(asset, entity_id, semantic_type):
            updated.append(deepcopy(asset))
    return dedupe_output_assets(updated)


def _active_output_assets(
    active_assets: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    history_by_id = {str(asset.get("asset_id") or ""): asset for asset in history}
    updated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for asset in active_assets:
        asset_id = str(asset.get("asset_id") or "")
        replacement = history_by_id.get(asset_id, asset)
        if replacement.get("is_active") is not False:
            updated.append(deepcopy(replacement))
        if asset_id:
            seen.add(asset_id)
    for asset in history:
        asset_id = str(asset.get("asset_id") or "")
        if asset_id in seen:
            continue
        if asset.get("is_active") is False:
            continue
        updated.append(deepcopy(asset))
        if asset_id:
            seen.add(asset_id)
    return dedupe_output_assets(updated)
