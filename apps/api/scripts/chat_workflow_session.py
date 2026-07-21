# ruff: noqa: E402
import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings
from app.schemas.ad_workflow import AdWorkflowGenerateRequest, AdWorkflowResponse
from app.schemas.assets import WorkflowAssetReference
from app.schemas.chat_workflow_stream import ChatWorkflowRunCreateRequest
from app.schemas.front_desk import ChatMessage, FrontDeskChatRequest, FrontDeskChatResponse
from app.services.ad_workflow import AdWorkflowService
from app.services.chat_workflow_stream import ChatWorkflowStreamService
from app.services.front_desk import FrontDeskService
from scripts.run_chat_workflow import _print_stream_event
from app.services.media_tasks import MediaTaskPollResult, MediaTaskService


@dataclass(frozen=True)
class SessionOptions:
    settings: Settings
    skip_audio_agents: bool = False
    wait_media: bool = False
    download_media: bool = False
    compose_when_ready: bool = False
    interval_seconds: int = 10
    max_attempts: int = 60
    json_output: bool = False
    selected_asset_ids: tuple[str, ...] = ()
    show_planning_events: bool = False


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive front-desk to ad workflow CLI.")
    parser.add_argument("--mock", action="store_true", help="Shortcut for all mock modes.")
    parser.add_argument("--agent-mode", choices=["mock", "real"], default=None)
    parser.add_argument("--media-mode", choices=["mock", "real"], default=None)
    parser.add_argument("--skip-audio-agents", action="store_true")
    parser.add_argument("--wait-media", action="store_true")
    parser.add_argument("--download-media", action="store_true")
    parser.add_argument("--compose-when-ready", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=10)
    parser.add_argument("--max-attempts", type=int, default=60)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--show-planning-events",
        "--stream-planning",
        dest="show_planning_events",
        action="store_true",
        help="Print chat-style workflow planning events before any execution path.",
    )
    parser.add_argument(
        "--asset-id",
        "--selected-asset",
        dest="selected_asset_ids",
        action="append",
        default=[],
        help="Use an uploaded asset_id as workflow selected_assets.",
    )
    return parser.parse_args(argv)


