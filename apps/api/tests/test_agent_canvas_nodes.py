from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasNodePatchRequestV2,
    CanvasNodeV2,
    CanvasPositionV2,
)
from app.schemas.agent_canvas_creative_session import CreativeGoalV2
from app.schemas.agent_canvas_errors import CanvasNodeErrorV2
from app.schemas.agent_canvas_progressive_authoring import StageAuthoringContextV1
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.services.agent_canvas_nodes import AgentCanvasNodeService
from app.services.agent_canvas_role_prompt_authoring import deterministic_role_brief
from app.services.agent_canvas_prompt_preparation import NodePromptPreparationService
from app.services.pi_agent_runtime_client import PiAgentRuntimeError


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

    def get_workflow(self, workflow_id: str) -> SimpleNamespace:
        assert workflow_id == self.node.workflow_id
        return SimpleNamespace(revision=1, nodes=(self.node,), bindings=())

    @property
    def database(self) -> SimpleNamespace:
        return SimpleNamespace(engine=SimpleNamespace(url=SimpleNamespace(database=None)))

    def update_node_prompt_preparation(
        self,
        node: CanvasNodeV2,
        *,
        expected_node_revision: int,
        expected_workflow_revision: int,
    ) -> CanvasNodeV2:
        assert expected_node_revision == self.node.revision
        assert expected_workflow_revision == 1
        self.node = node
        return node


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


def _retry_context() -> StageAuthoringContextV1:
    return StageAuthoringContextV1(
        workflow_id="workflow-product",
        session_id="session-product",
        session_revision=1,
        stage="product",
        creative_goal=CreativeGoalV2(
            requested_output="image",
            delivery_scope="draft",
            summary="A durable product identity.",
        ),
        internal_skill_ref="agent/skills/video_agent_product_design/SKILL.md",
    )


def _retryable_failed_draft() -> CanvasNodeV2:
    node = _managed_draft()
    return node.model_copy(
        update={
            "prompt_preparation": NodePromptPreparationV1(
                status="failed",
                operation_id="prompt-product-failed",
                attempt_no=1,
                context_snapshot_id="snapshot-product",
                error=CanvasNodeErrorV2(
                    code="prompt_preparation_failed",
                    message="Node prompt preparation failed.",
                    retryable=True,
                ),
                updated_at=node.updated_at,
            )
        }
    )


def test_retry_prompt_preparation_rejects_ready_and_nonretryable_failures() -> None:
    ready_repository = _Repository(_managed_draft())
    with pytest.raises(V2PersistenceError, match="prompt preparation"):
        NodePromptPreparationService(ready_repository).retry(
            "workflow-product",
            "node-product",
            operation_id="retry-ready",
            context=_retry_context(),
        )

    failed = _retryable_failed_draft().model_copy(
        update={
            "prompt_preparation": _retryable_failed_draft().prompt_preparation.model_copy(
                update={
                    "error": CanvasNodeErrorV2(
                        code="prompt_preparation_failed",
                        message="Node prompt preparation failed.",
                        retryable=False,
                    )
                }
            )
        }
    )
    with pytest.raises(V2PersistenceError, match="not retryable"):
        NodePromptPreparationService(_Repository(failed)).retry(
            "workflow-product",
            "node-product",
            operation_id="retry-nonretryable",
            context=_retry_context(),
        )


def test_retry_prompt_preparation_only_prepares_the_prompt() -> None:
    author_calls: list[str] = []
    repository = _Repository(_retryable_failed_draft())
    prepared = NodePromptPreparationService(
        repository,
        role_brief_author=lambda context, operation_id: (
            author_calls.append(operation_id) or deterministic_role_brief(context)
        ),
    ).retry(
        "workflow-product",
        "node-product",
        operation_id="retry-prompt-product",
        context=_retry_context(),
    )

    assert author_calls == ["retry-prompt-product"]
    assert prepared.status == "draft"
    assert prepared.prompt_preparation.status == "ready"
    assert prepared.prompt_preparation.attempt_no == 2


def test_retry_prompt_preparation_persists_a_typed_agent_validation_failure() -> None:
    repository = _Repository(_retryable_failed_draft())
    with pytest.raises(V2PersistenceError, match="structured output"):
        NodePromptPreparationService(
            repository,
            role_brief_author=lambda _context, _operation_id: (_raise_structured_failure()),
        ).retry(
            "workflow-product",
            "node-product",
            operation_id="retry-prompt-product",
            context=_retry_context(),
        )

    error = repository.node.prompt_preparation.error
    assert error is not None
    assert error.code == "agent_structured_output_invalid"
    assert error.retryable is False


def _raise_structured_failure() -> None:
    raise PiAgentRuntimeError(
        "agent_structured_output_invalid",
        "Agent structured output was invalid.",
    )
