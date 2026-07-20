# ruff: noqa: E402
import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings
from app.schemas.ad_workflow import AdWorkflowResponse
from app.schemas.assets import WorkflowAssetReference
from app.schemas.chat_workflow_stream import ChatWorkflowRunCreateRequest, ChatWorkflowStreamEvent
from app.schemas.front_desk import FrontDeskChatRequest
from app.services.chat_workflow import ChatWorkflowError, ChatWorkflowService
from app.services.chat_workflow_stream import ChatWorkflowStreamService
from app.tools.media import build_media_provider


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the natural-language ad workflow orchestration without HTTP.",
    )
    parser.add_argument("message", help="Natural-language user request.")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Shortcut for --agent-mode mock --media-mode mock.",
    )
    parser.add_argument(
        "--agent-mode",
        choices=["mock", "real"],
        default=None,
        help="Control whether text Agents use mock outputs or real LLM calls.",
    )
    parser.add_argument(
        "--media-mode",
        choices=["mock", "real"],
        default=None,
        help="Control whether media tools use mock files or real media APIs.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full ChatWorkflowResponse JSON.",
    )
    parser.add_argument(
        "--show-planning-events",
        "--stream-planning",
        dest="show_planning_events",
        action="store_true",
        help="Print chat-style workflow planning events without calling HTTP APIs.",
    )
    parser.add_argument(
        "--skip-audio-agents",
        action="store_true",
        help="Skip sound effects, voiceover, BGM, audio generation, and audio-video sync.",
    )
    parser.add_argument(
        "--poll-media",
        action="store_true",
        help="Accept asynchronous media polling mode for developer runs.",
    )
    parser.add_argument(
        "--download-media",
        action="store_true",
        help="Download completed remote media artifacts when the provider returns URLs.",
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


def _artifact_path(settings: Settings, workflow_id: str, *parts: str) -> str:
    return (settings.media_data_dir / Path(*parts) / workflow_id).as_posix()


def _load_selected_assets(
    settings: Settings,
    selected_asset_ids: list[str],
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


NODE_DISPLAY_NAMES = {
    "requirements-analysis": "\u9700\u6c42\u5206\u6790",
    "product-design": "\u4ea7\u54c1\u8bbe\u8ba1",
    "creative-direction": "\u521b\u610f\u65b9\u5411",
    "script": "\u5267\u672c",
    "character-design": "\u89d2\u8272\u8bbe\u8ba1",
    "scene-design": "\u573a\u666f\u8bbe\u8ba1",
    "character-image-generation": "\u89d2\u8272\u56fe\u751f\u6210",
    "scene-image-generation": "\u573a\u666f\u56fe\u751f\u6210",
    "bgm": "BGM",
    "storyboard": "\u5206\u955c",
    "storyboard-image-generation": "\u5206\u955c\u56fe\u751f\u6210",
    "storyboard-video-generation": "\u5206\u955c\u89c6\u9891\u751f\u6210",
    "final-composition": "\u6700\u7ec8\u5408\u6210",
}


STREAM_TEXT = {
    "run_started_default": "\u5f00\u59cb\u5904\u7406\u5e7f\u544a\u9700\u6c42",
    "front_desk_started": "\u6b63\u5728\u7406\u89e3\u5e7f\u544a\u9700\u6c42...",
    "workflow_planning_started": "\u6b63\u5728\u751f\u6210\u9ed8\u8ba4\u5de5\u4f5c\u6d41...",
    "workflow_edges_started": "\u6b63\u5728\u521b\u5efa\u8282\u70b9\u8fde\u7ebf...",
    "node_planned_prefix": "\u5df2\u521b\u5efa",
    "node_planned_suffix": "\u8282\u70b9",
    "edge_planned": "\u5df2\u521b\u5efa\u8fde\u7ebf",
    "graph_saved_default": "\u5de5\u4f5c\u6d41\u5df2\u4fdd\u5b58",
    "done_completed": "\u5de5\u4f5c\u6d41\u521b\u5efa\u5b8c\u6210",
    "done_other": "\u672c\u6b21\u5bf9\u8bdd\u5904\u7406\u5b8c\u6210",
}


def _run_stream_planning(
    *,
    settings: Settings,
    message: str,
    skip_audio_agents: bool,
    selected_assets: list[WorkflowAssetReference],
) -> int:
    service = ChatWorkflowStreamService(settings)
    request = ChatWorkflowRunCreateRequest(
        message=message,
        skip_audio_agents=skip_audio_agents,
        selected_assets=selected_assets,
        audio_mode="none" if skip_audio_agents else None,
    )
    exit_code = 0
    for event in service.stream_plan_events(request):
        _print_stream_event(event)
        if event.event == "error":
            exit_code = 1
    return exit_code


def _print_stream_event(
    event: ChatWorkflowStreamEvent,
    output_func=print,
    error_func=None,
) -> None:
    error_output = error_func or output_func
    data = event.data
    if event.event == "run_started":
        output_func(f"[run_started] {data.get('message') or STREAM_TEXT['run_started_default']}")
    elif event.event == "front_desk_started":
        output_func(f"[front_desk_started] {STREAM_TEXT['front_desk_started']}")
    elif event.event == "front_desk_reply":
        output_func(f"[front_desk_reply] {data.get('reply') or '-'}")
    elif event.event == "clarification_required":
        missing = data.get("missing_fields") or []
        suffix = (
            f" missing_fields={', '.join(missing)}" if isinstance(missing, list) and missing else ""
        )
        output_func(f"[clarification_required] {data.get('reply') or '-'}{suffix}")
    elif event.event == "workflow_planning_started":
        output_func(f"[workflow_planning_started] {STREAM_TEXT['workflow_planning_started']}")
    elif event.event == "workflow_node_planned":
        node_id = str(data.get("node_id") or data.get("node_type") or "-")
        display_name = NODE_DISPLAY_NAMES.get(node_id, str(data.get("title") or node_id))
        output_func(
            f"[workflow_node_planned] {STREAM_TEXT['node_planned_prefix']}"
            f"{display_name}{STREAM_TEXT['node_planned_suffix']} {node_id}"
        )
    elif event.event == "workflow_edges_started":
        output_func(f"[workflow_edges_started] {STREAM_TEXT['workflow_edges_started']}")
    elif event.event == "workflow_edge_planned":
        output_func(
            f"[workflow_edge_planned] {STREAM_TEXT['edge_planned']} "
            f"{data.get('source')} -> {data.get('target')}"
        )
    elif event.event == "workflow_graph_saved":
        output_func(
            f"[workflow_graph_saved] {data.get('message') or STREAM_TEXT['graph_saved_default']}"
        )
    elif event.event == "workflow_generated":
        workflow_payload = data.get("workflow")
        workflow = (
            AdWorkflowResponse.model_validate(workflow_payload)
            if isinstance(workflow_payload, dict)
            else None
        )
        workflow_id = data.get("workflow_id") or (workflow.workflow_id if workflow else "-")
        output_func(f"[workflow_generated] Workflow id: {workflow_id}")
        if workflow is not None:
            output_func("Nodes:")
            for node in workflow.nodes:
                output_func(f"- {node.id}")
            output_func(f"Edges: {len(workflow.edges)}")
    elif event.event == "done":
        status = data.get("status")
        message = (
            STREAM_TEXT["done_completed"] if status == "completed" else STREAM_TEXT["done_other"]
        )
        output_func(f"[done] {message}")
    elif event.event == "error":
        error_output(f"[error] {data.get('message') or '-'}")
    else:
        output_func(f"[{event.event}] {json.dumps(data, ensure_ascii=False)}")


def _node_location(result: object, node_id: str) -> str | None:
    if result.workflow is None:
        return None
    for node in result.workflow.nodes:
        if node.id == node_id:
            return node.content.get("url") or node.content.get("local_path")
    return None


def _node_content(result: object, node_id: str) -> dict[str, object] | None:
    if result.workflow is None:
        return None
    for node in result.workflow.nodes:
        if node.id == node_id:
            return node.content
    return None


def _display_local_path(settings: Settings, local_path: object) -> str:
    if not isinstance(local_path, str) or not local_path:
        return "-"
    return (settings.media_data_dir / local_path).as_posix()


def _print_character_asset_summary(result: object, settings: Settings) -> None:
    character_content = _node_content(result, "character-image-generation")
    if not character_content:
        return
    assets = character_content.get("assets")
    if not isinstance(assets, list) or not assets:
        return

    print("Character turnarounds:")
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        print(
            "- "
            f"{asset.get('asset_id')}: status={asset.get('status')} "
            f"download={asset.get('download_status')} "
            f"metadata={_display_local_path(settings, asset.get('metadata_path'))} "
            f"local={_display_local_path(settings, asset.get('local_path'))} "
            f"url={asset.get('url') or '-'}"
        )


def _print_storyboard_video_summary(result: object, settings: Settings) -> None:
    storyboard_video = _node_content(result, "storyboard-video-generation")
    if not storyboard_video:
        return

    print(
        "Storyboard video generation: "
        f"status={storyboard_video.get('status')} "
        f"composition_status={storyboard_video.get('composition_status', '-')}"
    )
    segments = storyboard_video.get("segments")
    if isinstance(segments, list) and segments:
        print("Storyboard video segments:")
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            print(
                "- segment "
                f"{segment.get('order')}: status={segment.get('status')} "
                f"download={segment.get('download_status', '-')} "
                f"duration={segment.get('duration_seconds')}s "
                f"task_id={segment.get('task_id') or segment.get('asset_id') or '-'} "
                f"query_url={segment.get('task_query_url') or '-'} "
                f"local={_display_local_path(settings, segment.get('local_path'))} "
                f"resolution={segment.get('resolution') or '-'} "
                f"ratio={segment.get('ratio') or '-'}"
            )
        waiting_task_ids = [
            str(segment.get("task_id"))
            for segment in segments
            if isinstance(segment, dict)
            and segment.get("task_id")
            and not segment.get("local_path")
        ]
        if waiting_task_ids:
            print(f"Waiting segment tasks: {', '.join(waiting_task_ids)}")
    elif storyboard_video.get("task_id") or storyboard_video.get("task_query_url"):
        print(
            "Storyboard task: "
            f"task_id={storyboard_video.get('task_id') or '-'} "
            f"query_url={storyboard_video.get('task_query_url') or '-'}"
        )


def _refresh_real_media_tasks(result: object, settings: Settings) -> None:
    if settings.media_mode.strip().lower() != "real" or result.workflow is None:
        return

    provider = build_media_provider(settings)
    workflow_id = result.workflow.workflow_id

    storyboard_video = _node_content(result, "storyboard-video-generation")
    if not storyboard_video:
        return
    segments = storyboard_video.get("segments")
    if not isinstance(segments, list):
        if storyboard_video.get("task_id") and not storyboard_video.get("local_path"):
            refreshed_storyboard = provider.retrieve_storyboard_video_task(
                str(storyboard_video["task_id"]),
                workflow_id=workflow_id,
                source_assets=[
                    asset_id
                    for asset_id in storyboard_video.get("source_assets", [])
                    if isinstance(asset_id, str)
                ],
                duration_seconds=int(storyboard_video.get("duration_seconds") or 0),
            )
            storyboard_video.update(refreshed_storyboard)
        return

    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        if not segment.get("task_id") or segment.get("local_path"):
            continue
        refreshed_segment = provider.retrieve_storyboard_video_task(
            str(segment["task_id"]),
            workflow_id=workflow_id,
            source_assets=[
                asset_id
                for asset_id in segment.get("source_assets", [])
                if isinstance(asset_id, str)
            ],
            duration_seconds=int(segment.get("duration_seconds") or 0),
            segment_order=int(segment.get("order") or index),
            scene_id=str(segment.get("scene_id") or f"scene-{index}"),
            prompt=str(segment.get("prompt") or ""),
            resolution=str(segment.get("resolution") or ""),
            ratio=str(segment.get("ratio") or ""),
        )
        segment.update(refreshed_segment)

    final_composition = _node_content(result, "final-composition")
    if final_composition and hasattr(provider, "compose_final_video"):
        refreshed_final = provider.compose_final_video(
            storyboard_video,
            int(storyboard_video.get("duration_seconds") or 0),
            workflow_id,
        )
        final_composition.update(refreshed_final)


def _print_summary(result: object, settings: Settings) -> None:
    front_desk = result.front_desk
    print(f"Front desk intent: {front_desk.intent}")
    print(f"Front desk reply: {front_desk.reply}")
    print(f"Should start workflow: {str(front_desk.should_start_workflow).lower()}")
    print(f"Missing fields: {', '.join(front_desk.missing_fields) or '-'}")

    if result.workflow is None:
        print("Workflow: -")
        return

    workflow = result.workflow
    print(f"Workflow id: {workflow.workflow_id}")
    print("Nodes:")
    for node in workflow.nodes:
        print(f"- {node.id}")
    print(f"Edge count: {len(workflow.edges)}")
    print(f"Trace: {_artifact_path(settings, workflow.workflow_id, 'runs')}/trace.json")
    _print_character_asset_summary(result, settings)
    _print_storyboard_video_summary(result, settings)
    print(
        "Subtitles: "
        f"{_artifact_path(settings, workflow.workflow_id, 'subtitles')}/subtitle-plan.json"
    )
    print(f"Audio: {_artifact_path(settings, workflow.workflow_id, 'audio')}/")
    final_composition = _node_content(result, "final-composition")
    if final_composition and final_composition.get("local_path"):
        print(f"Final video: {_display_local_path(settings, final_composition.get('local_path'))}")
    print(
        f"Final metadata: {_artifact_path(settings, workflow.workflow_id, 'final')}/final-ad-video.json"
    )


def main() -> int:
    args = _parse_args()
    settings = _build_settings(args)
    service = ChatWorkflowService(settings)

    try:
        selected_assets = _load_selected_assets(settings, args.selected_asset_ids)
        if args.show_planning_events:
            return _run_stream_planning(
                settings=settings,
                message=args.message,
                skip_audio_agents=args.skip_audio_agents,
                selected_assets=selected_assets,
            )
        result = service.generate_from_chat(
            FrontDeskChatRequest(
                message=args.message,
                skip_audio_agents=args.skip_audio_agents,
                selected_assets=selected_assets,
            )
        )
    except ChatWorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.poll_media or args.download_media:
        try:
            _refresh_real_media_tasks(result, settings)
        except Exception as exc:
            print(f"media_refresh_failed: {exc}", file=sys.stderr)
            return 1

    if args.json:
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        _print_summary(result, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
