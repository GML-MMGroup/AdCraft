"""Capability-checked Python authority for Pi Agent tools."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import Settings
from app.persistence.agent_run_repository import (
    AgentRunRepository,
    AgentRunRepositoryError,
)
from app.schemas.agent_runtime import AgentToolCall, AgentToolResult
from app.schemas.workflow_v2 import (
    WorkflowV2ChatActionTarget,
    WorkflowV2FreeNodeGenerateRequest,
)
from app.services.v2_agent_target_resolver import (
    V2AgentTargetResolutionError,
    V2AgentTargetResolver,
)
from app.services.v2_asset_locator import V2AssetLocatorError, V2AssetLocatorResolver
from app.services.workflow_v2 import WorkflowV2Error, WorkflowV2Service


_ALL_AGENTS = frozenset(
    {
        "front_desk",
        "script_writer",
        "product_designer",
        "character_designer",
        "scene_designer",
        "storyboard_artist",
        "video_director",
        "bgm_director",
        "quick_media_agent",
    }
)
_SPECIALIST_AGENTS = _ALL_AGENTS - {"front_desk"}
_MEDIA_AGENTS = _SPECIALIST_AGENTS - {"script_writer"}
_READ_OPERATIONS = frozenset(
    {
        "workflow_creation",
        "intent_contract_planner",
        "expert_brief_planner",
        "script_writer",
        "script_edit_normalization",
        "targeted_revision",
        "product_prompt",
        "product_revision",
        "character_prompt",
        "character_revision",
        "scene_prompt",
        "scene_revision",
        "visual_style_scope_repair",
        "storyboard_detail",
        "storyboard_prompt",
        "shot_video_prompt",
        "bgm_prompt",
        "free_image",
        "free_video",
        "free_audio",
    }
)


class AgentToolDomain(Protocol):
    def current_revision(self, workflow_id: str) -> int: ...

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AgentToolCapability:
    allowed_agents: frozenset[str]
    allowed_operations: frozenset[str]
    read_only: bool
    requires_target: bool
    requires_expected_revision: bool
    supports_idempotency: bool


_CAPABILITIES = {
    "list_canvas_targets": AgentToolCapability(
        _ALL_AGENTS, _READ_OPERATIONS, True, False, False, False
    ),
    "resolve_canvas_target": AgentToolCapability(
        _ALL_AGENTS, _READ_OPERATIONS, True, False, False, False
    ),
    "read_target_context": AgentToolCapability(
        _ALL_AGENTS, _READ_OPERATIONS, True, True, False, False
    ),
    "save_prompt_revision": AgentToolCapability(
        _SPECIALIST_AGENTS, _READ_OPERATIONS, False, True, True, True
    ),
    "start_slot_generation": AgentToolCapability(
        _MEDIA_AGENTS, _READ_OPERATIONS, False, True, True, True
    ),
    "start_free_media_generation": AgentToolCapability(
        frozenset({"quick_media_agent"}),
        frozenset({"free_image", "free_video", "free_audio"}),
        False,
        True,
        True,
        True,
    ),
    "select_asset_version": AgentToolCapability(
        _MEDIA_AGENTS, _READ_OPERATIONS, False, True, True, True
    ),
    "discard_working_version": AgentToolCapability(
        _MEDIA_AGENTS, _READ_OPERATIONS, False, True, True, True
    ),
}
_ASYNC_TOOLS = {"start_slot_generation", "start_free_media_generation"}


class _ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(min_length=1, max_length=160)


class _ListCanvasTargetsArguments(_ToolArguments):
    pass


class _ResolveCanvasTargetArguments(_ToolArguments):
    target_locator: str | None = Field(default=None, min_length=1, max_length=320)
    query: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def require_one_selector(self) -> _ResolveCanvasTargetArguments:
        if bool(self.target_locator) == bool(self.query):
            raise ValueError("Provide exactly one target locator or query.")
        return self


class _ReadTargetContextArguments(_ToolArguments):
    target_locator: str = Field(min_length=1, max_length=320)


class _SavePromptRevisionArguments(_ToolArguments):
    target_locator: str = Field(min_length=1, max_length=320)
    instruction: str = Field(min_length=1, max_length=4_000)
    prompt_scope: Literal["auto", "item", "slot"] = "auto"


class _StartSlotGenerationArguments(_ToolArguments):
    slot_id: str = Field(min_length=1, max_length=240)


class _StartFreeMediaGenerationArguments(_ToolArguments):
    node_id: str = Field(min_length=1, max_length=240)
    output_media_type: Literal["image", "video", "audio"]


class _SelectAssetVersionArguments(_ToolArguments):
    slot_id: str = Field(min_length=1, max_length=240)
    version_id: str = Field(min_length=1, max_length=240)


class _DiscardWorkingVersionArguments(_ToolArguments):
    slot_id: str = Field(min_length=1, max_length=240)


_ARGUMENT_MODELS: dict[str, type[_ToolArguments]] = {
    "list_canvas_targets": _ListCanvasTargetsArguments,
    "resolve_canvas_target": _ResolveCanvasTargetArguments,
    "read_target_context": _ReadTargetContextArguments,
    "save_prompt_revision": _SavePromptRevisionArguments,
    "start_slot_generation": _StartSlotGenerationArguments,
    "start_free_media_generation": _StartFreeMediaGenerationArguments,
    "select_asset_version": _SelectAssetVersionArguments,
    "discard_working_version": _DiscardWorkingVersionArguments,
}


class AgentToolDomainError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WorkflowV2AgentToolDomain:
    """Thin adapter from canonical Agent tools to existing V2 services."""

    def __init__(self, settings: Settings) -> None:
        self._service = WorkflowV2Service(settings)
        self._locator = V2AssetLocatorResolver(settings.media_data_dir)
        self._target_resolver = V2AgentTargetResolver(settings)

    def current_revision(self, workflow_id: str) -> int:
        workflow = self._service.get_workflow(workflow_id)
        if workflow.state_version is None:
            raise AgentToolDomainError(
                "agent_target_revision_unavailable",
                "Workflow state version is unavailable.",
            )
        return workflow.state_version

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if tool_name == "list_canvas_targets":
                return self._list_canvas_targets(arguments["workflow_id"])
            if tool_name == "resolve_canvas_target":
                return self._resolve_canvas_target(arguments)
            if tool_name == "read_target_context":
                return self._read_target_context(arguments)
            if tool_name == "save_prompt_revision":
                return self._save_prompt_revision(arguments)
            if tool_name == "start_slot_generation":
                return self._start_slot_generation(arguments)
            if tool_name == "start_free_media_generation":
                return self._start_free_media_generation(arguments)
            if tool_name == "select_asset_version":
                workflow = self._service.select_slot_version(
                    arguments["workflow_id"],
                    arguments["slot_id"],
                    arguments["version_id"],
                )
                return _workflow_mutation_result(workflow)
            if tool_name == "discard_working_version":
                workflow = self._service.discard_working_version(
                    arguments["workflow_id"],
                    arguments["slot_id"],
                )
                return _workflow_mutation_result(workflow)
        except (WorkflowV2Error, V2AssetLocatorError) as error:
            raise AgentToolDomainError(
                getattr(error, "code", "agent_tool_execution_failed"),
                str(error),
            ) from error
        raise AgentToolDomainError(
            "agent_tool_not_allowed",
            "Agent tool is not implemented by the V2 domain adapter.",
        )

    def _list_canvas_targets(self, workflow_id: str) -> dict[str, Any]:
        try:
            return self._target_resolver.list_active_targets(workflow_id).model_dump(mode="json")
        except V2AgentTargetResolutionError as error:
            raise AgentToolDomainError(error.code, error.message) from error

    def _resolve_canvas_target(self, arguments: dict[str, Any]) -> dict[str, Any]:
        workflow_id = arguments["workflow_id"]
        locator = arguments.get("target_locator")
        if not locator:
            query = str(arguments["query"]).casefold()
            candidates = [
                target
                for target in self._list_canvas_targets(workflow_id)["targets"]
                if query in str(target["display_name"]).casefold()
                or query in str(target["item_id"]).casefold()
            ]
            if len(candidates) != 1:
                raise AgentToolDomainError(
                    "agent_target_clarification_required",
                    "The canvas target is not unambiguous.",
                )
            return candidates[0]
        try:
            return self._target_resolver.resolve(
                workflow_id,
                WorkflowV2ChatActionTarget(target_type="node", locator=locator),
            ).model_dump(mode="json")
        except V2AgentTargetResolutionError as error:
            raise AgentToolDomainError(error.code, error.message) from error

    def _read_target_context(self, arguments: dict[str, Any]) -> dict[str, Any]:
        resolved = self._resolve_canvas_target(arguments)
        workflow = self._service.get_workflow(arguments["workflow_id"])
        item = _find_item(workflow, resolved.get("item_id"))
        slot = _find_slot(workflow, resolved.get("slot_id"))
        return {
            "workflow_id": workflow.workflow_id,
            "state_version": workflow.state_version,
            "target": resolved,
            "current_prompt": slot.slot_prompt if slot else item.item_prompt if item else None,
            "selected_asset_id": slot.selected_asset_id if slot else None,
            "selected_version_id": slot.selected_version_id if slot else None,
        }

    def _save_prompt_revision(self, arguments: dict[str, Any]) -> dict[str, Any]:
        workflow_id = arguments["workflow_id"]
        locator = arguments["target_locator"]
        kind, value = _split_locator(locator)
        if kind == "item":
            workflow = self._service.update_item_prompt(
                workflow_id,
                value,
                item_prompt=arguments["instruction"],
            )
            item = _find_item(workflow, value)
            affected_slot_ids = [slot.slot_id for slot in item.slots] if item else []
        else:
            if kind == "asset":
                resolved = self._locator.resolve(workflow_id, locator)
                slot_id = resolved.owner_slot_id
            elif kind == "slot":
                slot_id = value
            else:
                raise AgentToolDomainError(
                    "clarification_required",
                    "Prompt revisions require one item, slot, or selected asset target.",
                )
            if not slot_id:
                raise AgentToolDomainError("target_not_found", "Target slot was not found.")
            workflow = self._service.update_slot_prompt(
                workflow_id,
                slot_id,
                slot_prompt=arguments["instruction"],
            )
            affected_slot_ids = [slot_id]
        return {
            **_workflow_mutation_result(workflow),
            "affected_slot_ids": affected_slot_ids,
            "target_locator": locator,
        }

    def _start_slot_generation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self._service.generate_slot(
            arguments["workflow_id"],
            arguments["slot_id"],
        )
        return _generation_result(response, slot_id=arguments["slot_id"])

    def _start_free_media_generation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self._service.generate_free_node(
            arguments["workflow_id"],
            arguments["node_id"],
            WorkflowV2FreeNodeGenerateRequest(output_media_type=arguments["output_media_type"]),
        )
        return _generation_result(response, node_id=arguments["node_id"])


class V2AgentToolGateway:
    """Validate a Pi capability before delegating to existing domain services."""

    def __init__(
        self,
        *,
        repository: AgentRunRepository,
        domain: AgentToolDomain,
    ) -> None:
        self._repository = repository
        self._domain = domain

    def execute(self, call: AgentToolCall) -> AgentToolResult:
        try:
            run = self._repository.load(call.run_id)
        except AgentRunRepositoryError as error:
            return _rejected(call, error.code, error.message)
        capability = _CAPABILITIES.get(call.tool_name)
        if (
            capability is None
            or run.agent_name not in capability.allowed_agents
            or run.operation not in capability.allowed_operations
        ):
            return _rejected(
                call,
                "agent_tool_not_allowed",
                "Agent tool is not available for this operation.",
            )

        argument_model = _ARGUMENT_MODELS.get(call.tool_name)
        if argument_model is None:
            return _rejected(
                call,
                "agent_tool_not_allowed",
                "Agent tool is not available for this operation.",
            )
        try:
            _reject_unsafe_argument_values(call.arguments)
            arguments = argument_model.model_validate(call.arguments).model_dump(
                mode="json",
                exclude_none=True,
            )
        except (ValidationError, ValueError):
            return _rejected(
                call,
                "agent_tool_arguments_invalid",
                "Agent tool arguments are invalid.",
            )

        digest = _request_digest(call)
        existing = run.tool_results.get(call.idempotency_key)
        if existing is not None:
            if existing.get("request_digest") != digest:
                return _rejected(
                    call,
                    "agent_tool_idempotency_conflict",
                    "Agent tool idempotency key was reused with different input.",
                )
            return AgentToolResult.model_validate(existing["result"])

        workflow_id = arguments.get("workflow_id")
        if not isinstance(workflow_id, str) or not workflow_id:
            return _rejected(
                call,
                "agent_tool_arguments_invalid",
                "Tool arguments require workflow_id.",
            )
        if capability.requires_expected_revision:
            if call.expected_revision is None:
                return _rejected(
                    call,
                    "agent_target_revision_conflict",
                    "Mutation tool requires the expected target revision.",
                )
            current_revision = self._domain.current_revision(workflow_id)
            if call.expected_revision != current_revision:
                return AgentToolResult(
                    run_id=call.run_id,
                    tool_call_id=call.tool_call_id,
                    status="rejected",
                    result={"current_revision": current_revision},
                    error_code="agent_target_revision_conflict",
                    error_message="The target changed while the Agent was reasoning.",
                )

        try:
            payload = self._domain.execute(call.tool_name, arguments)
            result = AgentToolResult(
                run_id=call.run_id,
                tool_call_id=call.tool_call_id,
                status=(
                    "accepted"
                    if call.tool_name in _ASYNC_TOOLS
                    and (payload.get("execution_id") or payload.get("provider_task_id"))
                    else "completed"
                ),
                result=payload,
            )
            if capability.supports_idempotency:
                stored = self._repository.store_tool_result(
                    call.run_id,
                    lease_owner_id=run.lease_owner_id or "",
                    idempotency_key=call.idempotency_key,
                    request_digest=digest,
                    result=result.model_dump(mode="json"),
                )
                return AgentToolResult.model_validate(stored)
            return result
        except AgentRunRepositoryError as error:
            return _rejected(call, error.code, error.message)
        except AgentToolDomainError as error:
            return _rejected(call, error.code, error.message)
        except Exception:
            return AgentToolResult(
                run_id=call.run_id,
                tool_call_id=call.tool_call_id,
                status="failed",
                error_code="agent_tool_execution_failed",
                error_message="Agent tool execution failed.",
            )


def capability_matrix() -> dict[str, AgentToolCapability]:
    """Return the immutable capability declarations for tests and adapters."""

    return dict(_CAPABILITIES)


def _request_digest(call: AgentToolCall) -> str:
    payload = {
        "tool_name": call.tool_name,
        "arguments": call.arguments,
        "expected_revision": call.expected_revision,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reject_unsafe_argument_values(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered_key = str(key).casefold()
            if lowered_key.endswith("url") or lowered_key.endswith("_url"):
                raise ValueError("Remote URLs are not accepted from Agent tools.")
            _reject_unsafe_argument_values(child)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _reject_unsafe_argument_values(child)
        return
    if isinstance(value, str):
        lowered = value.casefold()
        if lowered.startswith(("http://", "https://", "data:")) or ";base64," in lowered:
            raise ValueError("Raw media and remote URLs are not accepted from Agent tools.")


def _workflow_mutation_result(workflow: Any) -> dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "state_version": workflow.state_version,
        "semantic_revision_no": workflow.semantic_revision_no,
    }


def _generation_result(
    response: Any,
    *,
    slot_id: str | None = None,
    node_id: str | None = None,
) -> dict[str, Any]:
    summaries = [summary.model_dump(mode="json") for summary in response.provider_call_summaries]
    provider_task_id = next(
        (
            summary.get("provider_task_id")
            for summary in summaries
            if summary.get("provider_task_id")
        ),
        None,
    )
    execution_id = response.execution_id or provider_task_id
    return {
        "workflow_id": response.workflow.workflow_id,
        "state_version": response.workflow.state_version,
        "execution_id": execution_id,
        "provider_task_id": provider_task_id,
        "slot_id": slot_id,
        "node_id": node_id,
        "executed_slot_ids": response.executed_slot_ids,
        "provider_calls": summaries,
    }


def _find_item(workflow: Any, item_id: str | None) -> Any | None:
    if not item_id:
        return None
    return next(
        (item for node in workflow.nodes for item in node.items if item.item_id == item_id),
        None,
    )


def _find_slot(workflow: Any, slot_id: str | None) -> Any | None:
    if not slot_id:
        return None
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


def _split_locator(locator: str) -> tuple[str, str]:
    if ":" not in locator:
        raise AgentToolDomainError("invalid_locator", "Target locator is invalid.")
    kind, value = locator.split(":", 1)
    if kind not in {"node", "item", "slot", "asset"} or not value:
        raise AgentToolDomainError("invalid_locator", "Target locator is invalid.")
    return kind, value


def _rejected(
    call: AgentToolCall,
    code: str,
    message: str,
) -> AgentToolResult:
    return AgentToolResult(
        run_id=call.run_id,
        tool_call_id=call.tool_call_id,
        status="rejected",
        error_code=code,
        error_message=message,
    )
