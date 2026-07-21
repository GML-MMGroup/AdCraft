from __future__ import annotations

from app.schemas.workflow_v2_provider_prompt_contracts import (
    V2ProviderPromptContract,
    V2ProviderPromptContractResult,
)
from app.schemas.workflow_v2_prompt_registry import V2PromptRenderResult
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_high_risk_prompt_renderer import V2HighRiskPromptRenderer
from app.services.v2_prompt_registry import provider_prompt_id_for_slot


class V2ProviderPromptContractRegistry:
    def __init__(self) -> None:
        self._contracts = _build_contracts()

    def get(self, slot_type: str, media_type: str | None = None) -> V2ProviderPromptContract:
        if slot_type.startswith("shot_cell_"):
            return self._contracts["shot_cell_*"]
        contract = self._contracts.get(slot_type)
        if contract is not None:
            return contract
        resolved_media_type = media_type or ("video" if "video" in slot_type else "image")
        return V2ProviderPromptContract(
            contract_id=f"{slot_type.replace('_', '-')}-provider-contract-v1",
            slot_type=slot_type,
            media_type=resolved_media_type,
            primary_goal=f"Generate one {resolved_media_type} output for {slot_type}.",
            required_prompt_clauses=[f"Generate only the requested {slot_type} output."],
            negative_constraints=["no watermark", "no unrelated content"],
            forbidden_terms=["watermark", "unrelated content"],
            warning_only_quality_flags=["possible_visual_drift"],
            technical_failure_rules=["provider_output_missing"],
        )


class V2ProviderPromptContractService:
    def __init__(self, registry: V2ProviderPromptContractRegistry | None = None) -> None:
        self._registry = registry or V2ProviderPromptContractRegistry()
        self._prompt_renderer = V2HighRiskPromptRenderer()

    def compile_contract_prompt(
        self,
        *,
        slot_type: str,
        media_type: str | None,
        slot_prompt: str | None,
        reference_asset_ids: list[str],
    ) -> V2ProviderPromptContractResult:
        contract = self._registry.get(slot_type, media_type=media_type)
        base_prompt = (slot_prompt or "").strip() or f"Generate media for {slot_type}."
        sections = [
            base_prompt,
            f"Primary goal: {contract.primary_goal}",
            *contract.required_prompt_clauses,
        ]
        if contract.reference_instruction_template and reference_asset_ids:
            sections.append(contract.reference_instruction_template)
        if contract.negative_constraints:
            sections.append("Negative constraints: " + "; ".join(contract.negative_constraints))
        render_result = self._prompt_renderer.render(
            prompt_id=provider_prompt_id_for_slot(slot_type),
            context={"sections": sections},
            identity={
                "slot_type": slot_type,
                "media_type": contract.media_type,
                "path_kind": "normal",
            },
        )
        provider_prompt = render_result.prompt_text
        payload = contract.model_dump(mode="json")
        payload["reference_asset_ids"] = list(reference_asset_ids)
        payload["prompt_rendered_by_registry"] = True
        payload["prompt_registry_ref"] = render_result.prompt_registry_ref.model_dump(mode="json")
        payload["prompt_lineage"] = _prompt_lineage(render_result)
        if isinstance(render_result.metadata.get("prompt_content_profile"), dict):
            payload["prompt_content_profile"] = render_result.metadata["prompt_content_profile"]
        return V2ProviderPromptContractResult(
            provider_prompt=provider_prompt,
            provider_prompt_contract=sanitize_context_for_llm_text(payload),
            negative_constraints=list(contract.negative_constraints),
        )


