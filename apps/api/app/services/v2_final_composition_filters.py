from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.schemas.workflow_v2 import WorkflowV2TimelineClip


@dataclass(frozen=True)
class V2CompositionCanvas:
    """Validated output geometry used by the final-composition filter compiler."""

    width: int
    height: int
    fps: int
    duration_seconds: float
    subtitle_font_path: str | None = None


@dataclass(frozen=True)
class V2ResolvedTimelineClip:
    """A timeline clip pinned to one FFmpeg input and its probed media capabilities."""

    input_index: int
    clip: WorkflowV2TimelineClip
    track_order: int
    source_has_audio: bool
    source_duration_seconds: float | None = None


@dataclass(frozen=True)
class V2FilterGraph:
    filter_complex: str
    video_label: str | None = None
    audio_label: str | None = None
    loop_input_indices: tuple[int, ...] = ()


@dataclass(frozen=True)
class FFmpegRenderCommand:
    """Safe argument-list fragments compiled from typed timeline controls."""

    input_args: tuple[str, ...]
    filter_graph: V2FilterGraph
    output_args: tuple[str, ...]


def build_ffmpeg_render_command(
    *,
    ffmpeg_path: str,
    source_paths: list[str],
    resolved_clips: list[V2ResolvedTimelineClip],
    filter_graph: V2FilterGraph,
    canvas: V2CompositionCanvas,
    video_encoder: str,
    audio_encoder: str,
    video_bitrate: str | None,
    audio_bitrate: str | None,
    output_path: str,
) -> FFmpegRenderCommand:
    """Compile safe FFmpeg argv fragments from server-validated editor controls."""

    input_args: list[str] = [ffmpeg_path, "-y", "-loglevel", "error"]
    clips_by_input = {resolved.input_index: resolved.clip for resolved in resolved_clips}
    for input_index, source_path in enumerate(source_paths):
        clip = clips_by_input[input_index]
        if clip.clip_type == "image":
            input_args.extend(["-loop", "1", "-framerate", str(canvas.fps)])
        elif input_index in filter_graph.loop_input_indices:
            input_args.extend(["-stream_loop", "-1"])
        input_args.extend(["-i", source_path])

    combined_graph = filter_graph.filter_complex
    output_args = ["-filter_complex", combined_graph, "-map", "[vout]"]
    if filter_graph.audio_label:
        output_args.extend(["-map", f"[{filter_graph.audio_label}]", "-c:a", audio_encoder])
        if audio_bitrate:
            output_args.extend(["-b:a", audio_bitrate])
    else:
        output_args.append("-an")
    output_args.extend(["-c:v", video_encoder, "-pix_fmt", "yuv420p"])
    if video_bitrate:
        output_args.extend(["-b:v", video_bitrate])
    output_args.extend(["-t", f"{canvas.duration_seconds:.3f}", output_path])
    return FFmpegRenderCommand(
        input_args=tuple(input_args),
        filter_graph=filter_graph,
        output_args=tuple(output_args),
    )


def build_visual_filter_graph(
    clips: list[V2ResolvedTimelineClip],
    canvas: V2CompositionCanvas,
) -> V2FilterGraph:
    """Compile validated visual/subtitle controls without accessing files or processes."""

    fragments = [
        (
            f"color=c=black:s={canvas.width}x{canvas.height}:r={canvas.fps}:"
            f"d={canvas.duration_seconds:.3f}[canvas0]"
        )
    ]
    current = "canvas0"
    visual_index = 0
    for resolved in _ordered_enabled(clips, kinds={"video", "image"}):
        clip = resolved.clip
        source = f"[{resolved.input_index}:v]"
        output = f"visual{visual_index}"
        fragments.append(f"{source}{_visual_filters(clip, canvas)}[{output}]")
        placed = f"placed{visual_index}"
        placement = normalized_overlay_placement(clip.transform.x, clip.transform.y)
        fragments.append(f"[{current}][{output}]overlay={placement}:eof_action=pass[{placed}]")
        current = placed
        visual_index += 1

    subtitle_index = 0
    for resolved in _ordered_enabled(clips, kinds={"subtitle"}):
        clip = resolved.clip
        if not canvas.subtitle_font_path:
            raise ValueError("enabled subtitles require a configured server font")
        output = f"subtitle{subtitle_index}"
        fragments.append(f"[{current}]{_subtitle_filter(clip, canvas)}[{output}]")
        current = output
        subtitle_index += 1
    fragments.append(f"[{current}]format=yuv420p[vout]")
    return V2FilterGraph(filter_complex=";".join(fragments), video_label="vout")


