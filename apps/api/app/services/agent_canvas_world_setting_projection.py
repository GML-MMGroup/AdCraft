"""Resolve immutable, role-scoped World Setting projections."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Protocol, cast

from pydantic import ValidationError

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_world_setting_repository import (
    AgentCanvasWorldSettingRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import ResolvedTextBindingInputV2
from app.schemas.agent_canvas_creative_session import GuidedSessionStateV2
from app.schemas.agent_canvas_world_setting import (
    ResolvedWorldSettingInputV1,
    SharedWorldSettingProjectionV1,
    WorldSettingProjectionAudienceV1,
    WorldSettingProjectionContextV1,
    WorldSettingProjectionSnapshotV1,
    WorldSettingReadyProjectionBundleV1,
)


class WorldSettingProjectionGateway(Protocol):
    def project_world_setting(
        self,
        content: str,
        *,
        audience: WorldSettingProjectionAudienceV1,
        workflow_id: str | None = None,
    ) -> WorldSettingReadyProjectionBundleV1: ...


class WorldSettingProjectionService:
    """Resolve guidance and exact run-frozen World Setting projections."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        projections: AgentCanvasWorldSettingRepository,
        *,
        gateway: WorldSettingProjectionGateway | None = None,
        model_ref_resolver: Callable[[], str] | None = None,
        runtime_manifest_path: Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._workflows = workflows
        self._projections = projections
        self._gateway = gateway
        self._model_ref_resolver = model_ref_resolver or (lambda: "unavailable:text:model")
        self._runtime_manifest_path = runtime_manifest_path or (
            Path(__file__).resolve().parents[2]
            / "agent"
            / "src"
            / "generated"
            / "runtime-manifest.json"
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def resolve_for_guidance(
        self,
        *,
        workflow_id: str,
        session: GuidedSessionStateV2,
        audience: WorldSettingProjectionAudienceV1,
    ) -> WorldSettingProjectionContextV1 | None:
        topics = tuple(
            topic
            for topic in session.topics
            if topic.topic_kind == "world_setting" and topic.status == "selected"
        )
        if not topics:
            return None
        if len(topics) != 1 or len(topics[0].related_node_ids) != 1:
            raise _resolution_error("Selected World Setting source is ambiguous.")
        node = self._workflows.get_node(workflow_id, topics[0].related_node_ids[0])
        if (
            node.node_type != "text"
            or node.creative_role != "world_setting"
            or node.status != "ready"
        ):
            raise _resolution_error("Selected World Setting Text Node is not Ready.")
        snapshots = self._projections.find_for_source(
            source_node_id=node.node_id,
            source_node_revision=node.revision,
        )
        if not snapshots:
            raise _resolution_error("Selected World Setting projection is unavailable.")
        return self._context(snapshots[-1], audience)

    def resolve_for_run(
        self,
        *,
        workflow_id: str,
        source: ResolvedTextBindingInputV2,
    ) -> ResolvedWorldSettingInputV1:
        """Resolve or build one projection for an immutable text snapshot."""

        audience = _validated_audience(source.binding_metadata)
        model_ref, prompt_digest, skill_digest, compiler_digest = self._compiler_identity()
        snapshot = self._projections.find_matching(
            source_node_id=source.source_node_id,
            source_node_revision=source.source_node_revision,
            source_content_digest=source.content_digest,
            compiler_digest=compiler_digest,
        )
        if snapshot is None:
            snapshot = self._build_snapshot(
                workflow_id=workflow_id,
                source=source,
                audience=audience,
                model_ref=model_ref,
                prompt_digest=prompt_digest,
                skill_digest=skill_digest,
                compiler_digest=compiler_digest,
            )
            snapshot = self._projections.insert(snapshot)
        return ResolvedWorldSettingInputV1(
            binding_id=source.binding_id,
            source_node_id=source.source_node_id,
            source_node_revision=source.source_node_revision,
            source_content_digest=source.content_digest,
            required=source.required,
            display_order=source.display_order,
            projection_audience=audience,
            projection_contract_version=snapshot.projection_contract_version,
            projection_snapshot_id=snapshot.projection_snapshot_id,
            projection_digest=snapshot.projection_digest,
            projection_mode=snapshot.projection_mode,
            warning_code=snapshot.warning_code,
        )

    def materialize(
        self,
        resolved: ResolvedWorldSettingInputV1,
    ) -> WorldSettingProjectionContextV1:
        snapshot = self._projections.get(resolved.projection_snapshot_id)
        if (
            snapshot.source_node_id != resolved.source_node_id
            or snapshot.source_node_revision != resolved.source_node_revision
            or snapshot.source_content_digest != resolved.source_content_digest
            or snapshot.projection_digest != resolved.projection_digest
            or snapshot.projection_mode != resolved.projection_mode
        ):
            raise _resolution_error("Frozen World Setting projection identity is inconsistent.")
        return self._context(snapshot, resolved.projection_audience)

    def _compiler_identity(self) -> tuple[str, str, str, str]:
        try:
            manifest = json.loads(self._runtime_manifest_path.read_text(encoding="utf-8"))
            prompt_digest = _required_digest(manifest, "prompt_digest")
            skill_digest = _required_digest(manifest, "skill_digest")
            model_ref = self._model_ref_resolver()
            if not model_ref.strip():
                raise ValueError("model_ref is empty")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise _resolution_error(
                "World Setting projection compiler identity is unavailable."
            ) from error
        compiler_digest = _digest(
            {
                "contract_version": "world-setting-projection-v1",
                "model_ref": model_ref,
                "prompt_digest": prompt_digest,
                "skill_digest": skill_digest,
            }
        )
        return model_ref, prompt_digest, skill_digest, compiler_digest

    def _build_snapshot(
        self,
        *,
        workflow_id: str,
        source: ResolvedTextBindingInputV2,
        audience: WorldSettingProjectionAudienceV1,
        model_ref: str,
        prompt_digest: str,
        skill_digest: str,
        compiler_digest: str,
    ) -> WorldSettingProjectionSnapshotV1:
        try:
            if self._gateway is None:
                raise RuntimeError("World Setting projection gateway is unavailable.")
            bundle = WorldSettingReadyProjectionBundleV1.model_validate(
                self._gateway.project_world_setting(
                    source.content,
                    audience=audience,
                    workflow_id=workflow_id,
                )
            )
            shared = bundle.shared
            role_projections = (
                bundle.script_writer,
                bundle.product_designer,
                bundle.prop_designer,
                bundle.character_designer,
                bundle.scene_designer,
                bundle.storyboard_artist,
                bundle.video_director,
                bundle.bgm_director,
            )
            projection_mode = "ready"
            warning_code = None
        except Exception:
            try:
                shared = _shared_fallback(source.content)
                role_projections = ()
                projection_mode = "fallback"
                warning_code = "world_setting_projection_fallback"
            except (TypeError, ValueError, ValidationError) as error:
                raise _resolution_error(
                    "World Setting projection and bounded fallback are unavailable."
                ) from error
        projection_payload = {
            "shared": shared.model_dump(mode="json"),
            "role_projections": [item.model_dump(mode="json") for item in role_projections],
            "projection_mode": projection_mode,
        }
        projection_digest = _digest(projection_payload)
        snapshot_identity = {
            "source_node_id": source.source_node_id,
            "source_node_revision": source.source_node_revision,
            "source_content_digest": source.content_digest,
            "compiler_digest": compiler_digest,
            "projection_digest": projection_digest,
        }
        return WorldSettingProjectionSnapshotV1(
            projection_snapshot_id=f"world_projection_{_digest(snapshot_identity)[:24]}",
            workflow_id=workflow_id,
            source_node_id=source.source_node_id,
            source_node_revision=source.source_node_revision,
            source_content_digest=source.content_digest,
            projection_contract_version="world-setting-projection-v1",
            projection_prompt_digest=prompt_digest,
            projection_skill_digest=skill_digest,
            model_ref=model_ref,
            compiler_digest=compiler_digest,
            projection_mode=projection_mode,
            shared_projection=shared,
            role_projections=role_projections,
            projection_digest=projection_digest,
            warning_code=warning_code,
            created_at=self._clock(),
        )

    @staticmethod
    def _context(
        snapshot: WorldSettingProjectionSnapshotV1,
        audience: WorldSettingProjectionAudienceV1,
    ) -> WorldSettingProjectionContextV1:
        role_projection = next(
            (item for item in snapshot.role_projections if item.audience == audience),
            None,
        )
        if snapshot.projection_mode == "ready" and audience != "shared" and role_projection is None:
            raise _resolution_error("Selected World Setting role projection is unavailable.")
        return WorldSettingProjectionContextV1(
            source_node_id=snapshot.source_node_id,
            source_node_revision=snapshot.source_node_revision,
            source_content_digest=snapshot.source_content_digest,
            projection_snapshot_id=snapshot.projection_snapshot_id,
            projection_digest=snapshot.projection_digest,
            projection_mode=snapshot.projection_mode,
            projection_audience=audience,
            shared=snapshot.shared_projection,
            role_projection=role_projection,
            warning_code=snapshot.warning_code,
        )


def _validated_audience(metadata: dict[str, object]) -> WorldSettingProjectionAudienceV1:
    if (
        metadata.get("context_kind") != "world_setting"
        or metadata.get("projection_contract_version") != "world-setting-projection-v1"
    ):
        raise _resolution_error("World Setting Binding metadata is invalid.")
    audience = str(metadata.get("projection_audience") or "")
    allowed = {
        "shared",
        "script_writer",
        "product_designer",
        "prop_designer",
        "character_designer",
        "scene_designer",
        "storyboard_artist",
        "video_director",
        "bgm_director",
    }
    if audience not in allowed:
        raise _resolution_error("World Setting projection audience is unsupported.")
    return cast(WorldSettingProjectionAudienceV1, audience)


def _shared_fallback(content: str) -> SharedWorldSettingProjectionV1:
    premise = " ".join(content.split())[:1_024]
    return SharedWorldSettingProjectionV1(
        premise=premise,
        era_and_location=(
            "Preserve the era and location implied only by the bounded premise above."
        ),
        continuity_rules=(
            "Keep established world facts consistent across every connected output.",
            "Do not introduce conflicting physical or social rules.",
            "Preserve recurring locations, materials, and environmental behavior.",
        ),
    )


def _required_digest(manifest: object, key: str) -> str:
    if not isinstance(manifest, dict):
        raise ValueError("runtime manifest must be an object")
    value = str(manifest.get(key) or "")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{key} is invalid")
    return value


def _digest(value: object) -> str:
    payload = (
        value
        if isinstance(value, str)
        else json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolution_error(message: str) -> V2PersistenceError:
    error = V2PersistenceError(
        "world_setting_projection_unavailable",
        message,
        stage="world_setting_projection_service",
    )
    error.details = {"retryable": True}
    return error
