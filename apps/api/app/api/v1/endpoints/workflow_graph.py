from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_workflow_graph_service
from app.schemas.workflow_graph import (
    MarkStaleRequest,
    WorkflowGraph,
    WorkflowGraphEdgeDeleteResponse,
    WorkflowGraphEdgeMutationResponse,
    WorkflowGraphEdgeCreateRequest,
    WorkflowGraphEdgePatchRequest,
    WorkflowGraphNodeCreateRequest,
    WorkflowGraphNodePatchRequest,
    WorkflowGraphSaveRequest,
    WorkflowGraphValidationResponse,
    WorkflowNodeVersionsResponse,
)
from app.services.workflow_graph import WorkflowGraphError, WorkflowGraphService

router = APIRouter(prefix="/workflows", tags=["workflow-graph"])


@router.get("/{workflow_id}", response_model=WorkflowGraph)
def get_workflow_graph(
    workflow_id: str,
    service: Annotated[WorkflowGraphService, Depends(get_workflow_graph_service)],
) -> WorkflowGraph:
    try:
        return service.get_graph(workflow_id)
    except WorkflowGraphError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{workflow_id}", response_model=WorkflowGraph)
def save_workflow_graph(
    workflow_id: str,
    request: WorkflowGraphSaveRequest,
    service: Annotated[WorkflowGraphService, Depends(get_workflow_graph_service)],
) -> WorkflowGraph:
    try:
        return service.save_full_graph(workflow_id, request)
    except WorkflowGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{workflow_id}/validate", response_model=WorkflowGraphValidationResponse)
def validate_workflow_graph(
    workflow_id: str,
    service: Annotated[WorkflowGraphService, Depends(get_workflow_graph_service)],
) -> WorkflowGraphValidationResponse:
    try:
        return service.validate(workflow_id)
    except WorkflowGraphError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{workflow_id}/nodes", response_model=WorkflowGraph)
def add_workflow_graph_node(
    workflow_id: str,
    request: WorkflowGraphNodeCreateRequest,
    service: Annotated[WorkflowGraphService, Depends(get_workflow_graph_service)],
) -> WorkflowGraph:
    try:
        return service.add_node(workflow_id, request)
    except WorkflowGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{workflow_id}/nodes/{node_id}", response_model=WorkflowGraph)
def patch_workflow_graph_node(
    workflow_id: str,
    node_id: str,
    request: WorkflowGraphNodePatchRequest,
    service: Annotated[WorkflowGraphService, Depends(get_workflow_graph_service)],
) -> WorkflowGraph:
    try:
        return service.patch_node(workflow_id, node_id, request)
    except WorkflowGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{workflow_id}/nodes/{node_id}", response_model=WorkflowGraph)
def delete_workflow_graph_node(
    workflow_id: str,
    node_id: str,
    service: Annotated[WorkflowGraphService, Depends(get_workflow_graph_service)],
) -> WorkflowGraph:
    try:
        return service.delete_node(workflow_id, node_id)
    except WorkflowGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{workflow_id}/edges", response_model=WorkflowGraphEdgeMutationResponse)
def add_workflow_graph_edge(
    workflow_id: str,
    request: WorkflowGraphEdgeCreateRequest,
    service: Annotated[WorkflowGraphService, Depends(get_workflow_graph_service)],
) -> WorkflowGraphEdgeMutationResponse:
    try:
        return service.add_edge(workflow_id, request)
    except WorkflowGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{workflow_id}/edges/{edge_id}", response_model=WorkflowGraphEdgeMutationResponse)
def patch_workflow_graph_edge(
    workflow_id: str,
    edge_id: str,
    request: WorkflowGraphEdgePatchRequest,
    service: Annotated[WorkflowGraphService, Depends(get_workflow_graph_service)],
) -> WorkflowGraphEdgeMutationResponse:
    try:
        return service.patch_edge(workflow_id, edge_id, request)
    except WorkflowGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{workflow_id}/edges/{edge_id}", response_model=WorkflowGraphEdgeDeleteResponse)
def delete_workflow_graph_edge(
    workflow_id: str,
    edge_id: str,
    service: Annotated[WorkflowGraphService, Depends(get_workflow_graph_service)],
) -> WorkflowGraphEdgeDeleteResponse:
    try:
        return service.delete_edge(workflow_id, edge_id)
    except WorkflowGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{workflow_id}/nodes/{node_id}/versions", response_model=WorkflowNodeVersionsResponse)
def get_workflow_graph_node_versions(
    workflow_id: str,
    node_id: str,
    service: Annotated[WorkflowGraphService, Depends(get_workflow_graph_service)],
) -> WorkflowNodeVersionsResponse:
    try:
        return service.node_versions(workflow_id, node_id)
    except WorkflowGraphError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{workflow_id}/nodes/{node_id}/lock", response_model=WorkflowGraph)
def lock_workflow_graph_node(
    workflow_id: str,
    node_id: str,
    service: Annotated[WorkflowGraphService, Depends(get_workflow_graph_service)],
) -> WorkflowGraph:
    try:
        return service.lock_node(workflow_id, node_id)
    except WorkflowGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{workflow_id}/nodes/{node_id}/unlock", response_model=WorkflowGraph)
def unlock_workflow_graph_node(
    workflow_id: str,
    node_id: str,
    service: Annotated[WorkflowGraphService, Depends(get_workflow_graph_service)],
) -> WorkflowGraph:
    try:
        return service.unlock_node(workflow_id, node_id)
    except WorkflowGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{workflow_id}/mark-stale", response_model=WorkflowGraph)
def mark_workflow_graph_stale(
    workflow_id: str,
    request: MarkStaleRequest,
    service: Annotated[WorkflowGraphService, Depends(get_workflow_graph_service)],
) -> WorkflowGraph:
    try:
        return service.mark_stale(workflow_id, request)
    except WorkflowGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