def _build_settings(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    agent_mode = args.agent_mode
    media_mode = args.media_mode
    if args.mock:
        agent_mode = agent_mode or "mock"
        media_mode = media_mode or "mock"
    if agent_mode == "mock":
        settings = replace(settings, agno_mock_mode=True)
    elif agent_mode == "real":
        settings = replace(settings, agno_mock_mode=False)
    if media_mode is not None:
        settings = replace(settings, media_mode=media_mode)
    if args.skip_audio_agents:
        settings = replace(settings, skip_audio_agents=True)
    return settings


def run_interactive_session(
    *,
    options: SessionOptions,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
    front_desk_service: Any | None = None,
    ad_workflow_service: Any | None = None,
    media_task_service: Any | None = None,
) -> int:
    settings = options.settings
    front_desk = front_desk_service or FrontDeskService(settings)
    workflow_service = ad_workflow_service or AdWorkflowService(settings)
    media_tasks = media_task_service or MediaTaskService(settings)
    history: list[ChatMessage] = []
    final_payload: dict[str, Any] = {}

    while True:
        try:
            user_message = input_func("User> ").strip()
        except (EOFError, StopIteration):
            return 0
        if not user_message:
            continue
        if user_message.lower() in {"exit", "quit"}:
            output_func("Session> exit")
            return 0

        if options.show_planning_events:
            stream_request = ChatWorkflowRunCreateRequest(
                message=user_message,
                history=history,
                skip_audio_agents=options.skip_audio_agents,
                audio_mode="none" if options.skip_audio_agents else None,
                selected_assets=_load_selected_assets(settings, options.selected_asset_ids),
            )
            stream_service = ChatWorkflowStreamService(settings, front_desk_service=front_desk)
            assistant_reply = ""
            workflow_generated = False
            for event in stream_service.stream_plan_events(stream_request):
                _print_stream_event(event, output_func=output_func)
                if event.event == "front_desk_reply":
                    assistant_reply = str(event.data.get("reply") or "")
                    final_payload["front_desk"] = event.data
                elif event.event == "workflow_generated":
                    final_payload["workflow"] = event.data.get("workflow")
                    workflow_generated = True
                elif event.event == "error":
                    return 1
            history.append(ChatMessage(role="user", content=user_message))
            if assistant_reply:
                history.append(ChatMessage(role="assistant", content=assistant_reply))
            if not workflow_generated:
                continue
            if options.json_output:
                output_func(json.dumps(final_payload, ensure_ascii=False, indent=2))
            return 0

        request = FrontDeskChatRequest(
            message=user_message,
            history=history,
            skip_audio_agents=options.skip_audio_agents,
        )
        try:
            front_desk_response = front_desk.chat(request)
        except Exception as exc:
            output_func(f"FrontDesk> failed: {exc}")
            return 1

        _print_front_desk(front_desk_response, output_func)
        history.append(ChatMessage(role="user", content=user_message))
        history.append(ChatMessage(role="assistant", content=front_desk_response.reply))
        final_payload["front_desk"] = front_desk_response.model_dump(mode="json")

        if not front_desk_response.should_start_workflow:
            continue
        if front_desk_response.ad_request is None:
            output_func("FrontDesk> invalid state: missing ad_request")
            return 1

        ad_request = _ad_request_with_session_options(
            front_desk_response.ad_request,
            options.skip_audio_agents,
            options.selected_asset_ids,
            settings,
        )
        output_func("FrontDesk> demand ready, starting workflow")
        try:
            workflow = workflow_service.generate(ad_request)
        except Exception as exc:
            output_func(f"Workflow> failed: {exc}")
            return 1

        final_payload["workflow"] = workflow.model_dump(mode="json")
        _print_workflow(workflow, settings, output_func)

        poll_result: MediaTaskPollResult | None = None
        if options.wait_media:
            try:
                poll_result = media_tasks.poll_until_all_segments_ready(
                    workflow.workflow_id,
                    interval_seconds=options.interval_seconds,
                    max_attempts=options.max_attempts,
                    download_media=options.download_media,
                    on_segment_update=lambda segment: _print_segment_status(segment, output_func),
                )
            except Exception as exc:
                output_func(f"Media> failed: {exc}")
                return 1
            for segment in poll_result.segments:
                _print_segment_status(segment, output_func)
            final_payload["media_poll"] = {
                "workflow_id": poll_result.workflow_id,
                "all_ready": poll_result.all_ready,
                "attempts": getattr(poll_result, "attempts", 0),
                "segments": poll_result.segments,
            }

        if options.compose_when_ready:
            try:
                final_asset = media_tasks.compose_when_ready(workflow.workflow_id)
            except Exception as exc:
                output_func(f"FFmpeg> failed: {exc}")
                return 1
            final_payload["final_composition"] = final_asset
            _print_final_asset(final_asset, settings, output_func)

        if options.json_output:
            output_func(json.dumps(final_payload, ensure_ascii=False, indent=2))
        return 0


def _ad_request_with_session_options(
    ad_request: AdWorkflowGenerateRequest,
    skip_audio_agents: bool,
    selected_asset_ids: tuple[str, ...],
    settings: Settings,
) -> AdWorkflowGenerateRequest:
    update: dict[str, Any] = {}
    if skip_audio_agents:
        update["skip_audio_agents"] = True
    if selected_asset_ids:
        selected_assets = list(ad_request.selected_assets) + _load_selected_assets(
            settings,
            selected_asset_ids,
        )
        update["selected_assets"] = selected_assets
    return ad_request.model_copy(update=update) if update else ad_request


def _load_selected_assets(
    settings: Settings,
    selected_asset_ids: tuple[str, ...],
) -> list[WorkflowAssetReference]:
    assets = []
    for asset_id in selected_asset_ids:
        matches = sorted((settings.media_data_dir / "assets").glob(f"*/*{asset_id}*/metadata.json"))
        if not matches:
            matches = sorted(
                (settings.media_data_dir / "assets").glob(f"*/{asset_id}/metadata.json")
            )
        if not matches:
            raise ValueError(f"Uploaded asset metadata not found for asset_id={asset_id}.")
        assets.append(
            WorkflowAssetReference.model_validate_json(matches[0].read_text(encoding="utf-8"))
        )
    return assets


def _print_front_desk(
    response: FrontDeskChatResponse,
    output_func: Callable[[str], None],
) -> None:
    output_func(f"FrontDesk> intent={response.intent}")
    output_func(f"FrontDesk> {response.reply}")
    output_func(f"FrontDesk> missing_fields={', '.join(response.missing_fields) or '-'}")


def _print_workflow(
    workflow: AdWorkflowResponse,
    settings: Settings,
    output_func: Callable[[str], None],
) -> None:
    output_func(f"Workflow> workflow_id={workflow.workflow_id}")
    output_func(
        f"Workflow> trace={(settings.media_data_dir / 'runs' / workflow.workflow_id / 'trace.json').as_posix()}"
    )
    for node in workflow.nodes:
        output_func(f"Workflow> {node.id} {node.status}")
        if node.id == "character-image-generation":
            _print_character_assets(node.content, settings, output_func)
        elif node.id == "storyboard-image-generation":
            _print_storyboard_images(node.content, settings, output_func)
        elif node.id == "storyboard-video-generation":
            segments = node.content.get("segments")
            if isinstance(segments, list):
                output_func(
                    f"Workflow> storyboard-video-generation submitted {len(segments)} tasks"
                )
                for segment in segments:
                    if isinstance(segment, dict):
                        _print_segment_status(segment, output_func)


def _print_character_assets(
    content: dict[str, Any],
    settings: Settings,
    output_func: Callable[[str], None],
) -> None:
    for asset in content.get("assets", []):
        if isinstance(asset, dict):
            output_func(
                "Character> "
                f"metadata={_display_path(settings, asset.get('metadata_path'))} "
                f"local={_display_path(settings, asset.get('local_path'))} "
                f"download_status={asset.get('download_status') or '-'}"
            )


def _print_storyboard_images(
    content: dict[str, Any],
    settings: Settings,
    output_func: Callable[[str], None],
) -> None:
    for asset in content.get("assets", []):
        if isinstance(asset, dict):
            output_func(
                "StoryboardImage> "
                f"scene={asset.get('order') or asset.get('scene')} "
                f"local={_display_path(settings, asset.get('local_path'))} "
                f"download_status={asset.get('download_status') or '-'}"
            )


def _print_segment_status(segment: dict[str, Any], output_func: Callable[[str], None]) -> None:
    output_func(
        "Media> "
        f"segment {segment.get('order')} "
        f"status={segment.get('status') or '-'} "
        f"download_status={segment.get('download_status') or '-'} "
        f"task_id={segment.get('task_id') or '-'} "
        f"query_url={segment.get('task_query_url') or '-'} "
        f"local_path={segment.get('local_path') or '-'}"
    )
    if segment.get("download_status") == "downloaded":
        output_func(f"Media> segment {segment.get('order')} downloaded")
    if str(segment.get("status") or "").lower() == "failed":
        output_func(
            f"Media> segment {segment.get('order')} failed: {segment.get('error') or segment.get('raw_response')}"
        )


def _print_final_asset(
    final_asset: dict[str, Any],
    settings: Settings,
    output_func: Callable[[str], None],
) -> None:
    status = final_asset.get("status")
    if status == "ready" and final_asset.get("local_path"):
        output_func("FFmpeg> final-ad-video.mp4 ready")
        output_func(f"FFmpeg> final_video={_display_path(settings, final_asset.get('local_path'))}")
    elif status == "waiting_for_segments":
        output_func("FFmpeg> waiting_for_segments")
    else:
        output_func(f"FFmpeg> status={status}")
    output_func(f"FFmpeg> metadata={_display_path(settings, final_asset.get('metadata_path'))}")


def _display_path(settings: Settings, local_path: object) -> str:
    if not isinstance(local_path, str) or not local_path:
        return "-"
    return (settings.media_data_dir / local_path).as_posix()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = _build_settings(args)
    return run_interactive_session(
        options=SessionOptions(
            settings=settings,
            skip_audio_agents=args.skip_audio_agents,
            wait_media=args.wait_media,
            download_media=args.download_media,
            compose_when_ready=args.compose_when_ready,
            interval_seconds=args.interval_seconds,
            max_attempts=args.max_attempts,
            json_output=args.json,
            selected_asset_ids=tuple(args.selected_asset_ids),
            show_planning_events=args.show_planning_events,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
