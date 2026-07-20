from __future__ import annotations

import hashlib
import json
from typing import Any

from app.schemas.workflow_v2_prompt_registry import (
    V2PromptLineage,
    V2PromptRegistryEntry,
    V2PromptRegistryRef,
    V2PromptRenderIdentity,
    V2PromptRenderResult,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text


PROVIDER_SLOT_PROMPT_IDS: dict[str, str] = {
    "product_main_image": "v2.provider.product_main_image.v1",
    "product_multi_view_grid": "v2.provider.product_multi_view_grid.v1",
    "character_main_image": "v2.provider.character_main_image.v1",
    "character_three_view": "v2.provider.character_three_view.v1",
    "scene_main_image": "v2.provider.scene_main_image.v1",
    "scene_multi_view_grid": "v2.provider.scene_multi_view_grid.v1",
    "shot_video_segment": "v2.provider.shot_video_segment.v1",
    "bgm_audio": "v2.provider.bgm_audio.v1",
    "final_video": "v2.provider.final_video.v1",
    "free_output": "v2.provider.free_output.v1",
}


PROVIDER_SLOT_OWNERS: dict[str, str] = {
    "product_main_image": "product_designer",
    "product_multi_view_grid": "product_designer",
    "character_main_image": "character_designer",
    "character_three_view": "character_designer",
    "scene_main_image": "scene_designer",
    "scene_multi_view_grid": "scene_designer",
    "shot_video_segment": "video_director",
    "bgm_audio": "sound_director",
    "final_video": "composition_tool",
    "free_output": "quick_image_generator",
}


class V2PromptRegistry:
    def __init__(self, entries: list[V2PromptRegistryEntry] | None = None) -> None:
        self._entries = {entry.prompt_id: entry for entry in (entries or _default_entries())}

    def get(self, prompt_id: str) -> V2PromptRegistryEntry:
        try:
            return self._entries[prompt_id]
        except KeyError as exc:
            raise KeyError(f"Unknown V2 prompt registry id: {prompt_id}") from exc

    def ref_for_provider_slot(self, slot_type: str) -> V2PromptRegistryRef:
        prompt_id = provider_prompt_id_for_slot(slot_type)
        if prompt_id not in self._entries:
            self._entries[prompt_id] = _provider_entry(prompt_id=prompt_id, slot_type=slot_type)
        return self.ref_for_prompt_id(prompt_id)

    def ref_for_prompt_id(self, prompt_id: str) -> V2PromptRegistryRef:
        entry = self.get(prompt_id)
        return V2PromptRegistryRef(
            prompt_id=entry.prompt_id,
            prompt_version=entry.prompt_version,
            owner=entry.owner,
            scope=entry.scope,
            stage=entry.stage,
            source_path=entry.source_path,
        )

    def render_result_for_provider_slot(
        self,
        *,
        slot_type: str,
        provider_prompt: str | None,
        render_context: dict[str, Any],
        workflow_id: str | None = None,
        node_id: str | None = None,
        item_id: str | None = None,
        slot_id: str | None = None,
        media_type: str | None = None,
        specialist: str | None = None,
        path_kind: str = "normal",
    ) -> V2PromptRenderResult:
        ref = self.ref_for_provider_slot(slot_type)
        identity = V2PromptRenderIdentity(
            workflow_id=workflow_id,
            node_id=node_id,
            item_id=item_id,
            slot_id=slot_id,
            slot_type=slot_type,
            media_type=media_type,
            specialist=specialist,
            path_kind=path_kind,
        )
        return V2PromptRenderResult(
            prompt_registry_ref=ref,
            render_identity=identity,
            prompt_text=provider_prompt or "",
            prompt_hash=stable_hash({"provider_prompt": provider_prompt or ""}),
            render_context_hash=stable_hash(render_context),
        )

    def render_result_for_prompt_id(
        self,
        *,
        prompt_id: str,
        rendered_prompt: str | None,
        render_context: dict[str, Any],
        workflow_id: str | None = None,
        node_id: str | None = None,
        item_id: str | None = None,
        slot_id: str | None = None,
        slot_type: str | None = None,
        media_type: str | None = None,
        specialist: str | None = None,
        path_kind: str = "normal",
    ) -> V2PromptRenderResult:
        ref = self.ref_for_prompt_id(prompt_id)
        identity = V2PromptRenderIdentity(
            workflow_id=workflow_id,
            node_id=node_id,
            item_id=item_id,
            slot_id=slot_id,
            slot_type=slot_type,
            media_type=media_type,
            specialist=specialist,
            path_kind=path_kind,
        )
        return V2PromptRenderResult(
            prompt_registry_ref=ref,
            render_identity=identity,
            prompt_text=rendered_prompt or "",
            prompt_hash=stable_hash({"rendered_prompt": rendered_prompt or ""}),
            render_context_hash=stable_hash(render_context),
        )

    def lineage_for_render(self, result: V2PromptRenderResult) -> V2PromptLineage:
        ref = result.prompt_registry_ref
        identity = result.render_identity
        return V2PromptLineage(
            prompt_registry_ref=ref.model_dump(mode="json"),
            prompt_id=ref.prompt_id,
            prompt_version=ref.prompt_version,
            workflow_id=identity.workflow_id,
            node_id=identity.node_id,
            item_id=identity.item_id,
            slot_id=identity.slot_id,
            slot_type=identity.slot_type,
            media_type=identity.media_type,
            specialist=identity.specialist,
            path_kind=identity.path_kind,
            prompt_hash=result.prompt_hash,
            render_context_hash=result.render_context_hash,
            source_path=ref.source_path,
            owner=ref.owner,
            scope=ref.scope,
            stage=ref.stage,
        )


def provider_prompt_id_for_slot(slot_type: str | None) -> str:
    normalized = str(slot_type or "").strip()
    if normalized.startswith("shot_cell_"):
        return "v2.provider.shot_cell.v1"
    return PROVIDER_SLOT_PROMPT_IDS.get(normalized, f"v2.provider.{normalized or 'unknown'}.v1")


def stable_hash(payload: Any) -> str:
    sanitized = sanitize_context_for_llm_text(payload)
    serialized = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _default_entries() -> list[V2PromptRegistryEntry]:
    entries: list[V2PromptRegistryEntry] = []
    entries.extend(
        [
            V2PromptRegistryEntry(
                prompt_id="v2.script_writer.plan.v1",
                prompt_version="1.0.0",
                owner="script_writer",
                scope="specialist_prompt",
                stage="script_writer",
                source_path="app/services/v2_runtime_prompt_packs.py",
                output_schema="V2ScriptPlan",
                title="V2 script writer plan prompt",
            ),
            V2PromptRegistryEntry(
                prompt_id="v2.expert_brief.plan.v1",
                prompt_version="1.0.0",
                owner="director",
                scope="specialist_prompt",
                stage="expert_brief",
                source_path="app/services/v2_runtime_prompt_packs.py",
                output_schema="V2ExpertBriefPlan",
                title="V2 expert brief planner prompt",
            ),
            V2PromptRegistryEntry(
                prompt_id="v2.specialist.materializer.v1",
                prompt_version="1.0.0",
                owner="director",
                scope="specialist_prompt",
                stage="specialist_materializer",
                source_path="app/services/v2_runtime_prompt_packs.py",
                output_schema="V2SpecialistPromptResult",
                title="V2 specialist materializer prompt",
            ),
            V2PromptRegistryEntry(
                prompt_id="v2.storyboard.detail.v1",
                prompt_version="1.0.0",
                owner="storyboard_artist",
                scope="storyboard_detail",
                stage="storyboard_detail_prompts",
                source_path="app/services/v2_high_risk_prompt_packs.py",
                output_schema="V2StoryboardDetailPlan",
                title="V2 storyboard detail prompt",
            ),
            V2PromptRegistryEntry(
                prompt_id="v2.repair.structured_generation.v1",
                prompt_version="1.0.0",
                owner="director",
                scope="repair_prompt",
                stage="repair",
                source_path="app/services/v2_high_risk_prompt_packs.py",
                output_schema="structured_generation_repair",
                title="V2 structured generation repair prompt",
            ),
            V2PromptRegistryEntry(
                prompt_id="v2.fallback.deterministic_generation.v1",
                prompt_version="1.0.0",
                owner="director",
                scope="fallback_prompt",
                stage="fallback",
                source_path="app/services/v2_high_risk_prompt_packs.py",
                output_schema="deterministic_fallback",
                allowed_runtime=["mock"],
                title="V2 deterministic fallback prompt",
            ),
        ]
    )
    for slot_type, prompt_id in sorted(PROVIDER_SLOT_PROMPT_IDS.items()):
        entries.append(_provider_entry(prompt_id=prompt_id, slot_type=slot_type))
    entries.append(_provider_entry(prompt_id="v2.provider.shot_cell.v1", slot_type="shot_cell"))
    return entries


def _provider_entry(*, prompt_id: str, slot_type: str) -> V2PromptRegistryEntry:
    owner = PROVIDER_SLOT_OWNERS.get(slot_type, "storyboard_artist")
    if slot_type == "shot_cell":
        owner = "storyboard_artist"
    return V2PromptRegistryEntry(
        prompt_id=prompt_id,
        prompt_version="1.0.0",
        owner=owner,
        scope="provider_payload",
        stage="provider_payload",
        source_path="app/services/v2_runtime_prompt_packs.py",
        output_schema="V2CanonicalProviderPayload",
        title=f"V2 provider prompt for {slot_type}",
        description="Registered provider-bound prompt compiled from the V2 prompt contract service.",
        metadata={"slot_type": slot_type},
    )
