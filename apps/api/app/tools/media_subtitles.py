from __future__ import annotations

from pathlib import Path
from typing import Any

from app.schemas.agent_outputs import SubtitleGenerationOutput

from app.tools.media_artifact_io import _save_artifact


def _format_srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def _subtitle_cues_from_script(
    script: dict[str, Any],
    duration_seconds: int,
) -> list[dict[str, Any]]:
    segments = _playable_segments_from_script(script)
    non_empty_segments = [
        (cue_type, str(text).strip()) for cue_type, text in segments if str(text).strip()
    ]
    if not non_empty_segments:
        non_empty_segments = [("narrator", "")]

    cue_count = len(non_empty_segments)
    cues: list[dict[str, Any]] = []
    for index, (cue_type, text) in enumerate(non_empty_segments, start=1):
        start_seconds = duration_seconds * (index - 1) / cue_count
        end_seconds = duration_seconds * index / cue_count
        normalized_cue_type = "cta" if cue_type == "cta" else "narrator"
        cues.append(
            {
                "cue_id": f"cue-{index}",
                "scene": index,
                "order": index,
                "start_time": _format_srt_time(start_seconds),
                "end_time": _format_srt_time(end_seconds),
                "text": text,
                "cue_type": normalized_cue_type,
                "speaker_hint": "narrator",
            }
        )
    return cues


def _playable_segments_from_script(script: dict[str, Any]) -> list[tuple[str, str]]:
    subtitle_lines = script.get("subtitle_lines")
    if isinstance(subtitle_lines, list) and subtitle_lines:
        return [
            ("cta" if index == len(subtitle_lines) else "narrator", str(line))
            for index, line in enumerate(subtitle_lines, start=1)
        ]

    return [
        ("hook", script.get("hook", "")),
        ("body", script.get("body", "")),
        ("cta", script.get("cta", "")),
    ]


def _write_srt_file(
    data_dir: Path,
    workflow_id: str,
    cues: list[dict[str, Any]],
) -> str:
    relative_path = Path("subtitles") / workflow_id / "subtitle.srt"
    output_path = data_dir / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    blocks = [
        (f"{index}\n{cue['start_time']} --> {cue['end_time']}\n{cue['text']}\n")
        for index, cue in enumerate(cues, start=1)
    ]
    output_path.write_text("\n".join(blocks), encoding="utf-8")
    return relative_path.as_posix()


def generate_subtitle_asset(
    script: dict[str, Any],
    duration_seconds: int,
    workflow_id: str,
    data_dir: Path,
) -> dict[str, Any]:
    cues = _subtitle_cues_from_script(script, duration_seconds)
    srt_path = _write_srt_file(data_dir, workflow_id, cues)
    subtitle_asset = _save_artifact(
        data_dir,
        "subtitles",
        workflow_id,
        "subtitle-plan.json",
        {
            "asset_id": "subtitle-plan",
            "format": "srt",
            "source": script,
            "cues": cues,
            "srt_path": srt_path,
            "status": "ready",
        },
    )
    return SubtitleGenerationOutput.model_validate(subtitle_asset).model_dump()
