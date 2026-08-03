import { describe, expect, it } from "vitest";

import {
  normalizeAgentCanvasChatTimelineV2,
  normalizeAgentCanvasChatTurnV2,
  normalizeAgentCanvasVideoSkillRunV2,
  normalizeAgentCanvasWorkflowV2,
  normalizeAgentCanvasChatTimelineResponseV2,
  normalizeCanvasBindingV2,
  normalizeCanvasLayoutPatchResponseV2,
  normalizeCanvasNodeV2,
  normalizeCanvasRuntimeEventV2,
  normalizeCanvasRuntimeEventsResponseV2,
  normalizeCanvasRuntimeSnapshotV2,
  normalizeCanvasRunAcceptedV2,
  normalizeCanvasVariationDraftV2,
  normalizeCanvasVariationMaterializeResponseV2,
  normalizeChatTurnAcceptedV2,
  normalizeChatTimelineListResponseV2,
  normalizeEditingNodeContentV2,
  normalizeEditingExportAcceptedV2,
  normalizeProjectAssetSummaryV2,
  normalizeProviderModelCapabilityListV2,
  normalizeResolvedMediaInputSnapshotV2,
  normalizeResolvedTextInputSnapshotV2,
} from "./normalizers.ts";

function validWorkflowPayload() {
  return {
    workflow_id: "workflow-1",
    project_id: "project-1",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 7,
    layout_revision: 3,
    nodes: [
      {
        node_id: "node-text-1",
        workflow_id: "workflow-1",
        node_type: "text",
        creative_role: "creative_brief",
        role_contract_version: "ad-media-role-v1",
        title: "Creative Brief",
        status: "ready",
        summary_prompt: "A compact brand brief.",
        generation_prompt: null,
        structured_content: { markdown: "# Brief" },
        model_id: null,
        parameters: {},
        prompt_context_snapshot_id: null,
        output_asset_id: null,
        position: { x: 120, y: 80 },
        revision: 3,
        error: null,
        variation_draft: null,
        created_at: "2026-07-28T10:00:00Z",
        updated_at: "2026-07-28T10:05:00Z",
      },
      {
        node_id: "node-image-1",
        workflow_id: "workflow-1",
        node_type: "image",
        creative_role: "character",
        role_contract_version: "ad-media-role-v1",
        title: "Lead Character",
        status: "draft",
        summary_prompt: "Main character portrait.",
        generation_prompt: "High detail cinematic portrait.",
        structured_content: {},
        model_id: "model-image-1",
        parameters: { stylization: 100 },
        prompt_context_snapshot_id: "snapshot-1",
        output_asset_id: "asset-output-1",
        position: { x: 480, y: 220 },
        revision: 5,
        error: {
          code: "provider_timeout",
          message: "Provider timed out.",
          retryable: true,
        },
        variation_draft: null,
        created_at: "2026-07-28T10:06:00Z",
        updated_at: "2026-07-28T10:07:00Z",
      },
    ],
    bindings: [
      {
        binding_id: "binding-1",
        workflow_id: "workflow-1",
        source: { kind: "node_output", source_node_id: "node-text-1" },
        target_node_id: "node-image-1",
        input_role: "text_context",
        required: true,
        enabled: true,
        order: 0,
        label: null,
        metadata: {},
        created_at: "2026-07-28T10:06:30Z",
        updated_at: "2026-07-28T10:06:30Z",
      },
      {
        binding_id: "binding-2",
        workflow_id: "workflow-1",
        source: { kind: "image_asset", source_asset_id: "asset-library-1" },
        target_node_id: "node-image-1",
        input_role: "image_reference",
        required: false,
        enabled: true,
        order: 1,
        label: null,
        metadata: {},
        created_at: "2026-07-28T10:06:31Z",
        updated_at: "2026-07-28T10:06:31Z",
      },
    ],
    assets: [
      {
        asset_id: "asset-output-1",
        media_type: "image",
        source_type: "generated",
        display_name: "Lead Character Render",
        mime_type: "image/png",
        status: "ready",
        preview_url: "/api/v2/assets/asset-output-1/content",
        media_url: "/api/v2/assets/asset-output-1/content",
        width: 1024,
        height: 1024,
        duration_seconds: null,
        checksum: "sha256-output-1",
      },
      {
        asset_id: "asset-library-1",
        media_type: "image",
        source_type: "library",
        display_name: "Reference Image",
        mime_type: "image/jpeg",
        status: "ready",
        preview_url: "/api/v2/assets/asset-library-1/content",
        media_url: "/api/v2/assets/asset-library-1/content",
        width: 1200,
        height: 900,
        duration_seconds: null,
        checksum: "sha256-library-1",
      },
    ],
  };
}

