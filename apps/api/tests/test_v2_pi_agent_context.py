from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.agent_operation_contexts import (
    BgmExpertAgentContext,
    CharacterExpertAgentContext,
    FrozenPlanningFacts,
    ProductExpertAgentContext,
    SceneExpertAgentContext,
)
from app.schemas.workflow_v2 import (
    WorkflowV2ChatActionTarget,
    WorkflowV2FreeNodeCreateRequest,
    WorkflowV2FreeNodeGenerateRequest,
)
from app.services.v2_agent_target_resolver import V2AgentTargetResolver
from app.services.v2_pi_planning_session import V2PiPlanningSession
from app.services.v2_pi_agent_context import (
    V2AgentContextBuilder,
    agent_for_semantic_family,
    isolate_agent_input_payload,
)
from app.services.workflow_v2 import WorkflowV2Service
from tests.helpers.asset_factories import (
    make_v2_asset_relation,
    make_v2_asset_version,
)
from tests.helpers.v2_factories import (
    add_working_asset_to_slot,
    make_v2_completed_asset_workflow,
    make_v2_workflow,
)


class FakeConversationContextSource:
    def load_context(
        self,
        conversation_id: str,
        *,
        limit: int,
    ) -> tuple[str, list[dict[str, object]]]:
        assert conversation_id == "conv-context"
        return (
            "The user is refining one exact hero character.",
            [
                {
                    "sequence_no": index,
                    "role": "user" if index % 2 else "assistant",
                    "content": (
                        f"Visible turn {index} "
                        + ("x" * 900)
                        + (
                            " /private/provider.json data:image/png;base64,AAAA"
                            if index == 29
                            else ""
                        )
                    ),
                    "provider_payload": {"secret": "not-visible"},
                }
                for index in range(1, 31)
            ][-limit:],
        )


@pytest.mark.parametrize(
    ("context_type", "context_kind"),
    [
        (ProductExpertAgentContext, "product_expert"),
        (CharacterExpertAgentContext, "character_expert"),
        (SceneExpertAgentContext, "scene_expert"),
        (BgmExpertAgentContext, "bgm_expert"),
    ],
)
@pytest.mark.parametrize(
    "unsafe",
    [
        {"sibling_provider_prompt": "SIBLING_SENTINEL"},
        {"user_input": "data:image/png;base64,AAAA"},
        {"user_input": "/private/full-workflow.json"},
        {"credentials": {"api_key": "secret"}},
        {"full_workflow": {"nodes": []}},
    ],
)
def test_expert_contexts_reject_sibling_and_unsafe_payloads(
    context_type: type[ProductExpertAgentContext],
    context_kind: str,
    unsafe: dict[str, object],
) -> None:
    payload = {
        "context_kind": context_kind,
        "user_input": "Target-owned instruction.",
        "frozen_facts": FrozenPlanningFacts(product_name="Product"),
        **unsafe,
    }

    with pytest.raises(ValidationError):
        context_type.model_validate(payload)


def test_parallel_pi_expert_invocations_keep_distinct_identity_and_context() -> None:
    session = V2PiPlanningSession.start(workflow_id="adwf_v2_context_parallel")
    contexts = [
        ProductExpertAgentContext(
            context_kind="product_expert",
            user_input="PRODUCT_SENTINEL",
            frozen_facts=FrozenPlanningFacts(product_name="Product"),
        ),
        CharacterExpertAgentContext(
            context_kind="character_expert",
            user_input="CHARACTER_SENTINEL",
            frozen_facts=FrozenPlanningFacts(product_name="Product"),
        ),
        SceneExpertAgentContext(
            context_kind="scene_expert",
            user_input="SCENE_SENTINEL",
            frozen_facts=FrozenPlanningFacts(product_name="Product"),
        ),
        BgmExpertAgentContext(
            context_kind="bgm_expert",
            user_input="BGM_SENTINEL",
            frozen_facts=FrozenPlanningFacts(product_name="Product"),
        ),
    ]

    def create(index: int) -> tuple[str, str]:
        context = contexts[index]
        invocation = session.child(
            agent_name=(
                "product_designer",
                "character_designer",
                "scene_designer",
                "bgm_director",
            )[index],
            operation=f"expert-{index}",
            logical_key=f"expert-{index}",
        )
        return invocation.run_id, context.model_dump_json()

    with ThreadPoolExecutor(max_workers=4) as executor:
        outputs = list(executor.map(create, range(4)))

    assert len({run_id for run_id, _payload in outputs}) == 4
    assert all(
        sentinel in payload
        and all(
            other not in payload
            for other in {
                "PRODUCT_SENTINEL",
                "CHARACTER_SENTINEL",
                "SCENE_SENTINEL",
                "BGM_SENTINEL",
            }
            - {sentinel}
        )
        for sentinel, (_run_id, payload) in zip(
            ("PRODUCT_SENTINEL", "CHARACTER_SENTINEL", "SCENE_SENTINEL", "BGM_SENTINEL"),
            outputs,
        )
    )


def test_pi_agent_owner_map_has_one_owner_for_each_generation_family() -> None:
    assert agent_for_semantic_family("product_main_image") == "product_designer"
    assert agent_for_semantic_family("character_three_view") == "character_designer"
    assert agent_for_semantic_family("scene_multi_view_grid") == "scene_designer"
    assert agent_for_semantic_family("shot_cell_1") == "storyboard_artist"
    assert agent_for_semantic_family("shot_cell_4") == "storyboard_artist"
    assert agent_for_semantic_family("shot_video_segment") == "video_director"
    assert agent_for_semantic_family("bgm_audio") == "bgm_director"
    assert agent_for_semantic_family("free_video") == "quick_media_agent"


