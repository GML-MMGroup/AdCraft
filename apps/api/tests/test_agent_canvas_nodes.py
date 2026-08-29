from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from app.schemas.agent_canvas import (
    CanvasNodePatchRequestV2,
    CanvasNodeV2,
    CanvasPositionV2,
)
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.services.agent_canvas_nodes import AgentCanvasNodeService


class _Repository:
    def __init__(self, node: CanvasNodeV2) -> None:
        self.node = node

    def get_node(self, workflow_id: str, node_id: str) -> CanvasNodeV2:
        assert workflow_id == self.node.workflow_id
        assert node_id == self.node.node_id
        return self.node

    def update_node(self, node: CanvasNodeV2, *, expected_revision: int) -> None:
        assert expected_revision == self.node.revision
        self.node = node


def _managed_draft() -> CanvasNodeV2:
    now = datetime.now(timezone.utc)
    prompt = "Canonical product prompt.\n\nRequired assertions:\n- One isolated product identity."
    digest = sha256(prompt.encode("utf-8")).hexdigest()
    return CanvasNodeV2(
        node_id="node-product",
        workflow_id="workflow-product",
        node_type="image",
        creative_role="product",
        title="Product",
        status="draft",
        generation_prompt=prompt,
        model_selection_mode="default",
        position=CanvasPositionV2(x=0, y=0),
        revision=1,
        prompt_preparation=NodePromptPreparationV1(
            status="ready",
            operation_id="prompt-product",
            attempt_no=1,
            context_snapshot_id="snapshot-product",
            prompt_digest=digest,
            role_variant="product_main",
            recipe_id="adcraft.agent_canvas.product_main",
            recipe_version="1",
            recipe_digest="sha256:" + "a" * 64,
            updated_at=now,
        ),
        metadata={
            "prompt_digest": digest,
            "prompt_recipe_id": "adcraft.agent_canvas.product_main",
            "prompt_recipe_version": "1",
            "prompt_recipe_digest": "sha256:" + "a" * 64,
        },
        created_at=now,
        updated_at=now,
    )


def test_model_selection_keeps_a_managed_prompt_ready() -> None:
    repository = _Repository(_managed_draft())

    updated = AgentCanvasNodeService(repository).patch(
        "workflow-product",
        "node-product",
        CanvasNodePatchRequestV2(
            model_selection_mode="explicit",
            model_ref="cliproxyapi:gpt-image-2",
        ),
        expected_revision=1,
    )

    assert updated.model_ref == "cliproxyapi:gpt-image-2"
    assert updated.prompt_preparation.status == "ready"
    assert updated.prompt_preparation.recipe_id == "adcraft.agent_canvas.product_main"


def test_manual_prompt_edit_preserves_user_text_and_leaves_node_runnable() -> None:
    repository = _Repository(_managed_draft())

    updated = AgentCanvasNodeService(repository).patch(
        "workflow-product",
        "node-product",
        CanvasNodePatchRequestV2(generation_prompt="A user-authored product photograph."),
        expected_revision=1,
    )

    assert updated.generation_prompt == "A user-authored product photograph."
    assert updated.prompt_preparation.status == "ready"
    assert updated.metadata["prompt_authoring_mode"] == "manual"
    assert "prompt_recipe_id" not in updated.metadata


def test_same_prompt_recovers_an_orphaned_managed_preparation() -> None:
    node = _managed_draft()
    orphaned = node.model_copy(
        update={
            "prompt_preparation": NodePromptPreparationV1(
                status="queued",
                operation_id=None,
                attempt_no=1,
                context_snapshot_id=None,
                prompt_digest=None,
                updated_at=node.updated_at,
            )
        }
    )
    repository = _Repository(orphaned)

    updated = AgentCanvasNodeService(repository).patch(
        "workflow-product",
        "node-product",
        CanvasNodePatchRequestV2(generation_prompt=orphaned.generation_prompt),
        expected_revision=1,
    )

    assert updated.prompt_preparation.status == "ready"
    assert updated.metadata["prompt_authoring_mode"] == "manual"
