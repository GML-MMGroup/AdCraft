"""Read-only Brand Professional Mode decision and inspection APIs."""

from __future__ import annotations

from collections.abc import Iterator
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.core.config import get_settings
from app.persistence.database import V2Database, create_v2_database
from app.persistence.errors import V2PersistenceError
from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.models import AgentCanvasChatTurnRow
from app.schemas.brand_professional_mode import (
    BrandDecisionPanelV1,
)

router = APIRouter()


def _brand_database() -> Iterator[V2Database]:
    database = create_v2_database(get_settings().media_data_dir)
    try:
        yield database
    finally:
        database.dispose()


def _brand_id_for_workflow(database: V2Database, workflow_id: str) -> str:
    repository = BrandDecisionRepository(database)
    project_id = repository.project_id_for_workflow(workflow_id)
    if project_id is None:
        raise _not_found()
    brand_id = repository.get_brand_id_by_project(project_id)
    if brand_id is None:
        raise _not_found()
    return brand_id


def _raise_not_found() -> None:
    raise HTTPException(
        status_code=404,
        detail={
            "code": "brand_decisions_not_found",
            "message": "Brand decisions not found for this workflow.",
        },
    )


@router.get("/brand/decisions", response_model=BrandDecisionPanelV1)
def get_brand_decisions(
    workflow_id: str = Query(min_length=1),
    database: V2Database = Depends(_brand_database),
) -> BrandDecisionPanelV1:
    repository = BrandDecisionRepository(database)
    try:
        brand_id = _brand_id_for_workflow(database, workflow_id)
    except V2PersistenceError:
        _raise_not_found()
    journey = repository.get_journey(brand_id)
    if journey is None:
        raise _not_found()
    project_id = repository.project_id_for_workflow(workflow_id)
    with database.engine.connect() as connection:
        brand_name = repository.get_brand_name_in_transaction(connection, brand_id)
        open_card = repository.get_open_card_in_transaction(connection, brand_id)
        hypotheses = repository.get_hypotheses_in_transaction(connection, brand_id)
        selected = repository.get_selected_hypothesis_id_in_transaction(connection, brand_id)
        adspec = repository.get_adspec_in_transaction(connection, brand_id)
        skill_stack = repository.get_skill_stack_in_transaction(connection, brand_id)
        steps = repository.get_treatment_steps_in_transaction(connection, brand_id)
    treatment_locked = journey.stage == "production"
    return BrandDecisionPanelV1(
        project_id=project_id or "",
        workflow_id=workflow_id,
        mode="brand",
        journey=journey,
        brand_name=brand_name,
        slot_values=repository.get_slot_values(brand_id),
        open_card=open_card,
        hypotheses=hypotheses,
        selected_hypothesis_id=selected,
        adspec=adspec,
        skill_stack=skill_stack,
        treatment_steps=steps,
        treatment_locked=treatment_locked,
    )


@router.get("/brand/inspection/conversation")
def inspect_conversation(
    workflow_id: str = Query(min_length=1),
    database: V2Database = Depends(_brand_database),
) -> dict:
    try:
        _brand_id_for_workflow(database, workflow_id)
    except V2PersistenceError:
        _raise_not_found()
    with database.engine.connect() as connection:
        rows = connection.execute(
            select(AgentCanvasChatTurnRow)
            .where(AgentCanvasChatTurnRow.workflow_id == workflow_id)
            .order_by(AgentCanvasChatTurnRow.created_at)
        ).all()
    turns = []
    for row in rows:
        text_value = _turn_text(row.request_json)
        role = "user" if row.turn_kind in {"user", "media_review"} else "assistant"
        turns.append(
            {
                "turn_id": row.turn_id,
                "role": role,
                "text": text_value,
                "status": row.status,
                "error_code": row.error_code,
                "created_at": row.created_at,
            }
        )
    return {"workflow_id": workflow_id, "turns": turns}


@router.get("/brand/inspection/decision-log")
def inspect_decision_log(
    workflow_id: str = Query(min_length=1),
    database: V2Database = Depends(_brand_database),
) -> dict:
    try:
        brand_id = _brand_id_for_workflow(database, workflow_id)
    except V2PersistenceError:
        _raise_not_found()
    entries = BrandDecisionRepository(database).list_decision_log(brand_id)
    return {
        "workflow_id": workflow_id,
        "entries": [entry.model_dump(mode="json") for entry in entries],
    }


@router.get("/brand/inspection/traces")
def inspect_traces(
    workflow_id: str = Query(min_length=1),
    database: V2Database = Depends(_brand_database),
) -> dict:
    try:
        _brand_id_for_workflow(database, workflow_id)
    except V2PersistenceError:
        _raise_not_found()
    trace_path = get_settings().media_data_dir / "v2" / "runs" / workflow_id / "trace.json"
    if not trace_path.exists():
        return {"workflow_id": workflow_id, "traces": []}
    try:
        payload = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"workflow_id": workflow_id, "traces": []}
    return {"workflow_id": workflow_id, "traces": payload}


def _turn_text(request_json: str) -> str:
    try:
        payload = json.loads(request_json)
    except json.JSONDecodeError:
        return ""
    if isinstance(payload, dict):
        text_value = payload.get("text")
        if isinstance(text_value, str):
            return text_value
    return ""


def _not_found() -> V2PersistenceError:
    return V2PersistenceError(
        "brand_decisions_not_found",
        "Brand decisions not found for this workflow.",
        stage="brand_mode_api",
    )