def test_pi_agent_context_excludes_unowned_and_unsafe_payloads() -> None:
    isolated = isolate_agent_input_payload(
        {
            "target": {
                "slot_id": "shot-1:shot_cell_1",
                "current_prompt": "Opening product reveal.",
            },
            "screenplay_summary": "Shot 1 opens on the product.",
            "style_summary": "Clean studio lighting.",
            "reference_asset_summaries": [
                {
                    "asset_id": "asset-product",
                    "semantic_type": "product_reference",
                    "display_name": "Product",
                }
            ],
            "sibling_provider_prompts": ["Do not expose this sibling prompt."],
            "provider_payload": {"prompt": "Provider-owned payload."},
            "raw_media": "data:image/png;base64,AAAA",
            "local_path": "/private/media/product.png",
            "credentials": {"api_key": "secret"},
        }
    )

    serialized = str(isolated)
    assert isolated["target"]["current_prompt"] == "Opening product reveal."
    assert isolated["screenplay_summary"] == "Shot 1 opens on the product."
    assert isolated["reference_asset_summaries"][0]["asset_id"] == "asset-product"
    assert "sibling" not in serialized
    assert "Provider-owned" not in serialized
    assert "base64" not in serialized
    assert "/private/" not in serialized
    assert "secret" not in serialized


def test_final_composition_has_no_pi_agent_owner() -> None:
    try:
        agent_for_semantic_family("final_video")
    except ValueError as exc:
        assert str(exc) == "agent_semantic_family_not_allowed"
    else:
        raise AssertionError("Final Composition must remain Python-owned.")


def test_targeted_context_contains_only_bounded_target_owned_state(
    v2_media_data_dir,
) -> None:
    workflow = make_v2_completed_asset_workflow(
        v2_media_data_dir,
        workflow_id="adwf_v2_target_context",
        selected_slots=["character-1:character_main_image"],
    )
    add_working_asset_to_slot(
        v2_media_data_dir,
        workflow,
        "character-1:character_main_image",
    )
    reference = make_v2_asset_version(
        v2_media_data_dir,
        workflow_id=workflow.workflow_id,
        asset_id="asset_character_reference",
        version_id="ver_character_reference",
        media_type="image",
        node_id="character-generation",
        item_id="character-1",
        slot_id=None,
        semantic_type="character_reference",
        display_name="Wardrobe reference",
        prompt_summary="Blue tailored jacket.",
    )
    make_v2_asset_relation(
        v2_media_data_dir,
        relation_type="reference_for_slot",
        source_asset_id=reference.asset_id,
        workflow_id=workflow.workflow_id,
        node_id="character-generation",
        item_id="character-1",
        slot_id="character-1:character_main_image",
        version_id=reference.version_id,
    )
    settings = Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    target = V2AgentTargetResolver(settings).resolve(
        workflow.workflow_id,
        WorkflowV2ChatActionTarget(
            target_type="slot",
            slot_id="character-1:character_main_image",
        ),
    )

    context = V2AgentContextBuilder(
        settings,
        conversation_context_source=FakeConversationContextSource(),
        recent_message_limit=12,
        recent_message_bytes=4_096,
    ).build_targeted_revision(
        workflow_id=workflow.workflow_id,
        conversation_id="conv-context",
        target=target,
        user_instruction="Keep the identity and change the jacket to navy.",
    )

    assert context.context_kind == "targeted_revision"
    assert context.target.node_id == "character-generation"
    assert context.target.item_id == "character-1"
    assert context.target.slot_id == "character-1:character_main_image"
    assert context.target.related_multiview_slot_id == "character-1:character_three_view"
    assert context.target.expected_revision == workflow.state_version
    assert context.target.selected_version is not None
    assert context.target.working_version is not None
    assert {reference.asset_id for reference in context.reference_summaries} == {
        "asset_character_reference"
    }
    assert len(context.recent_messages) <= 12
    assert sum(len(message.content.encode("utf-8")) for message in context.recent_messages) <= 4_096
    serialized = context.model_dump_json()
    assert "provider_payload" not in serialized
    assert "/private/" not in serialized
    assert "base64" not in serialized
    assert "workflow_json" not in serialized
    assert "shot-1:shot_cell_1" not in serialized


def test_quick_media_context_reads_only_the_requested_free_node(
    v2_media_data_dir,
) -> None:
    workflow = make_v2_workflow(
        v2_media_data_dir,
        workflow_id="adwf_v2_quick_context",
    )
    service = WorkflowV2Service(
        Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    )
    workflow = service.create_free_node(
        workflow.workflow_id,
        WorkflowV2FreeNodeCreateRequest(
            slot_prompt="A clean product splash image.",
        ),
    )
    free_node = next(node for node in workflow.nodes if node.node_type == "free-generation")

    context = V2AgentContextBuilder(
        Settings(agent_runtime_mode="fake", media_data_dir=v2_media_data_dir)
    ).build_quick_media(
        workflow_id=workflow.workflow_id,
        node_id=free_node.node_id,
        request=WorkflowV2FreeNodeGenerateRequest(output_media_type="image"),
    )

    assert context.context_kind == "quick_media"
    assert context.node_id == free_node.node_id
    assert context.output_media_type == "image"
    assert context.user_input == "A clean product splash image."
    assert "provider_payload" not in context.model_dump_json()