def build_audio_filter_graph(
    clips: list[V2ResolvedTimelineClip],
    *,
    timeline_duration_seconds: float,
    audio_mode: Literal["none", "bgm_only", "full"],
) -> V2FilterGraph:
    """Compile audio mixing controls while excluding unavailable source-audio streams."""

    if audio_mode == "none":
        return V2FilterGraph(filter_complex="", audio_label=None)
    fragments: list[str] = []
    labels: list[str] = []
    loop_input_indices: list[int] = []
    for index, resolved in enumerate(_ordered_enabled(clips, kinds={"video", "audio"})):
        clip = resolved.clip
        if clip.audio.muted or clip.muted:
            continue
        if clip.clip_type == "video" and not resolved.source_has_audio:
            continue
        if audio_mode == "bgm_only" and clip.clip_type == "audio" and not _is_bgm(clip):
            continue
        if (
            _is_bgm(clip)
            and resolved.source_duration_seconds is not None
            and resolved.source_duration_seconds + 0.01 < clip.duration
        ):
            loop_input_indices.append(resolved.input_index)
        output = f"audio{index}"
        fragments.append(f"[{resolved.input_index}:a]{_audio_filters(clip)}[{output}]")
        labels.append(f"[{output}]")
    if not labels:
        return V2FilterGraph(
            filter_complex=";".join(fragments),
            audio_label=None,
            loop_input_indices=tuple(loop_input_indices),
        )
    fragments.append(
        "".join(labels)
        + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0,"
        + f"alimiter,atrim=duration={timeline_duration_seconds:.3f}[aout]"
    )
    return V2FilterGraph(
        filter_complex=";".join(fragments),
        audio_label="aout",
        loop_input_indices=tuple(loop_input_indices),
    )


def normalized_overlay_placement(
    x: float,
    y: float,
) -> str:
    """Compile validated center offsets into safe FFmpeg overlay placement expressions."""

    return f"x=(main_w-overlay_w)/2{x:+.6f}*main_w/2:y=(main_h-overlay_h)/2{y:+.6f}*main_h/2"


def _ordered_enabled(
    clips: list[V2ResolvedTimelineClip],
    *,
    kinds: set[str],
) -> list[V2ResolvedTimelineClip]:
    return sorted(
        (
            resolved
            for resolved in clips
            if resolved.clip.enabled and resolved.clip.clip_type in kinds
        ),
        key=lambda resolved: (
            resolved.track_order,
            resolved.clip.start_time,
            resolved.clip.clip_id,
        ),
    )


def _visual_filters(clip: WorkflowV2TimelineClip, canvas: V2CompositionCanvas) -> str:
    transform = clip.transform
    if clip.clip_type == "video":
        trim = f"trim=start={clip.trim_in:.3f}:end={clip.trim_out:.3f}"
    else:
        trim = f"trim=duration={clip.duration:.3f}"
    filters = [trim, "setpts=PTS-STARTPTS", f"fps=fps={canvas.fps}"]
    target_width = max(1, round(canvas.width * transform.scale_x))
    target_height = max(1, round(canvas.height * transform.scale_y))
    if transform.fit == "cover":
        filters.extend(
            [
                f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase",
                f"crop={target_width}:{target_height}",
            ]
        )
    else:
        filters.extend(
            [
                f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease",
                f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:color=black@0",
            ]
        )
    if transform.rotation_degrees:
        filters.append(f"rotate={transform.rotation_degrees:.3f}*PI/180:ow=rotw(iw):oh=roth(ih)")
    filters.extend(_color_filters(clip))
    filters.extend(["format=rgba", f"colorchannelmixer=aa={transform.opacity:.3f}"])
    if clip.start_time:
        filters.append(f"setpts=PTS+{clip.start_time:.3f}/TB")
    return ",".join(filters)