def _build_contracts() -> dict[str, V2ProviderPromptContract]:
    image_warning_flags = [
        "possible_identity_drift",
        "possible_scene_drift",
        "weak_provider_reference_support",
    ]
    technical_failures = [
        "required_source_asset_missing",
        "required_source_asset_unreadable",
        "provider_output_missing",
        "provider_generation_failed",
    ]
    no_label_constraints = [
        "no text labels",
        "no captions",
        "no UI overlays",
        "no diagram-style annotations",
        "no watermarks",
    ]
    return {
        "product_main_image": V2ProviderPromptContract(
            contract_id="product-main-image-provider-contract-v1",
            slot_type="product_main_image",
            media_type="image",
            primary_goal="Generate one clean product-only hero/reference image.",
            required_prompt_clauses=[
                "The output is a product-only image.",
                "Show one clear product hero/reference asset with no human figures or narrative activity.",
            ],
            negative_constraints=[
                "no human figures",
                "no hand interaction",
                "no unrelated products",
                "no unrelated lifestyle scene",
                *no_label_constraints,
            ],
            forbidden_terms=["people", "story action", "unrelated product", "labels", "overlays"],
            warning_only_quality_flags=image_warning_flags,
            technical_failure_rules=technical_failures,
        ),
        "product_multi_view_grid": V2ProviderPromptContract(
            contract_id="product-multi-view-grid-provider-contract-v1",
            slot_type="product_multi_view_grid",
            media_type="image",
            primary_goal="Generate multiple views of the same product.",
            required_prompt_clauses=[
                "The selected product main image is the primary visual source of truth.",
                "Preserve product silhouette, material finish, color, proportions, logo placement when applicable, camera or module layout when applicable, and packaging relationship when applicable.",
                "Show multiple camera views of the same product without changing product identity.",
            ],
            reference_instruction_template=(
                "Use the selected product_main_image reference as the primary product identity reference."
            ),
            negative_constraints=[
                "no human figures",
                "no unrelated products",
                "no contact-sheet text",
                *no_label_constraints,
            ],
            forbidden_terms=[
                "different product",
                "captions",
                "UI overlays",
                "contact-sheet labels",
                "annotated diagrams",
            ],
            warning_only_quality_flags=image_warning_flags,
            technical_failure_rules=technical_failures,
        ),
        "character_main_image": V2ProviderPromptContract(
            contract_id="character-main-image-provider-contract-v1",
            slot_type="character_main_image",
            media_type="image",
            primary_goal="Generate one single character-only reference image.",
            required_prompt_clauses=[
                "The output is a single character-only image.",
                "Present one reusable character reference without product handling or narrative activity.",
            ],
            negative_constraints=[
                "no products",
                "no full environment scene",
                "no second character",
                "no narrative activity",
                *no_label_constraints,
            ],
            forbidden_terms=["products", "second character", "story action", "labels", "overlays"],
            warning_only_quality_flags=image_warning_flags,
            technical_failure_rules=technical_failures,
        ),
        "character_three_view": V2ProviderPromptContract(
            contract_id="character-three-view-provider-contract-v1",
            slot_type="character_three_view",
            media_type="image",
            primary_goal="Generate front, side, and back views of the same character.",
            required_prompt_clauses=[
                "The selected character main image is the primary visual source of truth.",
                "Generate front, side, and back views of the same character.",
                "Preserve face identity, hairstyle, hair color, body proportions, age impression, outfit silhouette, clothing colors, and accessories.",
            ],
            reference_instruction_template=(
                "Use the selected main image as the primary visual identity reference. "
                "Create front, side, and back views of the exact same person from the reference image. "
                "Preserve the same face, hairstyle, body proportions, clothing type, clothing color, and overall visual style. "
                "Do not replace the outfit. "
                "Do not add a suit or jacket unless it appears in the main image. "
                "Do not change from photorealistic to illustration. "
                "Do not change from illustration to photorealistic."
            ),
            negative_constraints=[
                "no different person",
                "no gender change",
                "no age impression change",
                "no hairstyle change",
                "no wardrobe change",
                "no body type change",
                *no_label_constraints,
            ],
            forbidden_terms=[
                "different person",
                "changing gender",
                "changing hairstyle",
                "labels",
                "overlays",
            ],
            warning_only_quality_flags=image_warning_flags,
            technical_failure_rules=technical_failures,
        ),
        "scene_main_image": V2ProviderPromptContract(
            contract_id="scene-main-image-provider-contract-v1",
            slot_type="scene_main_image",
            media_type="image",
            primary_goal="Generate one reusable environment-only image.",
            required_prompt_clauses=[
                "The output is an environment-only image.",
                "Include spatial layout, environment type or architecture, materials, lighting direction, color palette, time of day, and atmosphere.",
                "Use clean environment framing without human figures, product manipulation, or narrative activity.",
            ],
            negative_constraints=[
                "no foreground human figures",
                "no named characters",
                "no product manipulation",
                "no narrative activity",
                "no text marker overlays",
                "no composition text",
                *no_label_constraints,
            ],
            forbidden_terms=[
                "foreground people",
                "named characters",
                "product interaction",
                "composition labels",
                "diagram annotations",
            ],
            warning_only_quality_flags=image_warning_flags,
            technical_failure_rules=technical_failures,
        ),
        "scene_multi_view_grid": V2ProviderPromptContract(
            contract_id="scene-multi-view-grid-provider-contract-v1",
            slot_type="scene_multi_view_grid",
            media_type="image",
            primary_goal="Generate multiple camera angles of the same environment.",
            required_prompt_clauses=[
                "The selected scene main image is the primary visual source of truth.",
                "Generate multiple camera angles of the same environment.",
                "Preserve spatial layout, architecture, materials, lighting direction, color palette, major objects, and atmosphere.",
            ],
            reference_instruction_template=(
                "Use the selected scene_main_image reference as the primary environment layout reference."
            ),
            negative_constraints=[
                "no different location",
                "no named characters",
                "no product action",
                "no text marker overlays",
                "no view text",
                *no_label_constraints,
            ],
            forbidden_terms=[
                "different location",
                "named characters",
                "product action",
                "view labels",
                "annotated diagrams",
            ],
            warning_only_quality_flags=image_warning_flags,
            technical_failure_rules=technical_failures,
        ),
        "shot_cell_*": V2ProviderPromptContract(
            contract_id="storyboard-cell-provider-contract-v1",
            slot_type="shot_cell_*",
            media_type="image",
            primary_goal="Generate one single full-frame keyframe for the current shot cell.",
            required_prompt_clauses=[
                "Generate one single full-frame keyframe for the current shot cell.",
                "Use selected product, character, and scene references as visual continuity sources when available and relevant.",
                "Preserve product identity, preserve character identity, preserve environment identity, lighting continuity, and camera progression.",
            ],
            reference_instruction_template=(
                "Use selected product, character, and scene assets as continuity references for this shot cell."
            ),
            negative_constraints=[
                "no collage output",
                "no storyboard sheets",
                "no contact sheets",
                "no split screens",
                "no unrelated products",
                "no unrelated characters",
                "no unrelated locations",
                *no_label_constraints,
            ],
            forbidden_terms=[
                "collage",
                "storyboard sheet",
                "contact sheet",
                "split screen",
                "watermark",
            ],
            warning_only_quality_flags=image_warning_flags,
            technical_failure_rules=technical_failures,
        ),
        "shot_video_segment": V2ProviderPromptContract(
            contract_id="storyboard-video-provider-contract-v1",
            slot_type="shot_video_segment",
            media_type="video",
            primary_goal="Generate a video segment from the selected shot cell image sequence.",
            required_prompt_clauses=[
                "Use the selected shot cell images for the same shot as the primary visual progression source.",
                "Include shot video content, camera/action timeline, dialogue constraints when present, audio description when present, duration, and aspect ratio.",
                "Preserve product, character, environment, lighting, and camera continuity across the selected cell images.",
            ],
            reference_instruction_template=(
                "The selected shot cell images are required visual references for this video segment."
            ),
            negative_constraints=[
                "no unrelated characters",
                "no unrelated products",
                "no unrelated locations",
                "no subtitles",
                "no watermarks",
                "no static slide-show motion",
            ],
            forbidden_terms=[
                "unrelated characters",
                "unrelated products",
                "unrelated locations",
                "subtitles",
                "watermarks",
            ],
            warning_only_quality_flags=["possible_motion_drift", "weak_provider_reference_support"],
            technical_failure_rules=[
                "v2_provider_reference_file_missing",
                "v2_required_shot_cell_reference_missing",
                *technical_failures,
            ],
        ),
        "bgm_audio": V2ProviderPromptContract(
            contract_id="bgm-audio-provider-contract-v1",
            slot_type="bgm_audio",
            media_type="audio",
            primary_goal="Compile an audio-only instrumental music prompt.",
            required_prompt_clauses=[
                "Create instrumental music only.",
                "Include mood, pace, energy, duration, and commercial fit.",
            ],
            negative_constraints=["no vocals", "no lyrics", "no image reference text"],
            forbidden_terms=["vocals", "lyrics", "image prompt", "video prompt"],
            warning_only_quality_flags=["possible_audio_mood_drift"],
            technical_failure_rules=["provider_output_missing", "provider_generation_failed"],
        ),
        "final_video": V2ProviderPromptContract(
            contract_id="final-composition-provider-contract-v1",
            slot_type="final_video",
            media_type="video",
            primary_goal="Assemble selected timeline media with deterministic media tooling.",
            required_prompt_clauses=[
                "Use deterministic timeline assembly.",
                "Do not route final composition through an LLM image or video generation provider.",
            ],
            negative_constraints=["no synthetic fallback media", "no missing timeline segments"],
            forbidden_terms=["LLM image generation", "LLM video generation"],
            warning_only_quality_flags=[],
            technical_failure_rules=[
                "required_timeline_asset_missing",
                "composition_output_missing",
            ],
        ),
    }


def _join_sections(sections: list[str]) -> str:
    cleaned = [section.strip() for section in sections if section and section.strip()]
    return "\n\n".join(dict.fromkeys(cleaned))


def _prompt_lineage(render_result: V2PromptRenderResult) -> dict[str, object]:
    ref = render_result.prompt_registry_ref
    identity = render_result.render_identity
    return {
        "prompt_registry_ref": ref.model_dump(mode="json"),
        "prompt_id": ref.prompt_id,
        "prompt_version": ref.prompt_version,
        "workflow_id": identity.workflow_id,
        "node_id": identity.node_id,
        "item_id": identity.item_id,
        "slot_id": identity.slot_id,
        "slot_type": identity.slot_type,
        "media_type": identity.media_type,
        "specialist": identity.specialist,
        "path_kind": identity.path_kind,
        "prompt_hash": render_result.prompt_hash,
        "render_context_hash": render_result.render_context_hash,
        "source_path": ref.source_path,
        "owner": ref.owner,
        "scope": ref.scope,
        "stage": ref.stage,
    }
