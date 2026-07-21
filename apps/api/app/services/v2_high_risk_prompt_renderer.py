from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.schemas.workflow_v2_prompt_registry import (
    V2PromptRenderIdentity,
    V2PromptRenderResult,
)
from app.services.llm_context_sanitizer import sanitize_context_for_llm_text
from app.services.v2_high_risk_prompt_packs import (
    prompt_content_profile_metadata,
    prompt_pack_for,
)
from app.services.v2_prompt_registry import V2PromptRegistry, stable_hash


class V2HighRiskPromptRenderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.metadata = sanitize_context_for_llm_text(metadata or {})


class V2HighRiskPromptRenderer:
    def __init__(self, registry: V2PromptRegistry | None = None) -> None:
        self._registry = registry or V2PromptRegistry()

    def render(
        self,
        *,
        prompt_id: str,
        context: Mapping[str, Any],
        identity: V2PromptRenderIdentity | Mapping[str, Any],
    ) -> V2PromptRenderResult:
        try:
            ref = self._registry.ref_for_prompt_id(prompt_id)
        except KeyError as exc:
            raise V2HighRiskPromptRenderError(
                "v2_runtime_prompt_unregistered",
                f"High-risk V2 prompt is not registered: {prompt_id}",
                metadata={"prompt_id": prompt_id},
            ) from exc
        pack = prompt_pack_for(prompt_id)
        if pack is None:
            raise V2HighRiskPromptRenderError(
                "v2_runtime_prompt_pack_missing",
                f"High-risk V2 prompt pack is missing: {prompt_id}",
                metadata={
                    "prompt_id": ref.prompt_id,
                    "owner": ref.owner,
                    "scope": ref.scope,
                    "stage": ref.stage,
                },
            )
        context_payload = dict(context)
        missing = [
            key
            for key in pack.required_context_keys
            if key not in context_payload or context_payload.get(key) in (None, "", [])
        ]
        if missing:
            raise V2HighRiskPromptRenderError(
                "v2_runtime_prompt_render_failed",
                f"High-risk V2 prompt render context is missing required keys: {', '.join(missing)}",
                metadata={
                    "prompt_id": ref.prompt_id,
                    "owner": ref.owner,
                    "scope": ref.scope,
                    "stage": ref.stage,
                    "missing_context_keys": missing,
                },
            )
        try:
            prompt_text = pack.render(context_payload).strip()
        except Exception as exc:  # noqa: BLE001 - render failures become stable errors.
            raise V2HighRiskPromptRenderError(
                "v2_runtime_prompt_render_failed",
                f"High-risk V2 prompt render failed: {prompt_id}",
                metadata={
                    "prompt_id": ref.prompt_id,
                    "owner": ref.owner,
                    "scope": ref.scope,
                    "stage": ref.stage,
                },
            ) from exc
        if not prompt_text:
            raise V2HighRiskPromptRenderError(
                "v2_runtime_prompt_render_failed",
                f"High-risk V2 prompt rendered empty text: {prompt_id}",
                metadata={
                    "prompt_id": ref.prompt_id,
                    "owner": ref.owner,
                    "scope": ref.scope,
                    "stage": ref.stage,
                    "missing_context_keys": ["prompt_text"],
                },
            )
        identity_model = (
            identity
            if isinstance(identity, V2PromptRenderIdentity)
            else V2PromptRenderIdentity.model_validate(dict(identity))
        )
        profile_metadata = prompt_content_profile_metadata(
            prompt_id=ref.prompt_id,
            prompt_text=prompt_text,
        )
        metadata = {
            "owner": ref.owner,
            "scope": ref.scope,
            "stage": ref.stage,
            "source_path": ref.source_path,
            "path_kind": identity_model.path_kind,
        }
        if profile_metadata is not None:
            metadata["prompt_content_profile"] = profile_metadata
        return V2PromptRenderResult(
            prompt_registry_ref=ref,
            render_identity=identity_model,
            prompt_text=prompt_text,
            prompt_hash=stable_hash({"prompt_text": prompt_text}),
            render_context_hash=stable_hash(context_payload),
            metadata=metadata,
        )
