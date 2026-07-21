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
from app.services.media_tasks import MediaTaskService


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll and download async media tasks.")
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--media-mode", choices=["mock", "real"], default=None)
    parser.add_argument("--download-media", action="store_true")
    parser.add_argument("--compose-when-ready", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=10)
    parser.add_argument("--max-attempts", type=int, default=60)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _build_settings(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    if args.media_mode is not None:
        settings = replace(settings, media_mode=args.media_mode)
    return settings


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = _build_settings(args)
    service = MediaTaskService(settings)
    payload = {}
    try:
        poll_result = service.poll_until_all_segments_ready(
            args.workflow_id,
            interval_seconds=args.interval_seconds,
            max_attempts=args.max_attempts,
            download_media=args.download_media,
            on_segment_update=None if args.json else _print_segment,
        )
        payload["media_poll"] = {
            "workflow_id": poll_result.workflow_id,
            "segments": poll_result.segments,
            "all_ready": poll_result.all_ready,
            "attempts": poll_result.attempts,
        }
        if args.compose_when_ready:
            final_asset = service.compose_when_ready(args.workflow_id)
            payload["final_composition"] = final_asset
            if not args.json:
                _print_final(final_asset, settings)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _print_segment(segment: dict[str, object]) -> None:
    print(
        "Media> "
        f"segment {segment.get('order')} "
        f"status={segment.get('status') or '-'} "
        f"download_status={segment.get('download_status') or '-'} "
        f"task_id={segment.get('task_id') or '-'} "
        f"query_url={segment.get('task_query_url') or '-'} "
        f"local_path={segment.get('local_path') or '-'}"
    )


def _print_final(final_asset: dict[str, object], settings: Settings) -> None:
    if final_asset.get("status") == "ready" and final_asset.get("local_path"):
        print("FFmpeg> final-ad-video.mp4 ready")
        print(
            f"FFmpeg> final_video={(settings.media_data_dir / str(final_asset['local_path'])).as_posix()}"
        )
    elif final_asset.get("status") == "waiting_for_segments":
        print("FFmpeg> waiting_for_segments")
    else:
        print(f"FFmpeg> status={final_asset.get('status')}")
    metadata_path = final_asset.get("metadata_path")
    if isinstance(metadata_path, str):
        print(f"FFmpeg> metadata={(settings.media_data_dir / metadata_path).as_posix()}")


if __name__ == "__main__":
    raise SystemExit(main())
