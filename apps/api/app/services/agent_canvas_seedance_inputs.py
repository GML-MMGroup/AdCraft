"""Compile explicit Agent Canvas bindings into one Seedance input manifest."""

from __future__ import annotations

import hashlib

from app.schemas.agent_canvas import (
    CanvasNodeV2,
    ResolvedInputSnapshotV2,
    ResolvedTextInputSnapshotV2,
)
from app.schemas.seedance_inputs import (
    SeedanceDeliveredMediaInputV1,
    SeedanceInputManifestAuditV1,
    SeedanceInputManifestV1,
    SeedanceMediaInputAuditV1,
    SeedanceMediaInputV1,
    SeedanceTextInputAuditV1,
    SeedanceTextInputV1,
)


class AgentCanvasSeedanceInputCompiler:
    """Compile saved prompt and delivered bindings without rediscovering assets."""

    def __init__(self, *, default_duration_seconds: int = 5) -> None:
        if not 1 <= default_duration_seconds <= 15:
            raise ValueError("default_duration_seconds must be within 1..15")
        self._default_duration_seconds = default_duration_seconds

    def compile(
        self,
        node: CanvasNodeV2,
        *,
        model_id: str,
        resolved_inputs: tuple[ResolvedInputSnapshotV2, ...],
        delivered_media: tuple[SeedanceDeliveredMediaInputV1, ...],
    ) -> tuple[SeedanceInputManifestV1, SeedanceInputManifestAuditV1]:
        if node.node_type != "video":
            raise ValueError("Seedance manifests require a Video node.")
        prompt = str(node.generation_prompt or node.summary_prompt or node.title).strip()
        if not prompt:
            raise ValueError("v2_video_prompt_empty")
        requested_duration, effective_duration, normalizations = self._normalize_duration(
            node.parameters.get("duration_seconds")
        )
        text_inputs = self._compile_text_inputs(resolved_inputs)
        media_inputs = self._compile_media_inputs(delivered_media)
        media_inputs = _with_reference_purposes(node, media_inputs)
        compiled_prompt = _compile_prompt(prompt, text_inputs, media_inputs)
        manifest = SeedanceInputManifestV1(
            node_id=node.node_id,
            model_id=model_id,
            prompt=compiled_prompt,
            text_inputs=text_inputs,
            image_inputs=tuple(item for item in media_inputs if item.media_type == "image"),
            video_inputs=tuple(item for item in media_inputs if item.media_type == "video"),
            audio_inputs=tuple(item for item in media_inputs if item.media_type == "audio"),
            aspect_ratio=str(node.parameters.get("aspect_ratio") or "16:9"),
            resolution=str(node.parameters.get("resolution") or "720p"),
            requested_duration_seconds=requested_duration,
            effective_duration_seconds=effective_duration,
            generate_audio=bool(node.parameters.get("generate_audio", False)),
            normalizations=normalizations,
        )
        return manifest, _audit_projection(manifest)

    def _normalize_duration(self, value: object) -> tuple[int, int, tuple[str, ...]]:
        requested = self._default_duration_seconds if value is None else _integer_duration(value)
        if requested < 1:
            raise ValueError("duration_seconds must be at least 1")
        if requested > 15:
            return requested, 15, ("duration_clamped_to_provider_limit",)
        return requested, requested, ()

    @staticmethod
    def _compile_text_inputs(
        inputs: tuple[ResolvedInputSnapshotV2, ...],
    ) -> tuple[SeedanceTextInputV1, ...]:
        counters = {"text": 0, "script": 0}
        result: list[SeedanceTextInputV1] = []
        for item in sorted(
            (
                input_item
                for input_item in inputs
                if isinstance(input_item, ResolvedTextInputSnapshotV2)
            ),
            key=lambda input_item: (input_item.display_order, input_item.binding_id or ""),
        ):
            counters[item.document_kind] += 1
            result.append(
                SeedanceTextInputV1(
                    binding_id=item.binding_id or f"legacy_{item.source_node_id}",
                    source_node_id=item.source_node_id,
                    source_node_revision=item.source_node_revision,
                    source_type=item.document_kind,
                    input_role=item.input_role,
                    display_order=item.display_order,
                    content=item.content,
                    content_hash=item.content_hash,
                    label=f"{item.document_kind.title()} {counters[item.document_kind]}",
                )
            )
        return tuple(result)

    @staticmethod
    def _compile_media_inputs(
        delivered_media: tuple[SeedanceDeliveredMediaInputV1, ...],
    ) -> tuple[SeedanceMediaInputV1, ...]:
        counters = {"image": 0, "video": 0, "audio": 0}
        result: list[SeedanceMediaInputV1] = []
        for item in sorted(
            delivered_media, key=lambda value: (value.display_order, value.binding_id)
        ):
            counters[item.media_type] += 1
            result.append(
                SeedanceMediaInputV1(
                    **item.model_dump(),
                    provider_input_value=item.provider_input_value,
                    label=f"{item.media_type.title()} {counters[item.media_type]}",
                )
            )
        return tuple(result)