def _color_filters(clip: WorkflowV2TimelineClip) -> list[str]:
    color = clip.color
    preset = color.preset_id
    if preset == "warm":
        balance, minimum, maximum, hue_offset, saturation = (
            "rs=.060:bs=-.030",
            0.0,
            0.98,
            4.0,
            1.08,
        )
    elif preset == "cool":
        balance, minimum, maximum, hue_offset, saturation = (
            "rs=-.030:bs=.060",
            0.0,
            0.98,
            -4.0,
            0.95,
        )
    elif preset == "high_contrast":
        balance, minimum, maximum, hue_offset, saturation = (
            "rs=.010:bs=.010",
            0.03,
            0.97,
            0.0,
            1.18,
        )
    elif preset == "muted":
        balance, minimum, maximum, hue_offset, saturation = (
            "rs=.000:bs=.000",
            0.0,
            0.94,
            0.0,
            0.72,
        )
    else:
        balance, minimum, maximum, hue_offset, saturation = "rs=0:bs=0", 0.0, 1.0, 0.0, 1.0
    temperature = color.temperature / 1000
    tint = color.tint / 1000
    brightness = color.brightness / 10
    minimum = min(1.0, max(0.0, minimum + max(0.0, brightness)))
    maximum = min(1.0, max(minimum + 0.01, maximum * max(0.1, color.contrast)))
    saturation = max(0.0, saturation * color.saturation)
    exposure_gain = 2**color.exposure
    input_maximum = min(1.0, max(0.01, 1 / exposure_gain))
    output_maximum = min(1.0, maximum * min(1.0, exposure_gain))
    return [
        f"colorbalance={balance}:rm={temperature:.3f}:gm={tint:.3f}",
        (f"colorlevels=rimin={minimum:.3f}:rimax={input_maximum:.3f}:romax={output_maximum:.3f}"),
        f"hue=h={hue_offset + color.hue:.3f}:s={saturation:.3f}",
    ]


def _audio_filters(clip: WorkflowV2TimelineClip) -> str:
    audio = clip.audio
    filters = [
        f"atrim=start={clip.trim_in:.3f}:end={clip.trim_out:.3f}",
        "asetpts=PTS-STARTPTS",
        f"volume={audio.volume:.3f}",
    ]
    if audio.fade_in_seconds:
        filters.append(f"afade=t=in:st=0:d={audio.fade_in_seconds:.3f}")
    if audio.fade_out_seconds:
        fade_start = max(0, clip.duration - audio.fade_out_seconds)
        filters.append(f"afade=t=out:st={fade_start:.3f}:d={audio.fade_out_seconds:.3f}")
    delay_ms = round(clip.start_time * 1000)
    if delay_ms:
        filters.append(f"adelay={delay_ms}:all=1")
    filters.extend(["aresample=44100", "aformat=channel_layouts=stereo"])
    return ",".join(filters)


def _subtitle_filter(clip: WorkflowV2TimelineClip, canvas: V2CompositionCanvas) -> str:
    assert clip.text is not None
    style = clip.subtitle_style
    y = {
        "top_center": "h*0.1",
        "center": "(h-text_h)/2",
        "bottom_center": "h-text_h-h*0.1",
    }[style.position]
    escaped_text = _escape_drawtext(clip.text)
    escaped_font = _escape_drawtext(canvas.subtitle_font_path or "")
    return (
        f"drawtext=fontfile='{escaped_font}':text='{escaped_text}':"
        f"fontcolor={style.color}:fontsize={style.font_size}:x=(w-text_w)/2:y={y}:"
        f"enable='between(t,{clip.start_time:.3f},{clip.start_time + clip.duration:.3f})'"
    )


def _escape_drawtext(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("'", r"\'")
        .replace(":", r"\:")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("=", r"\=")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace("%", r"\%")
    )


def _is_bgm(clip: WorkflowV2TimelineClip) -> bool:
    return clip.metadata.get("role") == "bgm" or clip.metadata.get("is_bgm") is True
