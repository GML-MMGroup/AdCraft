"""Compile explicit Agent Canvas bindings into one Seedance input manifest."""

from __future__ import annotations

import hashlib

from app.schemas.agent_canvas import (
    CanvasNodeV2,
    ResolvedInputSnapshotV2,
    ResolvedTextInputSnapshotV2,
)
from app.schemas.agent_canvas_runtime import EffectiveMediaParameterSnapshotV2
from app.schemas.agent_canvas_video_parameters import VideoParameterNormalizationV2
from app.schemas.seedance_inputs import (
    SeedanceDeliveredMediaInputV1,
    SeedanceInputManifestAuditV1,
    SeedanceInputManifestV1,
    SeedanceMediaInputAuditV1,
    SeedanceMediaInputV1,
    SeedanceTextInputAuditV1,
    SeedanceTextInputV1,
    StoryboardGridGroundingAuditV1,
    StoryboardGridGroundingPlanV1,
    StoryboardReferenceIdentityAuditV1,
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
        compiled_prompt: str | None = None,
        effective_parameters: EffectiveMediaParameterSnapshotV2 | None = None,
        grounding_plan: StoryboardGridGroundingPlanV1 | None = None,
    ) -> tuple[SeedanceInputManifestV1, SeedanceInputManifestAuditV1]:
        if node.node_type != "video":
            raise ValueError("Seedance manifests require a Video node.")
        prompt = str(compiled_prompt or node.generation_prompt or "").strip()
        if not prompt:
            raise ValueError("v2_video_prompt_empty")
        effective = (
            effective_parameters.effective if effective_parameters is not None else node.parameters
        )
        requested = (
            effective_parameters.requested if effective_parameters is not None else node.parameters
        )
        _validate_native_audio_snapshot(requested, effective)
        requested_duration, effective_duration, normalizations = self._duration_values(
            requested.get("duration_seconds"),
            effective.get("duration_seconds"),
            effective_parameters.normalizations if effective_parameters is not None else (),
        )
        text_inputs = self._compile_text_inputs(resolved_inputs)
        media_inputs = self._compile_media_inputs(delivered_media, grounding_plan=grounding_plan)
        media_inputs = _with_reference_purposes(node, media_inputs, grounding_plan)
        if grounding_plan is not None:
            _validate_grounding_manifest_inputs(grounding_plan, media_inputs)
        compiled_prompt = _compile_prompt(prompt, text_inputs, media_inputs, grounding_plan)
        manifest = SeedanceInputManifestV1(
            node_id=node.node_id,
            model_id=model_id,
            prompt=compiled_prompt,
            text_inputs=text_inputs,
            image_inputs=tuple(item for item in media_inputs if item.media_type == "image"),
            video_inputs=tuple(item for item in media_inputs if item.media_type == "video"),
            audio_inputs=tuple(item for item in media_inputs if item.media_type == "audio"),
            aspect_ratio=str(effective.get("aspect_ratio") or "16:9"),
            resolution=str(effective.get("resolution") or "720p"),
            requested_duration_seconds=requested_duration,
            effective_duration_seconds=effective_duration,
            generate_audio=bool(effective.get("generate_audio", False)),
            normalizations=normalizations,
            grounding_plan=grounding_plan,
        )
        return manifest, _audit_projection(manifest, grounding_plan=grounding_plan)

    def _duration_values(
        self,
        requested_value: object,
        effective_value: object,
        normalizations: tuple[str | VideoParameterNormalizationV2, ...],
    ) -> tuple[int, int, tuple[str, ...]]:
        requested = (
            self._default_duration_seconds
            if requested_value is None
            else _integer_duration(requested_value)
        )
        if requested < 1:
            raise ValueError("duration_seconds must be at least 1")
        effective = requested if effective_value is None else _integer_duration(effective_value)
        if effective < 1:
            raise ValueError("duration_seconds must be at least 1")
        normalization_codes = tuple(
            item.normalization_code if isinstance(item, VideoParameterNormalizationV2) else item
            for item in normalizations
        )
        if effective > 15:
            effective = 15
            normalization_codes = (
                *normalization_codes,
                "duration_clamped_to_provider_limit",
            )
        return requested, effective, tuple(dict.fromkeys(normalization_codes))

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
        *,
        grounding_plan: StoryboardGridGroundingPlanV1 | None = None,
    ) -> tuple[SeedanceMediaInputV1, ...]:
        counters = {"image": 0, "video": 0, "audio": 0}
        result: list[SeedanceMediaInputV1] = []
        order_by_identity = (
            {
                (item.asset_id, item.version_id): index
                for index, item in enumerate(grounding_plan.ordered_references)
            }
            if grounding_plan is not None
            else {}
        )
        ordered = sorted(
            delivered_media,
            key=lambda value: (
                order_by_identity.get((value.asset_id, value.version_id), 10_000),
                value.display_order,
                value.binding_id,
            ),
        )
        for canonical_order, item in enumerate(ordered):
            counters[item.media_type] += 1
            result.append(
                SeedanceMediaInputV1(
                    **{
                        **item.model_dump(),
                        "display_order": (
                            canonical_order
                            if grounding_plan is not None
                            else item.display_order
                        ),
                        "provider_input_value": item.provider_input_value,
                        "label": f"{item.media_type.title()} {counters[item.media_type]}",
                    }
                )
            )
        return tuple(result)