describe("Agent Canvas normalizers", () => {
  it("normalizes the frozen node and persisted binding contract", () => {
    const workflow = normalizeAgentCanvasWorkflowV2({
      ...validWorkflowPayload(),
      nodes: validWorkflowPayload().nodes.map((node, index) => ({
        ...node,
        creative_role: index === 0 ? "creative_brief" : "character",
      })),
      bindings: [
        {
          binding_id: "binding-1",
          workflow_id: "workflow-1",
          source: { kind: "node_output", source_node_id: "node-text-1" },
          target_node_id: "node-image-1",
          input_role: "text_context",
          required: true,
          enabled: true,
          order: 0,
          label: "Creative direction",
          metadata: { origin: "manual" },
          created_at: "2026-07-28T10:06:30Z",
          updated_at: "2026-07-28T10:06:32Z",
        },
        {
          binding_id: "binding-2",
          workflow_id: "workflow-1",
          source: { kind: "image_asset", source_asset_id: "asset-library-1" },
          target_node_id: "node-image-1",
          input_role: "image_reference",
          required: false,
          enabled: true,
          order: 1,
          label: null,
          metadata: {},
          created_at: "2026-07-28T10:06:31Z",
          updated_at: "2026-07-28T10:06:31Z",
        },
      ],
    });

    expect(workflow.nodes[0]?.creative_role).toBe("creative_brief");
    expect(workflow.bindings[0]).toMatchObject({
      input_role: "text_context",
      enabled: true,
      order: 0,
    });
    expect(workflow.bindings[1]?.source).toEqual({
      kind: "image_asset",
      source_asset_id: "asset-library-1",
    });
  });

  it("normalizes durable proposals, specialist status, and guided actions after refresh", () => {
    const timeline = normalizeAgentCanvasChatTimelineResponseV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      creative_session: {
        skill_run_id: "session-1",
        workflow_id: "workflow-1",
        skill_id: "video-ad",
        skill_version: "1",
        status: "active",
        creative_direction_snapshot_id: null,
        current_topic_id: "characters",
        topics: [
          {
            topic_id: "characters",
            topic_kind: "character",
            display_order: 0,
            required: true,
            specialist_name: "character_designer",
            status: "in_review",
            outcome: null,
            related_node_ids: [],
          },
        ],
        deferred_topic_ids: [],
        memory_revision: 2,
        updated_at: "2026-07-30T08:00:00Z",
      },
      items: [
        {
          entry_id: "entry-proposal-1",
          workflow_id: "workflow-1",
          conversation_id: "conversation-1",
          sequence_no: 3,
          entry_type: "concept_proposal",
          speaker: null,
          content: "Choose a character direction.",
          metadata: {
            proposal_id: "proposal-1",
            proposal_kind: "character",
          },
          command_plan: null,
          action_receipt: null,
          guided_actions: [
            {
              action_id: "action-add-character",
              action: "add_another_topic_node",
              state: "pending",
              creating_turn_id: "turn-1",
              expected_semantic_revision: 7,
              label: "Add another",
              workflow_id: "workflow-1",
              proposal_id: "proposal-1",
              topic_id: "characters",
              node_id: null,
              ordered_node_ids: [],
              manifest_revision: null,
              recipe_id: "recipe-guided-1",
              recipe_revision: 1,
              confirmation_required: false,
              reason: "Add another character option.",
            },
          ],
          created_at: "2026-07-30T08:01:00Z",
        },
        {
          entry_id: "entry-activity-1",
          workflow_id: "workflow-1",
          conversation_id: "conversation-1",
          sequence_no: 4,
          entry_type: "expert_activity",
          speaker: null,
          content: "Character Designer is working",
          metadata: {
            specialist_name: "character_designer",
            status: "working",
          },
          command_plan: null,
          action_receipt: null,
          guided_actions: [],
          created_at: "2026-07-30T08:01:01Z",
        },
      ],
      next_cursor: 4,
    });

    expect(timeline.creative_session?.current_topic_id).toBe("characters");
    expect(timeline.items[0]?.entry_type).toBe("concept_proposal");
    expect(timeline.items[0]?.guided_actions[0]?.action).toBe("add_another_topic_node");
    expect(timeline.items[0]?.guided_actions[0]?.recipe_id).toBe("recipe-guided-1");
    expect(timeline.items[0]?.guided_actions[0]?.recipe_revision).toBe(1);
    expect(timeline.items[1]?.entry_type).toBe("expert_activity");
  });

  it("normalizes a complete canonical workflow payload", () => {
    const workflow = normalizeAgentCanvasWorkflowV2(validWorkflowPayload());

    expect(workflow.canvas_model).toBe("agent_canvas_v1");
    expect(workflow.revision).toBe(7);
    expect(workflow.layout_revision).toBe(3);
    expect(workflow.nodes).toHaveLength(2);
    expect(workflow.bindings[1]?.source.kind).toBe("image_asset");
    expect(workflow.assets[0]?.checksum).toBe("sha256-output-1");
  });

  it("accepts final Project Asset provenance without exposing storage implementation details to callers", () => {
    const asset = normalizeProjectAssetSummaryV2({
      ...validWorkflowPayload().assets[0],
      project_id: "project-1",
      workflow_id: "workflow-1",
      semantic_type: "character",
      size_bytes: 2048,
      storage_key: "project-assets/project-1/asset-output-1.png",
      source_semantic_role: "character",
      source_node_id: "node-image-1",
      source_execution_id: "execution-1",
      provider: "volcengine",
      model_id: "seedream-4-0-250828",
      prompt_provenance: { compiler: "agent_canvas_v2" },
      quality_metadata: { score: 0.94 },
      created_at: "2026-07-28T10:08:00Z",
    });

    expect(asset).toMatchObject({
      asset_id: "asset-output-1",
      source_node_id: "node-image-1",
      provider: "volcengine",
    });
  });

  it("normalizes final generic-node and explicit-binding contracts", () => {
    const canonical = validWorkflowPayload();
    const payload = {
      ...canonical,
      nodes: canonical.nodes.map((node, index) => ({
        ...node,
        creative_role: index === 0 ? "creative_brief" : "storyboard_sequence",
      })),
    };

    const workflow = normalizeAgentCanvasWorkflowV2(payload);

    expect(workflow.nodes[1]?.creative_role).toBe("storyboard_sequence");
    expect(workflow.bindings[0]).toMatchObject({
      source: { kind: "node_output", source_node_id: "node-text-1" },
      input_role: "text_context",
      enabled: true,
      order: 0,
    });
  });

  it("accepts additive typed-input runtime metadata and idempotent event identity", () => {
    const runtime = normalizeCanvasRuntimeSnapshotV2({
      workflow_id: "workflow-1",
      active_execution_id: "execution-1",
      execution_status: "waiting",
      node_runtime: {
        "node-video-1": {
          node_id: "node-video-1",
          visible_status: "draft",
          phase: "waiting_for_input",
          execution_id: "execution-1",
          provider_task_id: null,
          input_manifest_id: "manifest-1",
          waiting_reason: "waiting_for_input",
          missing_required_source_node_ids: ["node-script-1", "node-image-1"],
          waiting_for_node_ids: ["node-script-1"],
          blocked_by_node_ids: [],
          attempt_no: 0,
          updated_at: "2026-07-31T04:00:00Z",
          error: null,
        },
      },
      queued_node_ids: [],
      working_node_ids: [],
      waiting_node_ids: ["node-video-1"],
      ready_node_ids: [],
      failed_node_ids: [],
      events_cursor: 17,
      updated_at: "2026-07-31T04:00:00Z",
    });
    const event = normalizeCanvasRuntimeEventV2({
      sequence_no: 18,
      workflow_id: "workflow-1",
      event_type: "provider_inputs_resolved",
      project_id: "project-1",
      execution_id: "execution-1",
      node_id: "node-video-1",
      asset_id: null,
      binding_id: null,
      conversation_id: null,
      turn_id: null,
      action_id: null,
      trace_id: null,
      span_id: null,
      transition_key: "node-run:node-video-1:inputs-resolved:1",
      attempt: 1,
      created_at: "2026-07-31T04:00:01Z",
      payload: { input_manifest_id: "manifest-1" },
    });

    expect(runtime.node_runtime["node-video-1"]).toMatchObject({
      input_manifest_id: "manifest-1",
      waiting_reason: "waiting_for_input",
      missing_required_source_node_ids: ["node-script-1", "node-image-1"],
    });
    expect(event).toMatchObject({
      transition_key: "node-run:node-video-1:inputs-resolved:1",
      attempt: 1,
    });
  });

  it("normalizes frozen run intent and effective runtime metadata", () => {
    const runtime = normalizeCanvasRuntimeSnapshotV2({
      workflow_id: "workflow-1",
      active_execution_id: "execution-1",
      execution_status: "waiting",
      node_runtime: {
        "node-video-1": {
          node_id: "node-video-1",
          visible_status: "draft",
          phase: "blocked_by_upstream",
          execution_id: "execution-1",
          provider_task_id: null,
          run_intent_snapshot_id: "run-intent-1",
          input_manifest_id: "manifest-1",
          effective_parameters: {
            duration_seconds: 15,
            generate_audio: false,
          },
          normalizations: ["duration_clamped_to_provider_limit"],
          omitted_optional_inputs: [
            {
              binding_id: "binding-audio-1",
              reason: "provider_input_unsupported",
            },
          ],
          waiting_reason: "blocked_by_upstream",
          missing_required_source_node_ids: [],
          waiting_for_node_ids: ["node-image-1"],
          blocked_by_node_ids: ["node-image-1"],
          attempt_no: 1,
          updated_at: "2026-08-03T09:00:00Z",
          error: null,
        },
      },
      queued_node_ids: [],
      working_node_ids: [],
      waiting_node_ids: ["node-video-1"],
      ready_node_ids: [],
      failed_node_ids: [],
      events_cursor: 18,
      updated_at: "2026-08-03T09:00:00Z",
    });

    expect(runtime.node_runtime["node-video-1"]).toMatchObject({
      phase: "blocked_by_upstream",
      run_intent_snapshot_id: "run-intent-1",
      effective_parameters: {
        duration_seconds: 15,
        generate_audio: false,
      },
      normalizations: ["duration_clamped_to_provider_limit"],
      omitted_optional_inputs: [
        {
          binding_id: "binding-audio-1",
          reason: "provider_input_unsupported",
        },
      ],
    });
  });

  it("normalizes durable continuation delivery and non-applied guided receipts", () => {
    const accepted = normalizeChatTurnAcceptedV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: "message-1",
      turn_id: "turn-1",
      status: "queued",
      events_cursor: 21,
      continuation: {
        continuation_id: "continuation-1",
        delivery_status: "retry_wait",
        attempt_count: 2,
        next_attempt_at: "2026-07-31T04:10:00Z",
      },
    });
    const turn = normalizeAgentCanvasChatTurnV2({
      turn_id: "turn-1",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: "running",
      turn_kind: "message",
      request: {},
      error_code: null,
      error_message: null,
      continuation: {
        continuation_id: "continuation-1",
        delivery_status: "leased",
        attempt_count: 3,
        next_attempt_at: "2026-07-31T04:11:00Z",
      },
      created_at: "2026-07-31T04:00:00Z",
      updated_at: "2026-07-31T04:01:00Z",
    });
    const timeline = normalizeAgentCanvasChatTimelineV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      creative_session: null,
      items: [{
        entry_id: "receipt-entry-1",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        sequence_no: 2,
        entry_type: "action_receipt",
        speaker: null,
        content: "No additional draft was needed.",
        metadata: {},
        command_plan: null,
        action_receipt: {
          receipt_id: "receipt-1",
          workflow_id: "workflow-1",
          plan_id: null,
          action_id: "action-1",
          actor_kind: "user",
          idempotency_key: "guided-action-1",
          status: "not_applied",
          summary: "No additional draft was needed.",
          created_node_ids: [],
          updated_node_ids: [],
          deleted_node_ids: [],
          created_binding_ids: [],
          deleted_binding_ids: [],
          queued_execution_ids: [],
          run_queue_errors: [],
          operation_results: [],
          workflow_revision: 3,
          before_workflow_revision: 3,
          placement_hints: [],
          continuation_turn_id: null,
          continuation_id: "continuation-1",
          superseded_by: null,
          error: { code: "guided_action_no_effect", message: "No new sibling draft was created." },
          error_code: "guided_action_no_effect",
          error_message: "No new sibling draft was created.",
          created_at: "2026-07-31T04:01:00Z",
        },
        guided_actions: [],
        created_at: "2026-07-31T04:01:00Z",
      }],
      next_cursor: 2,
    });

    expect(accepted.continuation).toMatchObject({ delivery_status: "retry_wait", attempt_count: 2 });
    expect(turn.continuation).toMatchObject({ delivery_status: "leased", attempt_count: 3 });
    expect(timeline.items[0]).toMatchObject({
      item_type: "action_receipt",
      action_receipt: {
        status: "not_applied",
        continuation_id: "continuation-1",
        error: { code: "guided_action_no_effect" },
      },
    });
  });

  it("preserves the backend-defined adaptive production recipe without inferring topology", () => {
    const timeline = normalizeAgentCanvasChatTimelineV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      creation_mode: "guided_production",
      recipe: {
        recipe_id: "recipe-1",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        skill_run_id: "skill-1",
        revision: 2,
        creation_mode: "guided_production",
        current_topic_id: "topic-scene",
        stages: [
          {
            topic_id: "topic-product",
            topic_kind: "product",
            title: "Product design",
            objective: "Define the product visual language.",
            applicability: "not_required",
            applicability_reason: "The approved product image already exists.",
            specialist_name: "product_designer",
            proposal_mode: "single_plan",
            candidate_count: 1,
            status: "not_required",
            related_node_ids: ["node-product-ready"],
          },
          {
            topic_id: "topic-scene",
            topic_kind: "scene",
            title: "Scene design",
            objective: "Choose a setting for the product film.",
            applicability: "required",
            applicability_reason: "A scene is needed for the film.",
            specialist_name: "scene_designer",
            proposal_mode: "choice_set",
            candidate_count: 3,
            status: "working",
            related_node_ids: [],
          },
        ],
        anchor_digest: "anchor-1",
        created_at: "2026-07-31T05:00:00Z",
        updated_at: "2026-07-31T05:01:00Z",
      },
      continuations: [],
      creative_session: null,
      items: [],
      next_cursor: 0,
    });

    expect(timeline.creation_mode).toBe("guided_production");
    expect(timeline.recipe).toMatchObject({
      recipe_id: "recipe-1",
      current_topic_id: "topic-scene",
      stages: [
        { topic_id: "topic-product", applicability: "not_required" },
        { topic_id: "topic-scene", candidate_count: 3, status: "working" },
      ],
    });
    expect(timeline.items).toEqual([]);
  });

  it("rejects invalid adaptive proposal cardinality instead of fabricating choices", () => {
    expect(() => normalizeAgentCanvasChatTimelineV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      creation_mode: "guided_production",
      recipe: {
        recipe_id: "recipe-invalid",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        skill_run_id: null,
        revision: 1,
        creation_mode: "guided_production",
        current_topic_id: "topic-scene",
        stages: [{
          topic_id: "topic-scene",
          topic_kind: "scene",
          title: "Scene design",
          objective: "Choose a setting.",
          applicability: "required",
          applicability_reason: "A setting is required.",
          specialist_name: "scene_designer",
          proposal_mode: "choice_set",
          candidate_count: 1,
          status: "working",
          related_node_ids: [],
        }],
        anchor_digest: "anchor-1",
        created_at: "2026-07-31T05:00:00Z",
        updated_at: "2026-07-31T05:01:00Z",
      },
      continuations: [],
      creative_session: null,
      items: [],
      next_cursor: 0,
    })).toThrowError(/candidate_count/i);
  });

  it("normalizes the backend creative session creation-mode decision", () => {
    const timeline = normalizeAgentCanvasChatTimelineV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      creative_session: {
        skill_run_id: "session-1",
        workflow_id: "workflow-1",
        skill_id: "platform-default",
        skill_version: "1",
        status: "active",
        creation_mode: {
          mode: "ordinary_conversation",
          reason: "The user is continuing an ordinary conversation.",
          target_node_id: null,
          target_asset_id: null,
        },
        active_recipe: null,
        creative_direction_snapshot_id: "direction-1",
        current_topic_id: "script",
        topics: [],
        deferred_topic_ids: [],
        memory_revision: 0,
        updated_at: "2026-07-31T07:56:23Z",
      },
      continuations: [],
      items: [],
      next_cursor: 0,
    });

    expect(timeline.creative_session?.creation_mode).toEqual({
      mode: "ordinary_conversation",
      reason: "The user is continuing an ordinary conversation.",
      target_node_id: null,
      target_asset_id: null,
    });
    expect(timeline.creative_session?.active_recipe).toBeNull();
  });

  it("normalizes creation-mode decisions returned on persisted chat turns", () => {
    const turn = normalizeAgentCanvasChatTurnV2({
      turn_id: "turn-creation-mode-1",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: "completed",
      turn_kind: "message",
      request: { content: "Continue" },
      error_code: null,
      error_message: null,
      creation_mode: {
        mode: "targeted_authoring",
        reason: "The user targeted an existing video node.",
        target_node_id: "node-video-1",
        target_asset_id: null,
      },
      recipe: null,
      continuation: null,
      created_at: "2026-07-31T07:56:23Z",
      updated_at: "2026-07-31T07:56:24Z",
    });

    expect(turn.creation_mode).toMatchObject({
      mode: "targeted_authoring",
      target_node_id: "node-video-1",
    });
  });

  it("normalizes canonical Ready variations, command plans, receipts, and layout responses", () => {
    const workflowPayload = validWorkflowPayload();
    workflowPayload.nodes[1] = {
      ...workflowPayload.nodes[1],
      status: "ready",
      variation_draft: {
        source_node_id: "node-image-1",
        source_node_revision: 5,
        title: "Lead Character - night",
        generation_prompt: "A cinematic night portrait.",
        model_id: "model-image-1",
        parameters: { stylization: 80 },
        variation_revision: 2,
        created_at: "2026-07-29T01:00:00Z",
        updated_at: "2026-07-29T01:05:00Z",
      },
    };
    const workflow = normalizeAgentCanvasWorkflowV2(workflowPayload);
    const timeline = normalizeAgentCanvasChatTimelineV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      items: [
        {
          entry_id: "entry-plan-1",
          workflow_id: "workflow-1",
          conversation_id: "conversation-1",
          sequence_no: 13,
          entry_type: "command_plan",
          speaker: null,
          content: "Delete one draft.",
          metadata: {},
          command_plan: {
            plan_id: "plan-1",
            workflow_id: "workflow-1",
            conversation_id: "conversation-1",
            source_turn_id: "turn-1",
            context_snapshot_id: "context-1",
            base_workflow_revision: 7,
            expires_at: "2026-07-29T01:16:00Z",
            operations: [{
              operation_type: "delete_node",
              operation_id: "delete-1",
              node: { kind: "node_id", node_id: "node-image-1" },
            }],
            continuation_requested: false,
            risk: "destructive_authoring",
            confirmation_required: true,
            target_summary: "Delete one draft.",
            operation_fingerprint: "fingerprint-1",
            idempotency_key: "plan-key-1",
            status: "pending_confirmation",
            supersedes_plan_id: null,
            replacement_plan_id: null,
            actor: "agent",
            created_at: "2026-07-29T01:06:00Z",
            updated_at: "2026-07-29T01:06:00Z",
          },
          action_receipt: null,
          created_at: "2026-07-29T01:06:00Z",
        },
        {
          entry_id: "entry-receipt-1",
          workflow_id: "workflow-1",
          conversation_id: "conversation-1",
          sequence_no: 14,
          entry_type: "action_receipt",
          speaker: null,
          content: "Created one sibling draft.",
          metadata: {},
          command_plan: null,
          action_receipt: {
            receipt_id: "receipt-1",
            workflow_id: "workflow-1",
            plan_id: null,
            action_id: "turn-action-1",
            status: "applied",
            summary: "Created one sibling draft.",
            created_node_ids: ["node-sibling-1"],
            updated_node_ids: [],
            deleted_node_ids: [],
            created_binding_ids: [],
            deleted_binding_ids: [],
            queued_execution_ids: ["execution-1"],
            run_queue_errors: [],
            operation_results: [],
            workflow_revision: 8,
            placement_hints: [{
              intent: "right_sibling",
              anchor_node_id: "node-image-1",
              group_key: null,
            }],
            continuation_turn_id: "turn-continuation-1",
            error_code: null,
            error_message: null,
          },
          created_at: "2026-07-29T01:07:00Z",
        },
      ],
      next_cursor: 14,
    });
    const layout = normalizeCanvasLayoutPatchResponseV2({
      workflow_id: "workflow-1",
      revision: 8,
      layout_revision: 4,
      positions: [{ node_id: "node-sibling-1", x: 840, y: 220 }],
    });
    const materialized = normalizeCanvasVariationMaterializeResponseV2({
      workflow_id: "workflow-1",
      workflow_revision: 8,
      source_node_id: "node-image-1",
      sibling_node: {
        ...workflowPayload.nodes[1],
        node_id: "node-sibling-1",
        status: "draft",
        output_asset_id: null,
        variation_draft: null,
      },
      copied_binding_ids: ["binding-copy-1"],
      run: {
        workflow_id: "workflow-1",
        execution_id: "execution-1",
        status: "queued",
      },
      run_error: null,
      placement_hint: {
        intent: "right_sibling",
        anchor_node_id: "node-image-1",
        group_key: null,
      },
    });

    expect(workflow.nodes[1]?.variation_draft?.variation_revision).toBe(2);
    expect(timeline.items.map((item) => item.item_type)).toEqual([
      "command_plan",
      "action_receipt",
    ]);
    expect(layout.layout_revision).toBe(4);
    expect(materialized.sibling_node.node_id).toBe("node-sibling-1");
    expect(materialized.run?.execution_id).toBe("execution-1");
  });

  it("normalizes runtime, capability, chat, and editing payloads with bounded defaults", () => {
    const runtime = normalizeCanvasRuntimeSnapshotV2({
      workflow_id: "workflow-1",
      active_execution_id: "exec-1",
      execution_status: "running",
      node_runtime: {
        "node-image-1": {
          node_id: "node-image-1",
          visible_status: "working",
          phase: "running",
          execution_id: "exec-1",
          provider_task_id: "task-1",
          waiting_for_node_ids: ["node-text-1"],
          blocked_by_node_ids: ["node-script-1"],
          attempt_no: 2,
          updated_at: "2026-07-28T10:08:00Z",
          error: null,
        },
      },
      queued_node_ids: [],
      working_node_ids: ["node-image-1"],
      waiting_node_ids: [],
      ready_node_ids: ["node-text-1"],
      failed_node_ids: [],
      events_cursor: 42,
      updated_at: "2026-07-28T10:08:00Z",
    });

    const capabilities = normalizeProviderModelCapabilityListV2({
      items: [{
        provider: "openai",
        model_id: "gpt-image-1",
        output_type: "image",
        accepted_input_types: ["text", "image"],
        max_references: 8,
        reference_limits: {
          image: 8,
          video: 0,
          audio: 0,
        },
        supported_parameters: ["size", "quality"],
        supported_aspect_ratios: ["1:1", "16:9"],
        duration_range_seconds: null,
        pixel_bounds: [512, 2048],
        available: true,
        unavailable_reason: null,
      }],
    });

    const timeline = normalizeChatTimelineListResponseV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      items: [
        {
          item_type: "message",
          message_id: "message-1",
          conversation_id: "conversation-1",
          speaker: "adcraft_video_agent",
          text: "I prepared some options.",
          linked_node_ids: ["node-text-1"],
          script_node_id: null,
          proposal_id: "proposal-1",
          sequence: 11,
          created_at: "2026-07-28T10:09:00Z",
        },
        {
          item_type: "proposal",
          proposal: {
            proposal_id: "proposal-1",
            workflow_id: "workflow-1",
            turn_id: "turn-1",
            video_skill_run_id: "session-1",
            topic_id: "characters",
            creative_direction_snapshot_id: null,
            proposal_revision: 1,
            source_proposal_id: null,
            proposal_kind: "character",
            specialist_name: "character_designer",
            status: "pending",
            options: [
              {
                option_id: "option-1",
                title: "Option A",
                summary_prompt: "Athletic streetwear lead.",
              },
            ],
            proposed_references: [],
            selected_option_id: null,
            selection_actor: null,
            created_at: "2026-07-28T10:09:00Z",
            updated_at: "2026-07-28T10:09:00Z",
          },
          sequence: 12,
          created_at: "2026-07-28T10:09:01Z",
        },
      ],
      next_after_seq: 12,
    });

    const editing = normalizeEditingNodeContentV2({
      manifest: {
        video_entries: [
          {
            binding_id: "binding-video-1",
            asset_id: null,
            enabled: true,
            trim_start_seconds: 0,
            trim_end_seconds: null,
            volume: 1,
            preserve_native_audio: true,
            transition: "cut",
            transition_duration_seconds: 0,
            fit_mode: "fill",
          },
        ],
        bgm: null,
        output: {},
        manifest_revision: 4,
      },
      dirty: true,
      preview: {
        clips: [
          {
            reference_id: "binding-video-1",
            binding_id: "binding-video-1",
            node_id: "node-video-1",
            asset_id: "asset-video-1",
            status: "ready",
            display_order: 0,
            preview_url: "/api/v2/assets/asset-video-1/content",
            duration_seconds: 3.2,
            warning: null,
          },
        ],
        bgm_binding_id: null,
        bgm_node_id: null,
        bgm_asset_id: null,
        estimated_duration_seconds: 3.2,
        warnings: [],
      },
      last_successful_export: null,
      active_export: null,
    });

    expect(runtime.node_runtime["node-image-1"]?.attempt_no).toBe(2);
    expect(capabilities[0]?.accepted_input_types).toEqual(["text", "image"]);
    expect(timeline.items[1]?.item_type).toBe("proposal");
    expect(editing.manifest.bgm).toBeNull();
    expect(editing.manifest.video_entries[0]?.preserve_native_audio).toBe(true);
    expect(editing.manifest.output.video_codec).toBe("h264");
  });

  it("rejects malformed discriminators", () => {
    expect(() =>
      normalizeChatTimelineListResponseV2({
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        items: [
          {
            item_type: "unknown",
            sequence: 1,
            created_at: "2026-07-28T10:09:00Z",
          },
        ],
        next_after_seq: 1,
      }),
    ).toThrowError(/item_type/i);
  });

  it("rejects malformed node payloads", () => {
    expect(() =>
      normalizeCanvasNodeV2({
        ...validWorkflowPayload().nodes[0],
        position: { x: "120", y: 80 },
      }),
    ).toThrowError(/position/i);
  });

  it("accepts model selection fields returned by the canvas node API", () => {
    const node = {
      ...validWorkflowPayload().nodes[1],
      model_selection_mode: "explicit",
      model_ref: "fake:deterministic-image",
      model_summary: {
        model_ref: "fake:deterministic-image",
        provider_id: "fake",
        display_name: "Deterministic Image",
        capability: "image",
        availability: "available",
        unavailable_reason: null,
        catalog_revision: 3,
      },
    };
    delete node.model_id;

    const normalized = normalizeCanvasNodeV2(node);

    expect(normalized.model_id).toBeNull();
    expect(normalized.model_selection_mode).toBe("explicit");
    expect(normalized.model_ref).toBe("fake:deterministic-image");
    expect(normalized.model_summary?.display_name).toBe("Deterministic Image");
  });

  it("normalizes model selection on a variation draft without a raw model ID", () => {
    const normalized = normalizeCanvasVariationDraftV2({
      source_node_id: "node-image-1",
      source_node_revision: 2,
      title: "Amber product variation",
      generation_prompt: "Make the product lighting warmer.",
      model_selection_mode: "explicit",
      model_ref: "volcengine_ark:doubao-seedream-5-0-lite-260128",
      parameters: { aspect_ratio: "16:9" },
      variation_revision: 1,
      created_at: "2026-08-03T02:00:00Z",
      updated_at: "2026-08-03T02:00:00Z",
    });

    expect(normalized.model_selection_mode).toBe("explicit");
    expect(normalized.model_ref).toBe("volcengine_ark:doubao-seedream-5-0-lite-260128");
  });

  it("rejects malformed binding payloads", () => {
    expect(() =>
      normalizeCanvasBindingV2({
        ...validWorkflowPayload().bindings[0],
        source: { kind: "asset", asset_id: "asset-1" },
      }),
    ).toThrowError(/source/i);
  });

  it("rejects malformed runtime payloads", () => {
    expect(() =>
      normalizeCanvasRuntimeSnapshotV2({
        workflow_id: "workflow-1",
        active_execution_id: null,
        execution_status: "running",
        node_runtime: {},
        queued_node_ids: [],
        working_node_ids: [],
        waiting_node_ids: [],
        ready_node_ids: [],
        failed_node_ids: [],
        events_cursor: "42",
        updated_at: "2026-07-28T10:08:00Z",
      }),
    ).toThrowError(/events_cursor/i);
  });

  it("rejects malformed chat payloads", () => {
    expect(() =>
      normalizeChatTimelineListResponseV2({
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        items: [
          {
            item_type: "message",
            message_id: "message-1",
            conversation_id: "conversation-1",
            speaker: "director",
            text: "Hello",
            linked_node_ids: [],
            script_node_id: null,
            proposal_id: null,
            sequence: 1,
            created_at: "2026-07-28T10:09:00Z",
          },
        ],
        next_after_seq: 1,
      }),
    ).toThrowError(/speaker/i);
  });

  it("rejects malformed editing payloads", () => {
    expect(() =>
      normalizeEditingNodeContentV2({
        manifest: {
          video_entries: [],
          bgm: {
            binding_id: "binding-bgm-1",
            asset_id: null,
            enabled: true,
            trim_start_seconds: 0,
            trim_end_seconds: null,
            volume: 1.5,
            fade_in_seconds: 0,
            fade_out_seconds: 0,
          },
          output: {},
          manifest_revision: 4,
        },
        dirty: true,
        preview: {
          clips: [],
          bgm_binding_id: null,
          bgm_node_id: null,
          bgm_asset_id: null,
          estimated_duration_seconds: 0,
          warnings: [],
        },
        last_successful_export: null,
        active_export: null,
      }),
    ).toThrowError(/volume/i);
  });

  it("accepts shared events with asset details inside payload only", () => {
    const event = normalizeCanvasRuntimeEventV2({
      sequence_no: 51,
      workflow_id: "workflow-1",
      event_type: "asset_published",
      node_id: "node-image-1",
      binding_id: null,
      created_at: "2026-07-28T10:10:00Z",
      payload: {
        asset_id: "asset-output-2",
        provider_task_id: "task-2",
      },
    });

    expect(event.payload?.asset_id).toBe("asset-output-2");
  });

  it("normalizes the current backend event envelope into the shared event model", () => {
    const response = normalizeCanvasRuntimeEventsResponseV2({
      items: [{
        sequence_no: 52,
        workflow_id: "workflow-1",
        project_id: "project-1",
        event_type: "asset_published",
        execution_id: "execution-1",
        node_id: "node-image-1",
        asset_id: "asset-output-3",
        conversation_id: "conversation-1",
        turn_id: "turn-1",
        action_id: "action-1",
        trace_id: "0123456789abcdef0123456789abcdef",
        span_id: "0123456789abcdef",
        payload: {},
        created_at: "2026-07-28T10:10:01Z",
      }],
      next_cursor: 52,
    });

    expect(response).toMatchObject({
      workflow_id: null,
      next_cursor: 52,
      events: [{
        seq: 52,
        execution_id: "execution-1",
        asset_id: "asset-output-3",
        binding_id: null,
        project_id: "project-1",
        conversation_id: "conversation-1",
        turn_id: "turn-1",
        action_id: "action-1",
      }],
    });
  });

  it("accepts the frozen guided action chat turn kind", () => {
    expect(normalizeAgentCanvasChatTurnV2({
      turn_id: "turn-guided-1",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: "completed",
      turn_kind: "guided_action",
      request: { action_id: "action-1", confirmed: true },
      error_code: null,
      error_message: null,
      created_at: "2026-07-30T08:00:00Z",
      updated_at: "2026-07-30T08:00:01Z",
    }).turn_kind).toBe("guided_action");
  });

  it("accepts the backend capability list envelope", () => {
    const capabilities = normalizeProviderModelCapabilityListV2({
      items: [{
        provider: "volcengine",
        model_id: "seedance",
        output_type: "video",
        accepted_input_types: ["text", "image"],
        max_references: 4,
        reference_limits: {
          image: 4,
          video: 1,
          audio: 1,
        },
        supported_parameters: [],
        supported_aspect_ratios: ["16:9"],
        duration_range_seconds: [3, 12],
        pixel_bounds: null,
        available: true,
        unavailable_reason: null,
        supports_native_audio: true,
      }],
    });

    expect(capabilities[0]?.supports_native_audio).toBe(true);
    expect(capabilities[0]?.reference_limits).toEqual({
      image: 4,
      video: 1,
      audio: 1,
    });
  });

  it("normalizes the persisted Agent Canvas conversation timeline", () => {
    const timeline = normalizeAgentCanvasChatTimelineResponseV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      items: [
        {
          entry_id: "entry-1",
          workflow_id: "workflow-1",
          conversation_id: "conversation-1",
          sequence_no: 1,
          entry_type: "message",
          speaker: "user",
          content: "Create a summer campaign.",
          metadata: { mentioned_node_ids: [] },
          created_at: "2026-07-28T10:10:00Z",
        },
        {
          entry_id: "entry-2",
          workflow_id: "workflow-1",
          conversation_id: "conversation-1",
          sequence_no: 2,
          entry_type: "script_artifact",
          speaker: null,
          content: "View Script",
          metadata: { node_id: "node-script-1" },
          created_at: "2026-07-28T10:10:01Z",
        },
      ],
      next_cursor: 2,
    });

    expect(timeline.items[1]?.entry_type).toBe("script_artifact");
  });

  it("enforces ready media output and positive revisions", () => {
    expect(() =>
      normalizeCanvasNodeV2({
        ...validWorkflowPayload().nodes[1],
        status: "ready",
        output_asset_id: null,
      }),
    ).toThrowError(/output_asset_id/i);
    expect(() =>
      normalizeCanvasNodeV2({
        ...validWorkflowPayload().nodes[0],
        revision: 0,
      }),
    ).toThrowError(/revision/i);
    expect(() =>
      normalizeAgentCanvasWorkflowV2({
        ...validWorkflowPayload(),
        revision: 0,
      }),
    ).toThrowError(/revision/i);
  });

  it("enforces project asset geometry, duration, and browser-safe URLs", () => {
    const validAsset = validWorkflowPayload().assets[0];
    expect(() => normalizeProjectAssetSummaryV2({ ...validAsset, width: 0 })).toThrowError(/width/i);
    expect(() => normalizeProjectAssetSummaryV2({ ...validAsset, duration_seconds: -1 })).toThrowError(/duration_seconds/i);
    expect(() => normalizeProjectAssetSummaryV2({ ...validAsset, media_url: "/tmp/private.png" })).toThrowError(/media_url/i);
  });

  it("validates media access descriptors and source identity", () => {
    const nodeSnapshot = {
      snapshot_type: "media",
      source_kind: "node_output",
      source_node_id: "node-image-1",
      source_node_revision: 2,
      binding_kind: "image_reference",
      source_semantic_role: "storyboard_sequence",
      asset_id: "asset-output-1",
      media_type: "image",
      asset_checksum: "checksum-1",
      access_descriptor: {
        descriptor_type: "asset_content",
        asset_id: "asset-output-1",
        media_url: "/api/v2/assets/asset-output-1/content",
        checksum: "checksum-1",
      },
      binding_id: "binding-image-1",
      input_role: "image_reference",
      required: true,
      display_order: 1,
    };
    expect(normalizeResolvedMediaInputSnapshotV2(nodeSnapshot)).toMatchObject({
      source_node_id: "node-image-1",
      source_semantic_role: "storyboard_sequence",
      binding_id: "binding-image-1",
      input_role: "image_reference",
      required: true,
      display_order: 1,
    });
    expect(() =>
      normalizeResolvedMediaInputSnapshotV2({
        ...nodeSnapshot,
        source_kind: "image_asset",
      }),
    ).toThrowError(/node identity/i);
    expect(() =>
      normalizeResolvedMediaInputSnapshotV2({
        ...nodeSnapshot,
        access_descriptor: {
          ...nodeSnapshot.access_descriptor,
          media_url: "/tmp/private.png",
        },
      }),
    ).toThrowError(/media_url/i);
  });

  it("preserves resolved text binding audit fields", () => {
    expect(normalizeResolvedTextInputSnapshotV2({
      snapshot_type: "text",
      source_kind: "node_output",
      source_node_id: "node-script-1",
      source_node_revision: 3,
      binding_kind: "text_context",
      document_kind: "script",
      content: "Scene one.",
      content_hash: "hash-script-1",
      binding_id: "binding-script-1",
      input_role: "text_context",
      required: true,
      display_order: 0,
    })).toMatchObject({
      source_kind: "node_output",
      binding_id: "binding-script-1",
      input_role: "text_context",
      required: true,
      display_order: 0,
    });
  });

  it("accepts joined Run and idempotently completed Editing export responses", () => {
    expect(normalizeCanvasRunAcceptedV2({
      workflow_id: "workflow-1",
      execution_id: "execution-1",
      status: "partial_completed",
      accepted_node_ids: [],
      joined_node_ids: ["node-image-1"],
      skipped: [],
      waiting_node_ids: [],
      events_cursor: 18,
    }).status).toBe("partial_completed");

    expect(normalizeEditingExportAcceptedV2({
      workflow_id: "workflow-1",
      node_id: "node-editing-1",
      export_id: "export-1",
      status: "completed",
      manifest_revision: 3,
      ready_video_node_ids: ["node-video-1"],
      skipped_inputs: [],
      bgm_node_id: null,
      events_cursor: 19,
    }).status).toBe("completed");
  });

  it("preserves the final Video Skill Run session fields", () => {
    expect(normalizeAgentCanvasVideoSkillRunV2({
      skill_run_id: "skill-run-1",
      workflow_id: "workflow-1",
      skill_id: "video-ad",
      skill_version: "1",
      source_skill_run_id: null,
      status: "active",
      current_topic_id: "characters",
      deferred_topic_ids: ["bgm"],
      memory_revision: 3,
      created_at: "2026-07-30T08:00:00Z",
      updated_at: "2026-07-30T08:01:00Z",
    })).toMatchObject({
      status: "active",
      current_topic_id: "characters",
      deferred_topic_ids: ["bgm"],
      memory_revision: 3,
      updated_at: "2026-07-30T08:01:00Z",
    });
  });

  it("applies OpenAPI defaults to a minimal Video Skill Run response", () => {
    expect(normalizeAgentCanvasVideoSkillRunV2({
      skill_run_id: "skill-run-minimal",
      workflow_id: "workflow-1",
      skill_id: "video-ad",
      skill_version: "1",
      source_skill_run_id: null,
      created_at: "2026-07-30T08:00:00Z",
    })).toMatchObject({
      status: "active",
      current_topic_id: null,
      deferred_topic_ids: [],
      memory_revision: 0,
      updated_at: null,
    });
  });
});
