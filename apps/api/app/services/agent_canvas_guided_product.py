"""Typed guided Product source input orchestration."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import select

from app.persistence.agent_canvas_guided_product_repository import (
    AgentCanvasGuidedProductRepository,
    request_digest,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import AgentCanvasGuidanceSessionRow
from app.schemas.agent_canvas import CanvasNodeV2, CanvasPositionV2
from app.schemas.agent_canvas_guided_product import (
    GuidedProductInputCommitRequestV1,
    GuidedProductInputCommitResponseV1,
    ProductUploadCompilationProvenanceV1,
    ProductUploadInputProvenanceV1,
)
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_assets import AgentCanvasAssetService
from app.services.product_upload_multiview_compiler import (
    ProductUploadMultiviewCompilationError,
    ProductUploadMultiviewCompiler,
    ProductUploadMultiviewInput,
)
from app.services.v2_final_composition_renderer import V2MediaProbe


class GuidedProductInputCommitService:
    """Validate and materialize uploaded Product source nodes without Agent calls."""

    def __init__(
        self,
        *,
        assets: AgentCanvasAssetService,
        asset_repository: V2AssetLibraryRepository,
        workflows: AgentCanvasWorkflowRepository,
        commits: AgentCanvasGuidedProductRepository,
        compiler: ProductUploadMultiviewCompiler,
        events: EventRepository,
    ) -> None:
        self._assets = assets
        self._asset_repository = asset_repository
        self._workflows = workflows
        self._commits = commits
        self._compiler = compiler
        self._events = events

    def commit(
        self,
        workflow_id: str,
        request: GuidedProductInputCommitRequestV1,
        *,
        expected_workflow_revision: int,
        idempotency_key: str,
    ) -> GuidedProductInputCommitResponseV1:
        if not idempotency_key:
            raise V2PersistenceError(
                "idempotency_key_required",
                "Idempotency-Key is required.",
                stage="guided_product_service",
            )
        workflow = self._workflows.get_workflow(workflow_id)
        digest = request_digest(workflow_id, request, expected_workflow_revision)
        replay = self._commits.lookup_replay(
            workflow_id=workflow_id,
            idempotency_key=idempotency_key,
            request_digest=digest,
        )
        if replay is not None:
            return replay
        self._require_product_stage(workflow_id)
        if workflow.revision != expected_workflow_revision:
            raise V2PersistenceError(
                "workflow_revision_conflict",
                "Workflow revision does not match the current revision.",
                stage="guided_product_service",
            )
        guidance_revision = self._guidance_revision(workflow_id)
        if request.expected_guidance_revision != guidance_revision:
            raise V2PersistenceError(
                "guidance_revision_conflict",
                "Guidance session revision does not match the current revision.",
                stage="guided_product_service",
            )

        versions = tuple(
            self._resolve_input_version(workflow_id, reference.asset_id, reference.version_id)
            for reference in request.asset_versions
        )
        operation_id = f"op_{digest[:32]}"
        node_id = f"node_product_{request.input_kind}_{digest[:24]}"
        compiled_asset = None
        provenance_digest = None
        output_asset_id = versions[0].asset_id
        output_version_id = versions[0].version_id
        compiler_result = None
        try:
            if request.input_kind == "multiview":
                compiler_inputs = tuple(self._compiler_input(version) for version in versions)
                try:
                    compiler_result = self._compiler.compile(compiler_inputs)
                except ProductUploadMultiviewCompilationError as error:
                    self._append_failure_event(
                        workflow_id=workflow_id,
                        request=request,
                        request_digest=digest,
                        error_code=error.code,
                    )
                    raise V2PersistenceError(
                        error.code,
                        str(error),
                        stage="guided_product_service",
                    ) from error
                provenance = ProductUploadCompilationProvenanceV1(
                    profile_id=compiler_result.profile_id,
                    profile_version=compiler_result.profile_version,
                    ordered_inputs=tuple(
                        ProductUploadInputProvenanceV1(
                            asset_id=version.asset_id,
                            version_id=version.version_id,
                            sha256=version.sha256,
                            order=index,
                        )
                        for index, version in enumerate(versions)
                    ),
                    output_sha256=compiler_result.output_sha256,
                    compiler_fingerprint=compiler_result.compiler_fingerprint,
                )
                provenance_payload = provenance.model_dump(mode="json")
                provenance_digest = hashlib.sha256(
                    json.dumps(
                        provenance_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                published = self._assets.publish_generated_bytes(
                    workflow_id,
                    node_id=node_id,
                    execution_id=operation_id,
                    filename="product-multiview.png",
                    mime_type="image/png",
                    content=compiler_result.output_path.read_bytes(),
                    fingerprint=compiler_result.command_fingerprint,
                    source_type="derived",
                    source_semantic_role="product_multiview",
                    publication_metadata={
                        "source_type": "derived",
                        "upload_compilation": provenance_payload,
                        "provenance_digest": provenance_digest,
                    },
                )
                compiled_asset = published
                output_asset_id = published.asset_id
                output_version_id = published.version_id or output_version_id

            node = self._build_node(
                workflow_id=workflow_id,
                node_id=node_id,
                request=request,
                output_asset_id=output_asset_id,
                provenance=(
                    provenance_payload
                    if request.input_kind == "multiview"
                    else {
                        "kind": "direct_upload",
                        "asset_id": versions[0].asset_id,
                        "version_id": versions[0].version_id,
                    }
                ),
            )
            return self._commits.commit(
                node=node,
                request=request,
                idempotency_key=idempotency_key,
                request_digest=digest,
                expected_workflow_revision=expected_workflow_revision,
                guidance_revision=guidance_revision,
                compiled_asset=compiled_asset,
                output_asset_id=output_asset_id,
                output_version_id=output_version_id,
                provenance_digest=provenance_digest,
            )
        except BaseException:
            if compiler_result is not None:
                compiler_result.cleanup()
            if compiled_asset is not None:
                try:
                    self._assets.delete_asset(compiled_asset.asset_id)
                except V2PersistenceError:
                    pass
            raise

    def _append_failure_event(
        self,
        *,
        workflow_id: str,
        request: GuidedProductInputCommitRequestV1,
        request_digest: str,
        error_code: str,
    ) -> None:
        """Record one safe compiler failure without masking its domain error."""

        try:
            self._events.append(
                V2EventInsert(
                    workflow_id=workflow_id,
                    event_type="guided_product_source_failed",
                    transition_key=(
                        f"guided-product:{workflow_id}:{request.input_kind}:failure:"
                        f"{request_digest}"
                    ),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    payload={
                        "input_kind": request.input_kind,
                        "request_digest": request_digest,
                        "asset_versions": [
                            reference.model_dump(mode="json")
                            for reference in request.asset_versions
                        ],
                        "error_code": error_code,
                    },
                )
            )
        except V2PersistenceError:
            return

    def _resolve_input_version(self, workflow_id: str, asset_id: str, version_id: str):
        version = self._asset_repository.find_version(asset_id=asset_id, version_id=version_id)
        if version is None:
            raise V2PersistenceError(
                "guided_product_asset_not_found",
                "Product AssetVersion was not found.",
                stage="guided_product_service",
            )
        if version.source_workflow_id != workflow_id:
            raise V2PersistenceError(
                "guided_product_asset_foreign_workflow",
                "Product AssetVersion does not belong to this Workflow.",
                stage="guided_product_service",
            )
        try:
            self._assets.resolve_asset_version_path(asset_id, version_id)
        except V2PersistenceError as error:
            if error.code == "asset_not_ready":
                raise V2PersistenceError(
                    "guided_product_asset_unreadable",
                    "Product AssetVersion is not readable.",
                    stage="guided_product_service",
                ) from error
            raise
        if version.status != "ready":
            raise V2PersistenceError(
                "guided_product_asset_unreadable",
                "Product AssetVersion is not readable.",
                stage="guided_product_service",
            )
        if version.mime_type.split("/", 1)[0] != "image":
            raise V2PersistenceError(
                "guided_product_asset_not_image",
                "Product input AssetVersions must be images.",
                stage="guided_product_service",
            )
        return version

    def _compiler_input(self, version):
        path = self._assets.resolve_asset_version_path(version.asset_id, version.version_id)
        facts = V2MediaProbe()(path, "image")
        if facts.error or facts.width is None or facts.height is None:
            raise V2PersistenceError(
                "guided_product_asset_unreadable",
                "Product image could not be probed.",
                stage="guided_product_service",
            )
        return ProductUploadMultiviewInput(
            asset_id=version.asset_id,
            version_id=version.version_id,
            path=path,
            sha256=version.sha256,
            size_bytes=version.size_bytes,
            media_type="image",
            width=facts.width,
            height=facts.height,
        )

    def _guidance_revision(self, workflow_id: str) -> int:
        with self._workflows.database.engine.connect() as connection:
            revision = connection.execute(
                select(AgentCanvasGuidanceSessionRow.revision).where(
                    AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                )
            ).scalar_one_or_none()
        return int(revision) if revision is not None else 1

    def _require_product_stage(self, workflow_id: str) -> None:
        with self._workflows.database.engine.connect() as connection:
            journey_state = connection.execute(
                select(AgentCanvasGuidanceSessionRow.journey_state_json).where(
                    AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                )
            ).scalar_one_or_none()
        if journey_state is None:
            return
        try:
            journey = json.loads(str(journey_state))
            stage = journey.get("stage")
        except (TypeError, json.JSONDecodeError) as error:
            raise V2PersistenceError(
                "guided_product_stage_invalid",
                "Guided Product source input cannot read the current journey stage.",
                stage="guided_product_service",
            ) from error
        if stage != "product":
            raise V2PersistenceError(
                "guided_product_stage_invalid",
                "Guided Product source input is only available during the Product stage.",
                stage="guided_product_service",
            )

    @staticmethod
    def _build_node(
        *,
        workflow_id: str,
        node_id: str,
        request: GuidedProductInputCommitRequestV1,
        output_asset_id: str,
        provenance: dict[str, object],
    ) -> CanvasNodeV2:
        now = datetime.now(timezone.utc)
        return CanvasNodeV2(
            node_id=node_id,
            workflow_id=workflow_id,
            node_type="image",
            creative_role="product",
            title=(
                "Uploaded Product Main"
                if request.input_kind == "main"
                else "Uploaded Product Multiview"
            ),
            status="ready",
            execution_mode="source_only",
            summary_prompt=None,
            generation_prompt="",
            structured_content={},
            model_selection_mode="default",
            model_ref=None,
            parameters={},
            metadata={
                "source_input_kind": request.input_kind,
                "source_type": "upload" if request.input_kind == "main" else "derived",
                "output_asset_id": output_asset_id,
                "provenance": provenance,
            },
            output_asset_id=output_asset_id,
            position=CanvasPositionV2(x=0, y=0),
            revision=1,
            prompt_preparation=NodePromptPreparationV1.source_only(updated_at=now),
            created_at=now,
            updated_at=now,
        )
