import { describe, expect, it } from "vitest";

import {
  normalizeAgentCanvasChatTimelineCompatV2,
  normalizeAgentCanvasWorkflowV2,
  normalizeAgentCanvasChatTimelineResponseV2,
  normalizeCanvasBindingV2,
  normalizeCanvasLayoutPatchResponseV2,
  normalizeCanvasNodeV2,
  normalizeCanvasRuntimeEventV2,
  normalizeCanvasRuntimeEventsResponseV2,
  normalizeCanvasRuntimeSnapshotV2,
  normalizeCanvasRunAcceptedV2,
  normalizeCanvasVariationMaterializeResponseV2,
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
        semantic_role: "brief",
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
        video_skill_run_id: "skill-run-1",
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
        semantic_role: "character_main",
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
        video_skill_run_id: "skill-run-1",
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
        source: { kind: "node", node_id: "node-text-1" },
        target_node_id: "node-image-1",
        binding_kind: "brief_context",
        input_role: "instruction",
        required: true,
        display_order: 0,
        created_at: "2026-07-28T10:06:30Z",
      },
      {
        binding_id: "binding-2",
        workflow_id: "workflow-1",
        source: { kind: "image_asset", asset_id: "asset-library-1" },
        target_node_id: "node-image-1",
        binding_kind: "image_reference",
        input_role: "visual_reference",
        required: false,
        display_order: 1,
        created_at: "2026-07-28T10:06:31Z",
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
        source_semantic_role: "storyboard_grid",
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
  it("normalizes a complete canonical workflow payload", () => {
    const workflow = normalizeAgentCanvasWorkflowV2(validWorkflowPayload());

    expect(workflow.canvas_model).toBe("agent_canvas_v1");
    expect(workflow.revision).toBe(7);
    expect(workflow.layout_revision).toBe(3);
    expect(workflow.nodes).toHaveLength(2);
    expect(workflow.bindings[1]?.source.kind).toBe("image_asset");
    expect(workflow.assets[0]?.checksum).toBe("sha256-output-1");
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
    const timeline = normalizeAgentCanvasChatTimelineCompatV2({
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
            base_workflow_revision: 7,
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

    const capabilities = normalizeProviderModelCapabilityListV2([
      {
        provider: "openai",
        model_id: "gpt-image-1",
        output_type: "image",
        accepted_input_types: ["text", "image"],
        max_references: 8,
        supported_parameters: ["size", "quality"],
        supported_aspect_ratios: ["1:1", "16:9"],
        duration_range_seconds: null,
        pixel_bounds: [512, 2048],
        available: true,
        unavailable_reason: null,
      },
    ]);

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
            specialist: "character_designer",
            status: "pending",
            options: [
              {
                option_id: "option-1",
                display_name: "Option A",
                summary_prompt: "Athletic streetwear lead.",
                semantic_role: "character_main",
                proposed_node_type: "image",
                reference_node_ids: ["node-text-1"],
                reference_image_asset_ids: ["asset-library-1"],
              },
            ],
            workflow_revision: 7,
            selection_actor: null,
          },
          sequence: 12,
          created_at: "2026-07-28T10:09:01Z",
        },
      ],
      next_after_seq: 12,
    });

    const editing = normalizeEditingNodeContentV2({
      manifest: {
        ordered_video_binding_ids: ["binding-video-1"],
        manifest_revision: 4,
      },
      dirty: true,
      preview: {
        clips: [
          {
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
    expect(editing.manifest.bgm_volume).toBe(0.2);
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

  it("rejects malformed binding payloads", () => {
    expect(() =>
      normalizeCanvasBindingV2({
        ...validWorkflowPayload().bindings[0],
        source: { kind: "asset", asset_id: "asset-1" },
      }),
    ).toThrowError(/source/i);
  });

  it("accepts canonical binding input roles and rejects domain-specific roles", () => {
    expect(normalizeCanvasBindingV2(validWorkflowPayload().bindings[1]).input_role)
      .toBe("visual_reference");
    expect(() =>
      normalizeCanvasBindingV2({
        ...validWorkflowPayload().bindings[1],
        input_role: "storyboard_sequence",
      }),
    ).toThrowError(/input_role/i);
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
          ordered_video_binding_ids: ["binding-video-1"],
          bgm_volume: 1.5,
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
    ).toThrowError(/bgm_volume/i);
  });

  it("accepts shared events with asset details inside payload only", () => {
    const event = normalizeCanvasRuntimeEventV2({
      seq: 51,
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
        event_type: "asset_published",
        execution_id: "execution-1",
        node_id: "node-image-1",
        asset_id: "asset-output-3",
        payload: {},
        created_at: "2026-07-28T10:10:01Z",
      }],
      next_cursor: 52,
    });

    expect(response).toMatchObject({
      workflow_id: null,
      next_after_seq: 52,
      events: [{
        seq: 52,
        execution_id: "execution-1",
        asset_id: "asset-output-3",
        binding_id: null,
      }],
    });
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
          image: 9,
          video: 3,
          audio: 3,
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
      image: 9,
      video: 3,
      audio: 3,
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
      source_kind: "node",
      source_node_id: "node-image-1",
      source_node_revision: 2,
      binding_kind: "image_reference",
      binding_id: "binding-image-1",
      input_role: "visual_reference",
      required: true,
      display_order: 2,
      source_semantic_role: "storyboard_grid",
      asset_id: "asset-output-1",
      media_type: "image",
      asset_checksum: "checksum-1",
      access_descriptor: {
        descriptor_type: "asset_content",
        asset_id: "asset-output-1",
        media_url: "/api/v2/assets/asset-output-1/content",
        checksum: "checksum-1",
      },
    };
    expect(normalizeResolvedMediaInputSnapshotV2(nodeSnapshot)).toMatchObject({
      source_node_id: "node-image-1",
      binding_id: "binding-image-1",
      input_role: "visual_reference",
      required: true,
      display_order: 2,
      source_semantic_role: "storyboard_grid",
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

  it("preserves ordered binding metadata on resolved text inputs", () => {
    expect(normalizeResolvedTextInputSnapshotV2({
      snapshot_type: "text",
      source_kind: "node",
      source_node_id: "node-script-1",
      source_node_revision: 4,
      binding_kind: "script_context",
      document_kind: "script",
      content: "Open on the product.",
      content_hash: "sha256-script",
      binding_id: "binding-script-1",
      input_role: "instruction",
      required: true,
      display_order: 0,
    })).toMatchObject({
      binding_id: "binding-script-1",
      input_role: "instruction",
      required: true,
      display_order: 0,
    });
  });

  it("accepts joined Run and idempotently completed Editing export responses", () => {
    expect(normalizeCanvasRunAcceptedV2({
      workflow_id: "workflow-1",
      execution_id: "execution-1",
      status: "running",
      accepted_node_ids: [],
      joined_node_ids: ["node-image-1"],
      skipped: [],
      waiting_node_ids: [],
      events_cursor: 18,
    }).status).toBe("running");

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
});