def validate_seedance_audio_parity(
    manifest: SeedanceInputManifestV1,
    audit: SeedanceInputManifestAuditV1,
) -> None:
    """Reject drift between provider-visible and persisted audio decisions."""

    if manifest.generate_audio != audit.generate_audio:
        raise ValueError("video_native_audio_unsupported")


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


def _validate_native_audio_snapshot(
    requested: dict[str, object],
    effective: dict[str, object],
) -> None:
    requested_audio = requested.get("generate_audio")
    effective_audio = effective.get("generate_audio")
    if requested_audio is None or effective_audio is None:
        return
    if not isinstance(requested_audio, bool) or not isinstance(effective_audio, bool):
        raise ValueError("video_native_audio_unsupported")
    if requested_audio != effective_audio:
        raise ValueError("video_native_audio_unsupported")


def _compile_prompt(
    saved_prompt: str,
    text_inputs: tuple[SeedanceTextInputV1, ...],
    media_inputs: tuple[SeedanceMediaInputV1, ...],
    grounding_plan: StoryboardGridGroundingPlanV1 | None = None,
) -> str:
    segments = [saved_prompt]
    for item in text_inputs:
        segments.append(f"{item.label}: {item.content}")
    labels = [item.label for item in (*text_inputs, *media_inputs)]
    if labels:
        segments.append(f"Use the following bound references in order: {', '.join(labels)}.")
    storyboard_grid = next(
        (item for item in media_inputs if item.reference_purpose == "storyboard_grid"),
        None,
    ) or next(
        (item for item in media_inputs if item.reference_purpose == "storyboard_sequence"),
        None,
    )
    scene_board = next(
        (item for item in media_inputs if item.reference_purpose == "scene_reference"),
        None,
    )
    if grounding_plan is not None and storyboard_grid is not None:
        panel_text = ", ".join(
            f"Panel {panel.panel_index}: {panel.beat}" for panel in grounding_plan.panels
        )
        segments.append(
            " ".join(
                (
                    f"{storyboard_grid.label} is the primary 3x3 storyboard grid for shot {grounding_plan.target_shot_id}.",
                    "Follow its nine panels in persisted order as one continuous shot.",
                    panel_text,
                    "Use the grid for composition, camera, action progression, and timing.",
                    "Do not show, split, crop, or recreate the grid.",
                )
            )
        )
        role_directives = {
            "character_reference": (
                "prioritize this reference for character identity, wardrobe, silhouette, and appearance style"
            ),
            "scene_reference": (
                "prioritize this reference for location, layout, materials, lighting, and environment style"
            ),
            "product_reference": (
                "prioritize this reference for product identity, proportions, materials, and markings"
            ),
            "prop_reference": (
                "prioritize this reference for prop identity, proportions, materials, and markings"
            ),
        }
        references_by_identity = {
            (reference.asset_id, reference.version_id): reference
            for reference in grounding_plan.ordered_references
        }
        image_inputs = tuple(item for item in media_inputs if item.media_type == "image")
        for index, item in enumerate(image_inputs, start=1):
            reference = references_by_identity[(item.asset_id, item.version_id)]
            if reference.semantic_role == "storyboard_grid":
                continue
            directive = role_directives.get(reference.semantic_role)
            if directive is not None:
                segments.append(f"Image {index} is the bound {reference.semantic_role}; {directive}.")
    elif storyboard_grid is not None and scene_board is not None:
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
    grounding_plan: StoryboardGridGroundingPlanV1 | None = None,
) -> tuple[SeedanceMediaInputV1, ...]:
    return tuple(
        item.model_copy(
            update={
                "reference_purpose": (
                    "storyboard_grid"
                    if item.media_type == "image"
                    and grounding_plan is not None
                    and item.asset_id == grounding_plan.grid_asset_id
                    and item.version_id == grounding_plan.grid_version_id
                    else "storyboard_sequence"
                    if item.media_type == "image"
                    and item.source_semantic_role == "storyboard_sequence"
                    else "scene_reference"
                    if item.media_type == "image" and item.source_semantic_role == "scene"
                    else None
                )
            }
        )
        for item in media_inputs
    )