def _integer_duration(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("duration_seconds must be an integer")
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError("duration_seconds must be an integer") from error
    if result != value and str(result) != str(value):
        raise ValueError("duration_seconds must be an integer")
    return result


def _compile_prompt(
    saved_prompt: str,
    text_inputs: tuple[SeedanceTextInputV1, ...],
    media_inputs: tuple[SeedanceMediaInputV1, ...],
) -> str:
    segments = [saved_prompt]
    for item in text_inputs:
        segments.append(f"{item.label}: {item.content}")
    labels = [item.label for item in (*text_inputs, *media_inputs)]
    if labels:
        segments.append(f"Use the following bound references in order: {', '.join(labels)}.")
    storyboard_grid = next(
        (item for item in media_inputs if item.reference_purpose == "storyboard_sequence"),
        None,
    )
    scene_board = next(
        (item for item in media_inputs if item.reference_purpose == "scene_reference"),
        None,
    )
    if storyboard_grid is not None and scene_board is not None:
        segments.append(
            " ".join(
                (
                    f"{storyboard_grid.label} is the authoritative 3x3 Storyboard Grid.",
                    "Read Panels 1 through 9 left-to-right and top-to-bottom.",
                    "Redraw the opening as a normal full-frame shot from Panel 1, then follow the depicted composition, action, camera, and continuity through Panel 9 in order.",
                    "Never show the grid, collage, contact sheet, panel border, or split screen.",
                )
            )
        )
        segments.append(
            " ".join(
                (
                    f"{scene_board.label} is the Scene Design Board.",
                    "Use it only to preserve environment identity, layout, lighting, materials, and visual style.",
                    "It must not replace or reorder the Storyboard Grid sequence.",
                )
            )
        )
    return "\n\n".join(segments)


def _with_reference_purposes(
    node: CanvasNodeV2,
    media_inputs: tuple[SeedanceMediaInputV1, ...],
) -> tuple[SeedanceMediaInputV1, ...]:
    if node.semantic_role != "storyboard_video_segment":
        return media_inputs
    return tuple(
        item.model_copy(
            update={
                "reference_purpose": (
                    "storyboard_sequence"
                    if item.media_type == "image" and item.source_semantic_role == "storyboard_grid"
                    else "scene_reference"
                    if item.media_type == "image"
                    and item.source_semantic_role == "scene_design_board"
                    else None
                )
            }
        )
        for item in media_inputs
    )


def _audit_projection(manifest: SeedanceInputManifestV1) -> SeedanceInputManifestAuditV1:
    text_inputs = tuple(
        SeedanceTextInputAuditV1(
            binding_id=item.binding_id,
            source_node_id=item.source_node_id,
            source_node_revision=item.source_node_revision,
            source_type=item.source_type,
            input_role=item.input_role,
            display_order=item.display_order,
            content_hash=item.content_hash,
            label=item.label,
        )
        for item in manifest.text_inputs
    )
    media_inputs = tuple(
        SeedanceMediaInputAuditV1(
            binding_id=item.binding_id,
            asset_id=item.asset_id,
            media_type=item.media_type,
            input_role=item.input_role,
            source_semantic_role=item.source_semantic_role,
            reference_purpose=item.reference_purpose,
            required=item.required,
            display_order=item.display_order,
            provider_input_type=item.provider_input_type,
            checksum=item.checksum,
            label=item.label,
            byte_count=item.byte_count,
        )
        for item in manifest.media_inputs
    )
    return SeedanceInputManifestAuditV1(
        node_id=manifest.node_id,
        model_id=manifest.model_id,
        prompt_hash=hashlib.sha256(manifest.prompt.encode()).hexdigest(),
        text_inputs=text_inputs,
        media_inputs=media_inputs,
        input_counts={
            "text": sum(item.source_type == "text" for item in manifest.text_inputs),
            "script": sum(item.source_type == "script" for item in manifest.text_inputs),
            "image": len(manifest.image_inputs),
            "video": len(manifest.video_inputs),
            "audio": len(manifest.audio_inputs),
        },
        aspect_ratio=manifest.aspect_ratio,
        resolution=manifest.resolution,
        requested_duration_seconds=manifest.requested_duration_seconds,
        effective_duration_seconds=manifest.effective_duration_seconds,
        generate_audio=manifest.generate_audio,
        normalizations=manifest.normalizations,
    )
