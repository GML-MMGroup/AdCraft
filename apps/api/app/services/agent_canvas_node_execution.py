"""Node-type dispatch boundary for Agent Canvas runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from app.core.config import Settings
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_runtime import (
    AgentRunCompletedPayload,
    AgentRunContext,
    AgentRunPolicy,
    AgentRunRequest,
)
from app.schemas.agent_canvas import CanvasNodeV2, ResolvedInputSnapshotV2
from app.schemas.agent_canvas_ad_media import (
    AdReferenceBundleV2,
    CompiledProviderPromptV2,
)
from app.schemas.workflow_v2 import V2ProviderResult
from app.services.pi_agent_runtime_client import PiAgentRuntimeClient


@dataclass(frozen=True, slots=True)
class GeneratedMediaPayload:
    content: bytes
    mime_type: str
    filename: str


@dataclass(frozen=True, slots=True)
class NodeExecutionContext:
    execution_id: str
    node: CanvasNodeV2
    inputs: tuple[ResolvedInputSnapshotV2 | object, ...]
    model_id: str | None = None
    compiled_prompt: CompiledProviderPromptV2 | None = None
    reference_bundle: AdReferenceBundleV2 | None = None


@dataclass(frozen=True, slots=True)
class NodeExecutionOutcome:
    structured_content: dict[str, object] | None = None
    media: GeneratedMediaPayload | None = None
    provider_task_id: str | None = None
    remote_task_id: str | None = None
    provider: str | None = None
    result_descriptor: dict[str, object] | None = None


NodeExecutor = Callable[[NodeExecutionContext], NodeExecutionOutcome]


class _PiClient(Protocol):
    def run(self, request: AgentRunRequest): ...


class _MinimalProviderExecutor(Protocol):
    def execute_minimal(
        self,
        *,
        workflow_id: str,
        slot_type: str,
        media_type: str,
        provider_payload: dict[str, Any],
    ) -> V2ProviderResult: ...


class ScriptNodeExecutor:
    """Execute one saved Script draft through the isolated Pi Script Writer."""

    def __init__(self, client: _PiClient, *, timeout_seconds: float) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    def __call__(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        run_id = f"arun_{uuid4().hex}"
        request = AgentRunRequest(
            run_id=run_id,
            request_id=f"request_{uuid4().hex}",
            agent_name="script_writer",
            operation="execute_canvas_script",
            deadline_at=datetime.now(timezone.utc) + timedelta(seconds=self._timeout_seconds),
            model_policy_id="script_writer.execute_canvas_script.v1",
            context=AgentRunContext(
                operation="execute_canvas_script",
                user_input=_saved_prompt(context),
                workflow_id=context.node.workflow_id,
                target=None,
                input_payload={"resolved_inputs": [_json_input(item) for item in context.inputs]},
            ),
            policy=AgentRunPolicy(
                max_handoffs=0,
                timeout_seconds=self._timeout_seconds,
            ),
            contract_name="AgentCanvasScriptOutput",
            contract_schema={
                "type": "object",
                "additionalProperties": True,
                "required": ["content"],
                "properties": {"content": {"type": "string", "minLength": 1}},
            },
            audit_metadata={"tool_mode": "structured_only"},
        )
        outcome = self._client.run(request)
        terminal = outcome.terminal_event
        if terminal.event_type != "run_completed":
            raise _error(
                str(terminal.payload.get("code") or "script_execution_failed"),
                str(terminal.payload.get("message") or "Script execution failed."),
            )
        completed = AgentRunCompletedPayload.model_validate(terminal.payload)
        content = completed.value.get("content")
        if not isinstance(content, str) or not content.strip():
            raise _error(
                "script_provider_output_invalid",
                "Script Writer output did not include content.",
            )
        return NodeExecutionOutcome(structured_content=dict(completed.value))


class MediaNodeExecutor:
    """Adapt node-native media requests to the existing provider boundary."""

    def __init__(
        self,
        provider: _MinimalProviderExecutor,
        *,
        data_dir: Path,
    ) -> None:
        self._provider = provider
        self._data_dir = data_dir.resolve()

    def __call__(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        media_type = context.node.node_type
        if media_type not in {"image", "video", "audio"}:
            raise _error("node_not_runnable", "Node type cannot use a media executor.")
        prompt = _saved_prompt(context)
        provider_payload: dict[str, Any] = {
            "provider_prompt": prompt,
            "prompt": prompt,
            "node_id": context.node.node_id,
            "semantic_role": context.node.semantic_role,
            "model_id": context.model_id,
            **context.node.parameters,
        }
        if context.reference_bundle is not None:
            provider_payload["reference_assets"] = [
                {
                    "asset_id": reference.asset_id,
                    "media_type": reference.media_type,
                    "media_url": reference.access_descriptor.media_url,
                    "checksum": reference.access_descriptor.checksum,
                }
                for reference in context.reference_bundle.references
            ]
            provider_payload["reference_asset_ids"] = [
                reference.asset_id for reference in context.reference_bundle.references
            ]
        result = self._provider.execute_minimal(
            workflow_id=context.node.workflow_id,
            slot_type=context.node.semantic_role,
            media_type=media_type,
            provider_payload=provider_payload,
        )
        if result.status == "completed":
            content = result.asset_bytes
            if content is None and result.local_file_path:
                content = self._read_provider_file(result.local_file_path)
            if content is None:
                raise _error(
                    "provider_output_missing",
                    "Provider result did not include media content.",
                )
            mime_type, filename = {
                "image": ("image/png", "image.png"),
                "video": ("video/mp4", "video.mp4"),
                "audio": ("audio/mpeg", "audio.mp3"),
            }[media_type]
            return NodeExecutionOutcome(
                media=GeneratedMediaPayload(
                    content=content,
                    mime_type=mime_type,
                    filename=filename,
                ),
                provider=result.provider,
                remote_task_id=result.remote_task_id,
                result_descriptor=dict(result.metadata),
            )
        if result.status == "waiting" and result.remote_task_id:
            task_digest = hashlib.sha256(
                f"{context.execution_id}:{context.node.node_id}:{result.remote_task_id}".encode()
            ).hexdigest()[:24]
            return NodeExecutionOutcome(
                provider_task_id=f"task_{task_digest}",
                remote_task_id=result.remote_task_id,
                provider=result.provider,
                result_descriptor={
                    "media_type": media_type,
                    "provider": result.provider,
                    "provider_model": result.provider_model,
                    "provider_payload": result.provider_payload_snapshot,
                    **result.metadata,
                },
            )
        raise _error(
            result.error_code or "provider_generation_failed",
            result.error_message or "Provider generation failed.",
        )

    def _read_provider_file(self, value: str) -> bytes:
        candidate = Path(value)
        path = candidate if candidate.is_absolute() else self._data_dir / candidate
        resolved = path.resolve()
        if not resolved.is_relative_to(self._data_dir) or not resolved.is_file():
            raise _error(
                "provider_output_invalid",
                "Provider output path is outside managed storage.",
            )
        return resolved.read_bytes()


class NodeExecutionDispatcher:
    """Dispatch only runnable node types without prompt rewriting."""

    def __init__(
        self,
        *,
        script_executor: NodeExecutor | None = None,
        image_executor: NodeExecutor | None = None,
        video_executor: NodeExecutor | None = None,
        audio_executor: NodeExecutor | None = None,
    ) -> None:
        self._executors = {
            "script": script_executor,
            "image": image_executor,
            "video": video_executor,
            "audio": audio_executor,
        }

    def execute(self, context: NodeExecutionContext) -> NodeExecutionOutcome:
        if context.node.node_type not in self._executors:
            raise _error("node_not_runnable", "Node type cannot be run.")
        executor = self._executors[context.node.node_type]
        if executor is None:
            raise _error(
                "node_executor_unavailable",
                "The configured node executor is unavailable.",
            )
        return executor(context)


def build_default_node_dispatcher(
    settings: Settings,
    *,
    provider_executor: _MinimalProviderExecutor | None = None,
) -> NodeExecutionDispatcher:
    """Build deterministic fakes or configured node-native provider adapters."""

    if settings.agent_runtime_mode == "fake" or settings.media_mode == "mock":

        def fake_script(context: NodeExecutionContext) -> NodeExecutionOutcome:
            return NodeExecutionOutcome(
                structured_content={
                    "content": context.node.generation_prompt
                    or context.node.summary_prompt
                    or context.node.title
                }
            )

        def fake_media(context: NodeExecutionContext) -> NodeExecutionOutcome:
            prompt = (
                context.compiled_prompt.prompt
                if context.compiled_prompt is not None
                else context.node.generation_prompt
            )
            seed = hashlib.sha256(
                (f"{context.node.node_type}:{prompt}:{context.model_id}").encode()
            ).digest()
            mime_type, filename, signature = {
                "image": ("image/png", "image.png", b"\x89PNG\r\n\x1a\n"),
                "video": ("video/mp4", "video.mp4", b"\x00\x00\x00\x18ftypmp42"),
                "audio": ("audio/mpeg", "audio.mp3", b"ID3\x04\x00\x00"),
            }[context.node.node_type]
            return NodeExecutionOutcome(
                media=GeneratedMediaPayload(
                    content=signature + b"ADCRAFT_FAKE_MEDIA\n" + seed,
                    mime_type=mime_type,
                    filename=filename,
                )
            )

        return NodeExecutionDispatcher(
            script_executor=fake_script,
            image_executor=fake_media,
            video_executor=fake_media,
            audio_executor=fake_media,
        )

    media = MediaNodeExecutor(
        provider_executor or _default_provider_executor(settings),
        data_dir=settings.media_data_dir,
    )

    def unavailable(_: NodeExecutionContext) -> NodeExecutionOutcome:
        raise _error(
            "node_executor_unavailable",
            "Agent Canvas Script Writer runtime is not configured.",
        )

    return NodeExecutionDispatcher(
        script_executor=(
            ScriptNodeExecutor(
                PiAgentRuntimeClient(
                    base_url=settings.agent_runtime_base_url,
                    internal_token=settings.agent_runtime_internal_token,
                    protocol_version=settings.agent_runtime_protocol_version,
                    connect_timeout_seconds=settings.agent_runtime_connect_timeout_seconds,
                    read_timeout_seconds=settings.agent_runtime_read_timeout_seconds,
                    run_timeout_seconds=settings.agent_runtime_run_timeout_seconds,
                    max_event_bytes=settings.agent_runtime_max_event_bytes,
                    max_stream_bytes=settings.agent_runtime_max_stream_bytes,
                ),
                timeout_seconds=settings.agent_runtime_run_timeout_seconds,
            )
            if settings.agent_runtime_internal_token
            else unavailable
        ),
        image_executor=media,
        video_executor=media,
        audio_executor=media,
    )


def _default_provider_executor(settings: Settings) -> _MinimalProviderExecutor:
    from app.services.v2_provider_executor import V2ProviderExecutor

    return V2ProviderExecutor(settings=settings, data_dir=settings.media_data_dir)


def _saved_prompt(context: NodeExecutionContext) -> str:
    prompt = (
        context.compiled_prompt.prompt
        if context.compiled_prompt is not None
        else context.node.generation_prompt
    )
    return str(prompt or context.node.summary_prompt or context.node.title).strip()


def _json_input(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_node_execution")
