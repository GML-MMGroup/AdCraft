import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.schemas.ad_workflow import AdWorkflowGenerateRequest
from app.schemas.chat_workflow_stream import (
    ChatWorkflowRunCreateRequest,
    ChatWorkflowRunCreateResponse,
    ChatWorkflowStreamEvent,
)
from app.schemas.front_desk import FrontDeskChatResponse
from app.services.agent_trace import utc_now
from app.services.front_desk import FrontDeskError, FrontDeskService
from app.services.workflow_plan import create_workflow_plan


class ChatWorkflowRunError(RuntimeError):
    """Raised when a chat workflow planning run cannot be loaded."""


class ChatWorkflowStreamService:
    def __init__(
        self,
        settings: Settings,
        front_desk_service: FrontDeskService | None = None,
    ) -> None:
        self._settings = settings
        self._front_desk_service = front_desk_service or FrontDeskService(settings)

    def create_run(
        self,
        request: ChatWorkflowRunCreateRequest,
    ) -> ChatWorkflowRunCreateResponse:
        run_id = f"chatrun_{uuid4().hex[:12]}"
        payload = {
            "run_id": run_id,
            "status": "queued",
            "request": request.model_dump(mode="json"),
            "created_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat(),
        }
        self._write_run(run_id, payload)
        return ChatWorkflowRunCreateResponse(run_id=run_id)

    def stream_plan_events(
        self,
        request: ChatWorkflowRunCreateRequest,
        *,
        run_id: str | None = None,
        persist_run: bool = False,
    ) -> Iterator[ChatWorkflowStreamEvent]:
        run_id = run_id or f"chatrun_{uuid4().hex[:12]}"
        try:
            yield _event("run_started", {"run_id": run_id, "message": "开始处理广告需求"})
            self._update_run_if_persisted(run_id, persist_run, {"status": "running"})

            yield _event(
                "front_desk_started",
                {"run_id": run_id, "message": "正在理解广告需求"},
            )
            front_desk_response = self._front_desk_service.chat(request)
            yield _event("front_desk_reply", _front_desk_event(front_desk_response))

            if not front_desk_response.should_start_workflow:
                self._update_run_if_persisted(
                    run_id, persist_run, {"status": "needs_clarification"}
                )
                yield _event(
                    "clarification_required",
                    {
                        "reply": front_desk_response.reply,
                        "missing_fields": front_desk_response.missing_fields,
                    },
                )
                yield _event("done", {"run_id": run_id, "status": "needs_clarification"})
                return

            if front_desk_response.ad_request is None:
                raise ChatWorkflowRunError(
                    "invalid_front_desk_state: should_start_workflow=true but ad_request is missing"
                )

            yield _event(
                "workflow_planning_started",
                {"run_id": run_id, "message": "正在生成默认 workflow graph"},
            )
            ad_request = _apply_request_overrides(front_desk_response.ad_request, request)
            workflow = create_workflow_plan(ad_request, self._settings)

            for node in workflow.nodes:
                yield _event(
                    "workflow_node_planned",
                    {
                        "node_id": node.id,
                        "node_type": node.id,
                        "title": node.title,
                        "message": f"已创建{node.title}节点",
                    },
                )
            yield _event(
                "workflow_edges_started",
                {"workflow_id": workflow.workflow_id, "message": "正在创建节点连线"},
            )
            for edge in workflow.edges:
                yield _event(
                    "workflow_edge_planned",
                    {
                        "source": edge.source,
                        "target": edge.target,
                        "label": edge.label,
                        "message": f"已连接{edge.source}到{edge.target}",
                    },
                )

            yield _event(
                "workflow_graph_saved",
                {"workflow_id": workflow.workflow_id, "message": "工作流已保存"},
            )
            self._update_run_if_persisted(
                run_id,
                persist_run,
                {
                    "status": "completed",
                    "workflow_id": workflow.workflow_id,
                    "workflow": workflow.model_dump(mode="json"),
                },
            )
            yield _event(
                "workflow_generated",
                {
                    "workflow_id": workflow.workflow_id,
                    "workflow": workflow.model_dump(mode="json"),
                },
            )
            yield _event("done", {"run_id": run_id, "status": "completed"})
        except FrontDeskError as exc:
            yield from self._stream_error(run_id, f"front_desk_failed: {exc}", persist_run)
        except Exception as exc:
            yield from self._stream_error(run_id, str(exc), persist_run)

    def stream_run(self, run_id: str) -> Iterator[str]:
        payload = self._read_run(run_id)
        request = ChatWorkflowRunCreateRequest.model_validate(payload["request"])
        for event in self.stream_plan_events(request, run_id=run_id, persist_run=True):
            yield _sse(event)

    def _stream_error(
        self,
        run_id: str,
        message: str,
        persist_run: bool,
    ) -> Iterator[ChatWorkflowStreamEvent]:
        self._update_run_if_persisted(run_id, persist_run, {"status": "failed", "error": message})
        yield _event("error", {"run_id": run_id, "message": message})
        yield _event("done", {"run_id": run_id, "status": "failed"})

    def _run_path(self, run_id: str) -> Path:
        return self._settings.media_data_dir / "runs" / "chat" / f"{run_id}.json"

    def _write_run(self, run_id: str, payload: dict[str, Any]) -> None:
        path = self._run_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    def _read_run(self, run_id: str) -> dict[str, Any]:
        path = self._run_path(run_id)
        if not path.exists():
            raise ChatWorkflowRunError(f"chat workflow run not found: {run_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _update_run_if_persisted(
        self,
        run_id: str,
        persist_run: bool,
        updates: dict[str, Any],
    ) -> None:
        if not persist_run:
            return
        payload = self._read_run(run_id)
        payload.update(updates)
        payload["updated_at"] = utc_now().isoformat()
        self._write_run(run_id, payload)


def _event(event: str, data: dict[str, Any]) -> ChatWorkflowStreamEvent:
    return ChatWorkflowStreamEvent(event=event, data=data)


def _sse(stream_event: ChatWorkflowStreamEvent) -> str:
    return (
        f"event: {stream_event.event}\n"
        f"data: {json.dumps(stream_event.data, ensure_ascii=False, default=str)}\n\n"
    )


def _front_desk_event(response: FrontDeskChatResponse) -> dict[str, Any]:
    return {
        "intent": response.intent,
        "reply": response.reply,
        "missing_fields": response.missing_fields,
        "should_start_workflow": response.should_start_workflow,
    }


def _apply_request_overrides(
    ad_request: AdWorkflowGenerateRequest,
    request: ChatWorkflowRunCreateRequest,
) -> AdWorkflowGenerateRequest:
    updates: dict[str, Any] = {}
    if request.skip_audio_agents:
        updates["skip_audio_agents"] = True
        updates["audio_mode"] = "none"
    elif request.audio_mode is not None:
        updates["audio_mode"] = request.audio_mode
    if request.selected_assets:
        updates["selected_assets"] = [*ad_request.selected_assets, *request.selected_assets]
    return ad_request.model_copy(update=updates) if updates else ad_request