def _audit_projection(
    manifest: SeedanceInputManifestV1,
    *,
    grounding_plan: StoryboardGridGroundingPlanV1 | None = None,
) -> SeedanceInputManifestAuditV1:
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
            version_id=item.version_id,
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
    grounding_audit = _grounding_audit(manifest, grounding_plan)
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
        grounding_audit=grounding_audit,
    )


def _validate_grounding_manifest_inputs(
    plan: StoryboardGridGroundingPlanV1,
    media_inputs: tuple[SeedanceMediaInputV1, ...],
) -> None:
    actual = tuple(
        (item.asset_id, item.version_id, item.checksum)
        for item in media_inputs
        if item.media_type == "image"
    )
    expected = tuple(
        (item.asset_id, item.version_id, item.checksum)
        for item in plan.ordered_references
    )
    if any(
        reference.required
        and (reference.asset_id, reference.version_id, reference.checksum) not in actual
        for reference in plan.ordered_references
    ):
        raise ValueError("v2_storyboard_grid_reference_dropped")
    if not actual or actual[0] != expected[0]:
        raise ValueError("v2_storyboard_grid_reference_dropped")
    if any(identity not in expected for identity in actual):
        raise ValueError("v2_storyboard_grid_reference_dropped")
    if tuple(expected.index(identity) for identity in actual) != tuple(
        sorted(expected.index(identity) for identity in actual)
    ):
        raise ValueError("v2_storyboard_grid_reference_dropped")
    expected_roles = {
        (item.asset_id, item.version_id): item.semantic_role
        for item in plan.ordered_references
    }
    for item in media_inputs:
        if item.media_type != "image":
            continue
        identity = (item.asset_id, item.version_id)
        if _grounding_semantic_role(item) != expected_roles[identity]:
            raise ValueError("v2_storyboard_grid_reference_dropped")


def _grounding_semantic_role(item: SeedanceMediaInputV1) -> str:
    if item.reference_purpose == "storyboard_grid":
        return "storyboard_grid"
    return {
        "character": "character_reference",
        "scene": "scene_reference",
        "scene_board": "scene_reference",
        "product": "product_reference",
        "prop": "prop_reference",
    }.get(item.source_semantic_role or "", item.source_semantic_role or "reference")


def _grounding_audit(
    manifest: SeedanceInputManifestV1,
    plan: StoryboardGridGroundingPlanV1 | None,
) -> StoryboardGridGroundingAuditV1 | None:
    if plan is None:
        return None
    delivered = tuple(
        StoryboardReferenceIdentityAuditV1(
            asset_id=item.asset_id,
            version_id=item.version_id or "unknown",
            checksum=item.checksum,
            semantic_role=_grounding_semantic_role(item),
            binding_id=item.binding_id,
            display_order=index,
            provider_input_type=item.provider_input_type,
        )
        for index, item in enumerate(manifest.media_inputs)
    )
    requested = tuple(
        StoryboardReferenceIdentityAuditV1(
            asset_id=item.asset_id,
            version_id=item.version_id,
            checksum=item.checksum,
            semantic_role=item.semantic_role,
            binding_id=item.binding_id,
            display_order=item.display_order,
        )
        for item in plan.ordered_references
    )
    delivered_keys = {(item.asset_id, item.version_id) for item in delivered}
    omitted_optional = tuple(
        f"{item.asset_id}:{item.version_id}"
        for item in plan.ordered_references
        if not item.required and (item.asset_id, item.version_id) not in delivered_keys
    )
    return StoryboardGridGroundingAuditV1(
        requested=requested,
        delivered=delivered,
        serialized=(),
        submitted=(),
        primary_reference_asset_id=plan.grid_asset_id,
        primary_reference_version_id=plan.grid_version_id,
        panel_sequence_fingerprint=plan.panel_sequence_fingerprint,
        plan_fingerprint=plan.plan_fingerprint,
        provider_request_field="content",
        provider_input_order=tuple(item.semantic_role for item in plan.ordered_references),
        prompt_reference_labels=tuple(item.label for item in manifest.image_inputs),
        omitted_optional_references=omitted_optional,
    )


def mark_seedance_grounding_serialized(
    audit: SeedanceInputManifestAuditV1,
) -> SeedanceInputManifestAuditV1:
    grounding_audit = audit.grounding_audit
    if grounding_audit is None:
        return audit
    return audit.model_copy(
        update={
            "grounding_audit": grounding_audit.model_copy(
                update={"serialized": grounding_audit.delivered}
            )
        }
    )


def mark_seedance_grounding_submitted(
    audit: SeedanceInputManifestAuditV1,
) -> SeedanceInputManifestAuditV1:
    grounding_audit = audit.grounding_audit
    if grounding_audit is None:
        return audit
    serialized = grounding_audit.serialized
    return audit.model_copy(
        update={
            "grounding_audit": grounding_audit.model_copy(update={"submitted": serialized})
        }
    )
