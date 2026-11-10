"""Bounded, read-only project facts for ordinary conversation, without LLM summarization."""

from __future__ import annotations

import json
from collections.abc import Iterator

from app.persistence.agent_canvas_conversation_repository import AgentCanvasConversationRepository
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.schemas.agent_canvas import AgentCanvasWorkflowV2
from app.schemas.brand_professional_mode import BrandTreatmentDocumentV1
from app.services.brand_decision_document import BrandDecisionDocumentService

PROJECT_SUMMARY_MAX_BYTES = 12_288


class ConversationProjectSummaryBuilder:
    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._brands = BrandDecisionRepository(workflows.database)
        self._brand_documents = BrandDecisionDocumentService(workflows.database)

    def build(self, workflow_id: str) -> str:
        workflow = self._workflows.get_workflow(workflow_id)
        session = self._conversations.get_guidance_session_or_none(workflow_id)
        brand_id = self._brands.get_brand_id_by_project(workflow.project_id)
        document = self._brand_documents.read(brand_id) if brand_id else None
        result: dict[str, object] = {
            "source": "current_project_records",
            "workflow_id": workflow.workflow_id,
            "workflow_revision": workflow.revision,
            "goal": _clip(session.goal.summary, 1024) if session else None,
            "brand_id": brand_id,
            "brand_content_digest": document.content_digest if document else None,
            "facts": [],
            "omitted_facts": 0,
        }
        facts: list[dict[str, object]] = []
        omitted = 0
        # Reserve independent space so a verbose Brand brief cannot crowd out
        # current authored work (or a large canvas displace the product identity).
        for candidates, budget in ((_brand_facts(document), 6000), (_node_facts(workflow), 4800)):
            used = 0
            for fact in candidates:
                size = len(_json(fact).encode("utf-8")) + 1
                candidate = {**result, "facts": [*facts, fact], "omitted_facts": omitted}
                if (
                    used + size > budget
                    or len(_json(candidate).encode("utf-8")) > PROJECT_SUMMARY_MAX_BYTES - 64
                ):
                    omitted += 1
                else:
                    facts.append(fact)
                    used += size
        return _json({**result, "facts": facts, "omitted_facts": omitted})


def _brand_facts(document: BrandTreatmentDocumentV1 | None) -> Iterator[dict[str, object]]:
    if document is None:
        return
    if document.selected_hypothesis is not None:
        direction = document.selected_hypothesis
        yield {
            "kind": "selected_direction",
            "label": direction.label,
            "story": _clip(direction.hypothesis, 1800),
        }
    if document.skill_stack is not None:
        yield {"kind": "selected_skills", "selection": document.skill_stack.model_dump(mode="json")}
    for profile in (document.brand_profile, document.campaign_brief):
        for value in profile.values:
            yield {
                "kind": "brand_decision",
                "stage": value.stage,
                "field": value.slot_id,
                "value": _clip(value.value, 600),
                "provenance": value.provenance,
                "decision_kind": value.kind,
            }
    for step in document.treatment_steps:
        yield {
            "kind": "selected_treatment",
            "step": step.step_key,
            "label": step.selected_label,
            "detail": _clip(step.detail, 900),
        }


def _node_facts(workflow: AgentCanvasWorkflowV2) -> Iterator[dict[str, object]]:
    # Summaries describe authored artifacts, not provider prompts or a claim to have viewed media.
    roles = ("product", "script", "creative_brief", "world_setting", "character", "scene", "bgm")
    for role in roles:
        for node in workflow.nodes:
            if node.creative_role != role:
                continue
            text = node.structured_content.get("content")
            if not isinstance(text, str):
                text = node.summary_prompt or ""
            yield {
                "kind": "current_node",
                "node_id": node.node_id,
                "revision": node.revision,
                "role": role,
                "title": node.title,
                "status": node.status,
                "output_available": node.output_asset_id is not None,
                "summary_excerpt": _clip(text, 1600 if role == "script" else 450),
            }


def _clip(value: str, limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    # Retain the ending as well as the setup; never silently turn a partial extract into a full script.
    half = (limit - 40) // 2
    return (
        encoded[:half].decode("utf-8", errors="ignore")
        + "\n[excerpt omitted]\n"
        + encoded[-half:].decode("utf-8", errors="ignore")
    )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
