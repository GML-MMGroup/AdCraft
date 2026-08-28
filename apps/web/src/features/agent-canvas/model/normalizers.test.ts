import { describe, expect, it } from "vitest";

import {
  normalizeAgentActionReceiptV2,
  normalizeAgentCanvasChatTimelineV2,
  normalizeAgentCanvasProjectCreateResponseV2,
  normalizeAgentCanvasChatTurnV2,
  normalizeAgentCanvasVideoSkillRunV2,
  normalizeAgentCanvasWorkflowV2,
  normalizeAgentCanvasChatTimelineResponseV2,
  normalizeAgentExecutionSettingsV2,
  normalizeAgentWorkingDocumentPageV2,
  normalizeAgentWorkingDocumentV2,
  normalizeCanvasBindingV2,
  normalizeCanvasEditingExportImportResponseV2,
  normalizeCanvasLayoutPatchResponseV2,
  normalizeCanvasNodeV2,
  normalizeCanvasPostReadyCheckpointV2,
  normalizeCanvasRuntimeEventV2,
  normalizeCanvasRuntimeEventsResponseV2,
  normalizeCanvasRuntimeSnapshotV2,
  normalizeCanvasRunAcceptedV2,
  normalizeCanvasVariationDraftV2,
  normalizeCanvasVariationMaterializeResponseV2,
  normalizeChatTurnAcceptedV2,
  normalizeChatTimelineListResponseV2,
  normalizeConceptProposalV2,
  normalizeEditingNodeContentV2,
  normalizeEditingExportAcceptedV2,
  normalizeGuidedSessionStateV2,
  normalizeProjectAssetUploadResponseV2,
  normalizeProjectAssetSummaryV2,
  normalizeProviderModelCapabilityListV2,
  normalizeResolvedMediaInputSnapshotV2,
  normalizeResolvedTextInputSnapshotV2,
  normalizeVideoSkillCatalogResponseV2,
  normalizeVideoSkillPublicDetailV2,
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
        execution_mode: "source_only",
        summary_prompt: "A compact brand brief.",
        generation_prompt: null,
        structured_content: { markdown: "# Brief" },
        model_id: null,
        parameters: {},
        parameter_provenance: {},
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
        execution_mode: "generative",
        summary_prompt: "Main character portrait.",
        generation_prompt: "High detail cinematic portrait.",
        structured_content: {},
        model_id: "model-image-1",
        parameters: { stylization: 100 },
        parameter_provenance: {},
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

function progressiveGuidanceSessionPayload() {
  return {
    session_id: "guidance-1",
    workflow_id: "workflow-1",
    status: "active",
    response_locale: "zh-CN",
    goal: {
      requested_output: "video",
      delivery_scope: "generated_media",
      summary: "Create a calm product advertisement.",
      explicit_constraints: { dialogue: "none" },
    },
    creative_authority: {
      authority: "user",
      source: "explicit_user",
      decided_at_turn_id: "turn-authority-1",
      revision: 1,
    },
    current_checkpoint: {
      checkpoint_id: "checkpoint-1",
      workflow_id: "workflow-1",
      session_revision: 3,
      stage_kind: "scene",
      status: "waiting_user",
      trigger: "user_message",
      action_id: null,
    },
    narrative_direction: "A quiet product ritual that builds toward a precise reveal.",
    element_decisions: [{
      element_kind: "character",
      presence: "exclude",
      authority: "user",
      requirements: {},
      source: "explicit_user",
    }],
    current_topic_id: "topic-scene",
    topics: [{
      topic_id: "topic-scene",
      topic_kind: "scene",
      title: "Scene direction",
      status: "proposed",
      capability_id: "scene_design",
      capability_display_name: "Scene Designer",
      related_node_ids: [],
      source_proposal_id: "proposal-scene-1",
      revision: 2,
    }],
    active_proposal_id: "proposal-scene-1",
    active_style_skill_run_id: "style-run-1",
    completion: {
      authoring: "not_ready",
      delivery: "not_ready",
      editing_preparation: "not_ready",
      editing_node_id: null,
      matching_node_ids: [],
      matching_asset_ids: [],
    },
    journey: {
      policy_version: "fixed_ad_production_v2",
      stage: "scene",
      stage_status: "waiting_user",
      stage_revision: 4,
      decisions: [{
        decision_id: "decision:scene:1",
        element_kind: "scene",
        occurrence_id: "occurrence:scene:1",
        occurrence_index: 1,
        outcome: "unresolved",
        source: "user",
        source_revision: 2,
        requirements: {},
      }],
      active_occurrence_id: "occurrence:scene:1",
      active_action: {
        action_id: "journey-action-1",
        action_kind: "invoke_capability",
        stage: "scene",
        stage_revision: 4,
        status: "waiting_user",
        turn_id: "turn-scene-1",
        occurrence_id: "occurrence:scene:1",
      },
      suspended_action: null,
      transition_evidence: [{
        evidence_id: "evidence-1",
        evidence_kind: "clarification_completed",
        source_id: "turn-clarification-1",
        source_revision: 2,
        stage: "scene",
        stage_revision: 4,
        occurrence_id: "occurrence:scene:1",
        actor: "system",
        recorded_at: "2026-08-04T09:00:00Z",
      }],
    },
    revision: 3,
    updated_at: "2026-08-04T09:00:00Z",
  };
}

function productSourceGuidanceSessionPayload() {
  const base = progressiveGuidanceSessionPayload();
  return {
    ...base,
    current_checkpoint: { ...base.current_checkpoint, stage_kind: "product" },
    journey: {
      ...base.journey,
      stage: "product",
      active_action: { ...base.journey.active_action, stage: "product" },
    },
    interaction: {
      interaction_id: "interaction-product-main-1",
      workflow_id: "workflow-1",
      session_id: "guidance-1",
      checkpoint_id: "checkpoint-1",
      kind: "product_source",
      status: "open",
      response_locale: "zh-CN",
      expected_session_revision: 3,
      revision: 2,
      title: "Choose a Product source",
      context: "Upload the real Product or generate a visual direction.",
      content: {
        content_kind: "product_source",
        input_kind: "main",
        question_id: "product_main_source",
        prompt: "Choose the Product main source.",
        expected_guidance_revision: 6,
        min_asset_count: 1,
        max_asset_count: 1,
      },
      allowed_actions: ["select_source"],
      submit_path: "/api/v2/workflows/workflow-1/chat/interactions/interaction-product-main-1/submit",
      created_at: "2026-08-27T08:00:00Z",
      updated_at: "2026-08-27T08:00:00Z",
    },
    awaiting: {
      awaiting_id: "awaiting-product-main-1",
      workflow_id: "workflow-1",
      session_id: "guidance-1",
      checkpoint_id: "checkpoint-1",
      kind: "product_source",
      requires_user_action: true,
      resume_policy: "submit_interaction",
      interaction_id: "interaction-product-main-1",
      node_ids: [] as string[],
      stage: "product",
      stage_revision: 4,
      created_at: "2026-08-27T08:00:00Z",
    },
  };
}

describe("Agent Canvas normalizers", () => {
  it("accepts expert_activity_superseded in the canonical chat timeline", () => {
    const timeline = normalizeChatTimelineListResponseV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      guidance_advance_precondition: null,
      items: [{
        item_type: "expert_activity",
        activity_id: "activity-storyboard-1",
        turn_id: "turn-storyboard-1",
        capability_id: "storyboard_design",
        capability_display_name: "Storyboard Artist",
        status: "superseded",
        sequence: 43,
        started_at: "2026-08-21T06:17:00Z",
        finished_at: "2026-08-21T06:18:00Z",
        message: null,
        error_code: "guidance_revision_conflict",
        elapsed_ms: 60000,
        attempt_stage: "initial",
        retryable: false,
        validation_paths: [],
        suggested_actions: [],
        completion_mode: null,
        warning_code: null,
      }],
      next_after_seq: 43,
    });

    expect(timeline.items[0]).toMatchObject({
      item_type: "expert_activity",
      status: "superseded",
    });
  });

  it("projects expert_activity_superseded from persisted timeline entries", () => {
    const timeline = normalizeAgentCanvasChatTimelineV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      guidance_session: null,
      guidance_advance_precondition: null,
      continuations: [],
      current_session_actions: [],
      items: [{
        entry_id: "activity-entry-43",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        sequence_no: 43,
        entry_type: "expert_activity",
        speaker: null,
        content: "Storyboard Artist",
        metadata: {
          activity_id: "activity-storyboard-1",
          turn_id: "turn-storyboard-1",
          capability_id: "storyboard_design",
          capability_display_name: "Storyboard Artist",
          status: "superseded",
          message_key: "expert_activity.superseded",
          error_code: "guidance_revision_conflict",
        },
        command_plan: null,
        action_receipt: null,
        created_at: "2026-08-21T06:18:00Z",
      }],
      presentation_items: [],
      next_cursor: 43,
    });

    expect(timeline.items[0]).toMatchObject({
      item_type: "expert_activity",
      activity_id: "activity-storyboard-1",
      status: "superseded",
      message: null,
    });
  });

  it("rejects the retired fixed Journey V1 projection instead of migrating it in the browser", () => {
    const payload = progressiveGuidanceSessionPayload();

    expect(() => normalizeGuidedSessionStateV2({
      ...payload,
      journey: {
        policy_version: "fixed_ad_production_v1",
        stage: "foundation_design",
        stage_status: "waiting_user",
        stage_revision: 1,
        foundation_queue: [],
        foundation_cursor: null,
        active_action: null,
        suspended_action: null,
        transition_evidence: [],
      },
    })).toThrowError(/journey\.(policy_version|foundation_queue)/i);
  });

  it("keeps a durable decision-bundle timeline pointer without treating it as chat text", () => {
    const timeline = normalizeAgentCanvasChatTimelineV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      guidance_session: null,
      continuations: [],
      current_session_actions: [],
      items: [{
        entry_id: "decision-entry-1",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        sequence_no: 1,
        entry_type: "decision_bundle",
        speaker: null,
        content: "Choose the creative direction.",
        metadata: { bundle_id: "bundle-1" },
        command_plan: null,
        action_receipt: null,
        created_at: "2026-08-10T00:00:00Z",
      }],
      next_cursor: 1,
    });

    expect(timeline.items).toEqual([{
      item_type: "decision_bundle_pointer",
      bundle_id: "bundle-1",
      sequence: 1,
      created_at: "2026-08-10T00:00:00Z",
    }]);
  });

  it("accepts slim capability proposals and capability turns without guidance decisions", () => {
    const proposal = normalizeConceptProposalV2({
      proposal_id: "proposal-product-1",
      workflow_id: "workflow-1",
      turn_id: "turn-product-1",
      video_skill_run_id: null,
      topic_id: "topic-product",
      creative_direction_snapshot_id: null,
      proposal_revision: 1,
      source_proposal_id: null,
      proposal_kind: "product",
      capability_id: "product_design",
      capability_display_name: "Product Designer",
      options: [{
        option_id: "option-product-1",
        title: "Quiet Precision",
        public_summary: "A restrained premium product direction.",
        key_decisions: ["Keep the silhouette compact.", "Use a restrained metallic finish."],
      }],
      proposed_references: [{
        source_kind: "node",
        source_id: "node-world-setting-1",
        binding_kind: "text_context",
        input_role: "text_context",
        required: true,
        display_order: 0,
        semantic_reference_role: "world_setting_reference",
        display_name: "World Setting",
        media_type: "text",
      }],
      target_node_id: null,
      target_node_revision: null,
      proposal_purpose: "Define the product direction.",
      availability: "open",
      application_count: 0,
      latest_application: null,
      materialization: {
        materialization_id: "materialization-product-1",
        option_id: "option-product-1",
        turn_id: "turn-materialization-1",
        status: "failed",
        attempt_no: 1,
        retryable: true,
        error: {
          code: "capability_materialization_failed",
          message: "The selected direction could not be prepared.",
        },
        created_at: "2026-08-07T01:00:01Z",
        updated_at: "2026-08-07T01:00:02Z",
      },
      guidance_session_id: "guidance-1",
      guidance_session_revision: 1,
      actions: [],
      created_at: "2026-08-07T01:00:00Z",
      updated_at: "2026-08-07T01:00:00Z",
    });
    const turn = normalizeAgentCanvasChatTurnV2({
      turn_id: "turn-product-1",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: "completed",
      turn_kind: "capability",
      request: {},
      error_code: null,
      error_message: null,
      creation_mode: null,
      guidance_session_revision: 1,
      continuation: null,
      created_at: "2026-08-07T01:00:00Z",
      updated_at: "2026-08-07T01:00:01Z",
    });

    expect(proposal).toMatchObject({
      capability_id: "product_design",
      capability_display_name: "Product Designer",
      options: [{
        public_summary: "A restrained premium product direction.",
        key_decisions: ["Keep the silhouette compact.", "Use a restrained metallic finish."],
      }],
      proposed_references: [{ semantic_reference_role: "world_setting_reference" }],
      materialization: {
        status: "failed",
        retryable: true,
        error: { code: "capability_materialization_failed" },
      },
    });
    expect(turn.turn_kind).toBe("capability");
  });

  it("accepts a public proposal option with redacted key decisions", () => {
    const proposal = normalizeConceptProposalV2({
      proposal_id: "proposal_164add5ec074134d7905953c0be81780",
      workflow_id: "adwf_v2_758d5ac55c609dc3",
      turn_id: "turn_aeb04c93ce6d69f4f14bd3f90673facd",
      video_skill_run_id: "skill_run_b9f5bf34b0624b6aba2ef5c4fec5d833",
      topic_id: "topic_world_setting",
      creative_direction_snapshot_id: "direction_31bcd1606e444dd59fcb0de5d4b5169b",
      proposal_revision: 1,
      source_proposal_id: null,
      proposal_kind: "world_setting",
      capability_id: "world_setting",
      capability_display_name: "World Setting Designer",
      options: [{
        option_id: "option_59d7f6dce6bb15c9ba2b8ff9e49ef022",
        title: "Warm family routine",
        public_summary: "A bright modern home shaped by calm morning and evening routines.",
      }, {
        option_id: "option_c91b1a664803e4e96b91493ecf9c3448",
        title: "Minimal fresh living space",
        public_summary: "A restrained modern interior with clean surfaces and soft neutral tones.",
      }, {
        option_id: "option_693fb095fed8d5187cb82afa115b736e",
        title: "Natural softness",
        public_summary: "A gentle natural world with warm wood, pale textiles, and soft daylight.",
      }],
      proposed_references: [],
      target_node_id: null,
      target_node_revision: null,
      proposal_purpose: "Create a tissue advertisement.",
      availability: "open",
      application_count: 0,
      latest_application: null,
      materialization: null,
      guidance_session_id: "guidance_ce0d6ee35bf64eb781475c8fa8cb09cd",
      guidance_session_revision: 4,
      actions: [],
      created_at: "2026-08-21T02:32:10.579220Z",
      updated_at: "2026-08-21T02:32:10.579220Z",
    });

    expect(proposal.options).toHaveLength(3);
    expect(proposal.options.every((option) => option.key_decisions.length === 0)).toBe(true);
  });

  it("accepts retry lineage and safe operation recovery state for chat turns", () => {
    const turn = normalizeAgentCanvasChatTurnV2({
      turn_id: "turn-retry-2",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: "running",
      turn_kind: "capability",
      request: {},
      creation_mode: null,
      guidance_session_revision: 12,
      continuation: null,
      retry_of_turn_id: "turn-failed-1",
      retry_attempt_no: 2,
      retryable: false,
      operation_stage: "validating",
      operation_failure: {
        code: "agent_provider_transport_failed",
        message: "The provider request could not be completed.",
        operation: "scene_design",
        capability_id: "scene_design",
        attempt_stage: "transport_retry",
        failure_stage: "provider",
        elapsed_ms: 5400,
        retryable: true,
        validation_paths: ["options[0].title"],
        occurred_at: "2026-08-11T10:00:01Z",
      },
      error_code: null,
      error_message: null,
      created_at: "2026-08-11T10:00:00Z",
      updated_at: "2026-08-11T10:00:01Z",
    });
    const accepted = normalizeChatTurnAcceptedV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      message_id: null,
      turn_id: "turn-retry-2",
      status: "queued",
      events_cursor: 42,
      retry_of_turn_id: "turn-failed-1",
      retry_attempt_no: 2,
      replayed: false,
      presentation_stream_id: "presentation-stream-1",
    });

    expect(turn).toMatchObject({
      retry_of_turn_id: "turn-failed-1",
      retry_attempt_no: 2,
      operation_stage: "validating",
      operation_failure: { code: "agent_provider_transport_failed" },
    });
    expect(accepted).toMatchObject({
      retry_of_turn_id: "turn-failed-1",
      retry_attempt_no: 2,
      replayed: false,
      presentation_stream_id: "presentation-stream-1",
    });
  });

  it("accepts the canonical World Setting node, proposal, guidance topic, and persisted binding", () => {
    const worldSettingDocument = {
      document_kind: "world_setting",
      contract_version: "world-setting-v2",
      content: "A near-future coastal city where quiet technology blends into daily rituals.",
      core: {
        premise: "Quiet technology is embedded in daily rituals.",
        era_and_place: "A near-future coastal city.",
        world_rules: ["Technology stays visually unobtrusive."],
        visual_continuity: ["Mist, pale stone, and restrained warm light recur."],
      },
      authoring_provenance: {
        source_proposal_id: "proposal-world-1",
        source_option_id: "world-option-1",
        materialization_run_id: "materialization-1",
        style_skill_run_id: null,
        creative_direction_snapshot_id: "direction-1",
      },
    };
    const workflow = normalizeAgentCanvasWorkflowV2({
      ...validWorkflowPayload(),
      nodes: [
        {
          ...validWorkflowPayload().nodes[0],
          node_id: "node-world-setting",
          creative_role: "world_setting",
          title: "World Setting",
          structured_content: worldSettingDocument,
        },
        validWorkflowPayload().nodes[1],
      ],
      bindings: [{
        binding_id: "binding-world-setting",
        workflow_id: "workflow-1",
        source: { kind: "node_output", source_node_id: "node-world-setting" },
        target_node_id: "node-image-1",
        input_role: "text_context",
        required: true,
        enabled: true,
        order: 0,
        label: "World Setting",
        metadata: { context_kind: "world_setting" },
        created_at: "2026-08-06T10:00:00Z",
        updated_at: "2026-08-06T10:00:00Z",
      }],
    });
    const proposal = normalizeConceptProposalV2({
      proposal_id: "proposal-world-1",
      workflow_id: "workflow-1",
      turn_id: "turn-world-1",
      video_skill_run_id: null,
      topic_id: "topic-world-setting",
      creative_direction_snapshot_id: "direction-1",
      proposal_revision: 1,
      source_proposal_id: null,
      proposal_kind: "world_setting",
      capability_id: "world_setting",
      capability_display_name: "World Setting Designer",
      options: [
        {
          option_id: "world-option-1",
          title: "Quiet future",
          public_summary: "A restrained near-future city.",
          key_decisions: ["Keep technology calm and unobtrusive."],
        },
        {
          option_id: "world-option-2",
          title: "Living heritage",
          public_summary: "Tradition expressed through modern craft.",
          key_decisions: ["Make craft heritage visible in the environment."],
        },
      ],
      proposed_references: [],
      target_node_id: null,
      target_node_revision: null,
      proposal_purpose: "Choose the production world",
      availability: "open",
      application_count: 0,
      latest_application: null,
      guidance_session_id: "guidance-1",
      guidance_session_revision: 4,
      actions: [
        {
          action_id: "world-select",
          action: "select_option",
          label: "Use this world",
          proposal_id: "proposal-world-1",
          expected_session_revision: 4,
          confirmation_required: false,
          reason: "Materialize the selected World Setting.",
        },
        {
          action_id: "world-revise",
          action: "revise_options",
          label: "Revise options",
          proposal_id: "proposal-world-1",
          expected_session_revision: 4,
          confirmation_required: false,
          reason: "Request revised World Setting options.",
        },
        {
          action_id: "world-delegate",
          action: "delegate_choice",
          label: "Let AdCraft choose",
          proposal_id: "proposal-world-1",
          expected_session_revision: 4,
          confirmation_required: false,
          reason: "Delegate the World Setting choice.",
        },
      ],
      created_at: "2026-08-06T10:00:00Z",
      updated_at: "2026-08-06T10:00:00Z",
    });
    const timeline = normalizeAgentCanvasChatTimelineV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      guidance_session: {
        ...progressiveGuidanceSessionPayload(),
        element_decisions: [{
          element_kind: "world_setting",
          presence: "include",
          authority: "user",
          requirements: { style: "quiet future" },
          source: "explicit_user",
        }],
        current_topic_id: "topic-world-setting",
        active_proposal_id: "proposal-world-1",
        topics: [{
          topic_id: "topic-world-setting",
          topic_kind: "world_setting",
          title: "World Setting",
          status: "proposed",
          capability_id: "world_setting",
          capability_display_name: "World Setting Designer",
          related_node_ids: ["node-world-setting"],
          source_proposal_id: "proposal-world-1",
          revision: 1,
        }],
      },
      continuations: [],
      current_session_actions: [],
      items: [],
      next_cursor: 0,
    });

    expect(workflow.nodes[0]).toMatchObject({
      creative_role: "world_setting",
      structured_content: worldSettingDocument,
    });
    expect(workflow.bindings[0]).toMatchObject({
      input_role: "text_context",
      required: true,
      metadata: { context_kind: "world_setting" },
    });
    expect(proposal.proposal_kind).toBe("world_setting");
    expect(proposal.options).toHaveLength(2);
    expect(timeline.guidanceSession?.element_decisions[0]?.element_kind).toBe("world_setting");
    expect(timeline.guidanceSession?.topics[0]?.topic_kind).toBe("world_setting");
    expect(timeline.guidanceSession?.creative_authority).toMatchObject({ authority: "user" });
    expect(timeline.guidanceSession?.current_checkpoint).toMatchObject({ stage_kind: "scene" });
  });

  it("normalizes superseded proposal actions and recoverable expert activity metadata", () => {
    const historicalProposal = normalizeConceptProposalV2({
      proposal_id: "proposal-history-1",
      workflow_id: "workflow-1",
      turn_id: "turn-proposal-1",
      video_skill_run_id: null,
      topic_id: "topic-scene",
      creative_direction_snapshot_id: null,
      proposal_revision: 2,
      source_proposal_id: null,
      proposal_kind: "scene",
      capability_id: "scene_design",
      capability_display_name: "Scene Designer",
      options: [{
        option_id: "option-scene-1",
        title: "Morning",
        public_summary: "Quiet morning light.",
        key_decisions: ["Use soft directional daylight."],
      }],
      proposed_references: [],
      target_node_id: null,
      target_node_revision: null,
      proposal_purpose: null,
      availability: "superseded",
      application_count: 0,
      latest_application: null,
      guidance_session_id: "guidance-1",
      guidance_session_revision: 3,
      actions: [{
        action_id: "reuse:proposal-history-1:option-scene-1:3",
        action: "reuse_direction",
        label: "Use this direction",
        proposal_id: "proposal-history-1",
        expected_session_revision: 3,
        confirmation_required: false,
        reason: "Publish this historical direction as a sibling Draft.",
        option_id: "option-scene-1",
        enabled: true,
        disabled_reason: null,
      }],
      created_at: "2026-08-07T00:00:00Z",
      updated_at: "2026-08-07T00:01:00Z",
    });
    const timeline = normalizeAgentCanvasChatTimelineV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      guidance_session: progressiveGuidanceSessionPayload(),
      continuations: [],
      current_session_actions: [{
        action_id: "authority-director",
        logical_key: "authority:director:3",
        action: "set_creative_authority",
        authority: "director",
        state: "pending",
        creating_turn_id: "turn-authority-2",
        expected_session_revision: 3,
        label: "Take the lead",
        workflow_id: "workflow-1",
        confirmation_required: false,
        reason: "Let the Director choose the next direction.",
      }],
      items: [{
        entry_id: "activity-entry-1",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        sequence_no: 4,
        entry_type: "expert_activity",
        speaker: null,
        content: "The Specialist request timed out.",
        metadata: {
          activity_id: "activity-1",
          capability_id: "scene_design",
          capability_display_name: "Scene Designer",
          operation: "materialize_draft",
          status: "failed",
          error_code: "agent_deadline_exceeded",
          elapsed_ms: 420000,
          attempt_stage: "transport_retry",
          retryable: true,
          validation_paths: ["draft.title"],
          operation_policy_id: "agent.materialization.v1",
          suggested_actions: ["retry", "revise_request"],
        },
        command_plan: null,
        action_receipt: null,
        created_at: "2026-08-07T01:00:00Z",
      }],
      next_cursor: 4,
    });

    expect(timeline.current_session_actions[0]).toMatchObject({
      action: "set_creative_authority",
      authority: "director",
    });
    expect(historicalProposal.actions[0]).toMatchObject({
      action: "reuse_direction",
      option_id: "option-scene-1",
      enabled: true,
    });
    expect(timeline.items[0]).toMatchObject({
      item_type: "expert_activity",
      activity_id: "activity-1",
      error_code: "agent_deadline_exceeded",
      message: "The Specialist request timed out.",
      retryable: true,
      suggested_actions: ["retry", "revise_request"],
    });
    expect(timeline.items[0]).not.toHaveProperty("operation");
    expect(timeline.items[0]).not.toHaveProperty("operation_policy_id");
  });

  it("accepts an open GuidedInteraction and legal durable awaiting state", () => {
    const session = normalizeGuidedSessionStateV2({
      ...progressiveGuidanceSessionPayload(),
      interaction: {
        interaction_id: "interaction-1", workflow_id: "workflow-1", session_id: "guidance-1", checkpoint_id: "checkpoint-1",
        kind: "concept_choice", status: "open", response_locale: "zh-CN", expected_session_revision: 3, revision: 2,
        title: "Choose scene", context: "Pick a scene direction.",
        content: { content_kind: "concept_choice", proposal_id: null,
          stage: "scene", stage_revision: 4, action_id: "action-scene-1",
          occurrence_id: "occurrence:scene:1", capability_id: "scene_design",
          allow_custom: true, allow_exclusion: false, options: [
          { option_id: "option-a", title: "Morning", summary: "Soft morning light." },
          { option_id: "option-b", title: "Evening", summary: "Warm evening light." },
          { option_id: "option-c", title: "Night", summary: "Focused night lighting.", recommended: true },
        ] },
        allowed_actions: ["select", "custom", "delegate"], submit_path: "/submit",
        created_at: "2026-08-15T10:00:00Z", updated_at: "2026-08-15T10:00:00Z",
      },
      awaiting: {
        awaiting_id: "awaiting-1", workflow_id: "workflow-1", session_id: "guidance-1", checkpoint_id: "checkpoint-1",
        kind: "concept_selection", requires_user_action: true, resume_policy: "submit_interaction",
        interaction_id: "interaction-1", node_ids: [], stage: "scene", stage_revision: 4,
        created_at: "2026-08-15T10:00:00Z",
      },
    });
    expect(session.interaction?.content.content_kind).toBe("concept_choice");
    expect(session.awaiting?.kind).toBe("concept_selection");
  });

  it("accepts the canonical Product source interaction and upload handoff", () => {
    const upload = normalizeProjectAssetUploadResponseV2({
      workflow_id: "workflow-1",
      asset: {
        asset_id: "asset-product-main",
        version_id: "version-product-main-1",
        project_id: "project-1",
        workflow_id: "workflow-1",
        media_type: "image",
        source_type: "upload",
        status: "ready",
        display_name: "Product main source",
        mime_type: "image/png",
        width: 1600,
        height: 1600,
        duration_seconds: null,
        checksum: "sha256-product-main",
        preview_url: "/api/v2/assets/asset-product-main/content",
        media_url: "/api/v2/assets/asset-product-main/content",
        created_at: "2026-08-27T08:00:00Z",
      },
      pending_handoff_id: "handoff-product-main-1",
    });
    const session = normalizeGuidedSessionStateV2({
      ...progressiveGuidanceSessionPayload(),
      current_checkpoint: {
        ...progressiveGuidanceSessionPayload().current_checkpoint,
        stage_kind: "product",
      },
      journey: {
        ...progressiveGuidanceSessionPayload().journey,
        stage: "product",
        active_action: {
          ...progressiveGuidanceSessionPayload().journey.active_action,
          stage: "product",
        },
      },
      interaction: {
        interaction_id: "interaction-product-main-1",
        workflow_id: "workflow-1",
        session_id: "guidance-1",
        checkpoint_id: "checkpoint-1",
        kind: "product_source",
        status: "open",
        response_locale: "zh-CN",
        expected_session_revision: 3,
        revision: 2,
        title: "Choose a Product source",
        context: "Upload the real Product or generate a visual direction.",
        content: {
          content_kind: "product_source",
          input_kind: "main",
          question_id: "product_main_source",
          prompt: "Choose the Product main source.",
          expected_guidance_revision: 6,
          min_asset_count: 1,
          max_asset_count: 1,
        },
        allowed_actions: ["select_source"],
        submit_path: "/api/v2/workflows/workflow-1/chat/interactions/interaction-product-main-1/submit",
        created_at: "2026-08-27T08:00:00Z",
        updated_at: "2026-08-27T08:00:00Z",
      },
      awaiting: {
        awaiting_id: "awaiting-product-main-1",
        workflow_id: "workflow-1",
        session_id: "guidance-1",
        checkpoint_id: "checkpoint-1",
        kind: "product_source",
        requires_user_action: true,
        resume_policy: "submit_interaction",
        interaction_id: "interaction-product-main-1",
        node_ids: [],
        stage: "product",
        stage_revision: 4,
        created_at: "2026-08-27T08:00:00Z",
      },
    });

    expect(upload.pending_handoff_id).toBe("handoff-product-main-1");
    expect(session.interaction?.content).toMatchObject({
      content_kind: "product_source",
      input_kind: "main",
      expected_guidance_revision: 6,
    });
    expect(session.awaiting?.kind).toBe("product_source");
  });

  it("rejects Product source cardinality and unknown content fields", () => {
    const wrongCount = productSourceGuidanceSessionPayload();
    wrongCount.interaction.content.min_asset_count = 2;
    expect(() => normalizeGuidedSessionStateV2(wrongCount)).toThrow(
      "Invalid creativeSession.interaction.content: invalid Product source asset count contract",
    );

    const unknownField = productSourceGuidanceSessionPayload();
    expect(() => normalizeGuidedSessionStateV2({
      ...unknownField,
      interaction: {
        ...unknownField.interaction,
        content: { ...unknownField.interaction.content, inferred_prompt: "do not accept" },
      },
    })).toThrow("Invalid creativeSession.interaction.content.inferred_prompt: unknown field");
  });

  it("rejects a Product source awaiting record that is not submit-authoritative", () => {
    const payload = productSourceGuidanceSessionPayload();
    expect(() => normalizeGuidedSessionStateV2({
      ...payload,
      awaiting: {
        ...payload.awaiting,
        resume_policy: "node_terminal",
        node_ids: ["node-product-1"],
      },
    })).toThrow("Invalid creativeSession.awaiting: invalid Product source awaiting authority");
  });

  it("retains immutable image AssetVersion identity in a binding source", () => {
    const binding = normalizeCanvasBindingV2({
      binding_id: "binding-versioned-image-1",
      workflow_id: "workflow-1",
      source: {
        kind: "image_asset",
        source_asset_id: "asset-product-main",
        source_asset_version_id: "version-product-main-1",
      },
      target_node_id: "node-image-1",
      input_role: "image_reference",
      required: true,
      enabled: true,
      order: 0,
      label: "Product main",
      metadata: {},
      created_at: "2026-08-27T08:00:00Z",
      updated_at: "2026-08-27T08:00:00Z",
    });

    expect(binding.source).toEqual({
      kind: "image_asset",
      source_asset_id: "asset-product-main",
      source_asset_version_id: "version-product-main-1",
    });
  });

  it("accepts canonical Character occurrence identity across journey, receipt, and continuation projections", () => {
    const session = normalizeGuidedSessionStateV2({
      ...progressiveGuidanceSessionPayload(),
      journey: {
        ...progressiveGuidanceSessionPayload().journey,
        stage: "character",
        decisions: [{
          decision_id: "decision:character:2",
          element_kind: "character",
          occurrence_id: "occurrence:character:2",
          occurrence_index: 2,
          outcome: "include",
          source: "user",
          source_revision: 6,
          requirements: {
            role: "Supporting athlete",
            identity_summary: "A calm teammate in the locker room.",
            presence: "required",
          },
        }],
        active_occurrence_id: "occurrence:character:2",
        active_action: {
          action_id: "action-character-2-turnaround",
          action_kind: "prepare_character_turnaround",
          stage: "character",
          stage_revision: 4,
          status: "working",
          turn_id: "turn-character-2",
          occurrence_id: "occurrence:character:2",
          character_phase: "turnaround",
        },
        transition_evidence: [{
          evidence_id: "evidence-character-2-main",
          evidence_kind: "character_materialized",
          source_id: "node-character-2-main",
          source_revision: 3,
          stage: "character",
          stage_revision: 4,
          occurrence_id: "occurrence:character:2",
          character_phase: "main",
          actor: "system",
          recorded_at: "2026-08-27T08:00:00Z",
        }],
      },
    });
    const receipt = normalizeAgentActionReceiptV2({
      receipt_id: "receipt-character-2-main",
      workflow_id: "workflow-1",
      plan_id: null,
      action_id: "action-character-2-main",
      proposal_id: null,
      proposal_option_id: null,
      proposal_action: null,
      actor_kind: "system",
      occurrence_id: "occurrence:character:2",
      character_phase: "main",
      idempotency_key: "character-2-main",
      status: "applied",
      summary: "Character main source published.",
      created_node_ids: ["node-character-2-main"],
      updated_node_ids: [],
      deleted_node_ids: [],
      created_binding_ids: [],
      deleted_binding_ids: [],
      queued_execution_ids: [],
      run_queue_errors: [],
      operation_results: [],
      workflow_revision: 12,
      before_workflow_revision: 11,
      placement_hints: [],
      continuation_turn_id: "turn-character-2-turnaround",
      superseded_by: null,
      error_code: null,
      error_message: null,
      created_at: "2026-08-27T08:00:00Z",
    });
    const timeline = normalizeAgentCanvasChatTimelineResponseV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      continuations: [{
        continuation_id: "continuation-character-2-turnaround",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        source_turn_id: "turn-character-2-main",
        continuation_turn_id: "turn-character-2-turnaround",
        operation: "continue_guidance",
        occurrence_id: "occurrence:character:2",
        character_phase: "turnaround",
        action_owner: "guided_journey",
        payload_digest: "digest-character-2",
        status: "queued",
        attempt_count: 0,
        max_attempts: 5,
        next_attempt_at: "2026-08-27T08:00:01Z",
        lease_owner: null,
        lease_generation: 0,
        lease_expires_at: null,
        last_error_code: null,
        last_error_message: null,
        created_at: "2026-08-27T08:00:00Z",
        updated_at: "2026-08-27T08:00:00Z",
      }],
      items: [],
      next_cursor: 0,
    });

    expect(session.journey.active_action?.character_phase).toBe("turnaround");
    expect(session.journey.transition_evidence[0]?.character_phase).toBe("main");
    expect(receipt).toMatchObject({ occurrence_id: "occurrence:character:2", character_phase: "main" });
    expect(timeline.continuations[0]).toMatchObject({
      occurrence_id: "occurrence:character:2",
      character_phase: "turnaround",
      action_owner: "guided_journey",
    });
  });

  it("preserves Character occurrence identity on proposed references", () => {
    const proposal = normalizeConceptProposalV2({
      proposal_id: "proposal-character",
      workflow_id: "workflow-1",
      turn_id: "turn-1",
      video_skill_run_id: null,
      topic_id: null,
      creative_direction_snapshot_id: null,
      proposal_revision: 1,
      source_proposal_id: null,
      proposal_kind: "character",
      capability_id: "character_design",
      capability_display_name: "Character Designer",
      options: [{ option_id: "option-1", title: "Lead", public_summary: "A composed lead." }],
      proposed_references: [{
        source_kind: "node",
        source_id: "node-character-main",
        binding_kind: "image_reference",
        input_role: "image_reference",
        required: true,
        display_order: 0,
        semantic_reference_role: "subject_reference",
        occurrence_id: "occurrence:character:2",
        character_phase: "main",
        display_name: "Lead main image",
        media_type: "image",
      }],
      target_node_id: null,
      target_node_revision: null,
      proposal_purpose: null,
      availability: "open",
      application_count: 0,
      latest_application: null,
      materialization: null,
      guidance_session_id: "session-1",
      guidance_session_revision: 1,
      actions: [],
      created_at: "2026-08-27T00:00:00Z",
      updated_at: "2026-08-27T00:00:00Z",
    });

    expect(proposal.proposed_references[0]).toMatchObject({
      occurrence_id: "occurrence:character:2",
      character_phase: "main",
    });
  });

  it("normalizes the complete guidance completion projection", () => {
    const session = normalizeGuidedSessionStateV2({
      ...progressiveGuidanceSessionPayload(),
      completion: {
        authoring: "ready",
        delivery: "ready",
        plan_document_id: "document-plan-1",
        plan_revision: 3,
        editing_preparation: "prepared",
        editing_node_id: "node-editing-1",
        preparation_receipt_id: "receipt-preparation-1",
        manifest_revision: 2,
        export_status: "completed",
        export_id: "export-1",
        final_completion_receipt_id: "receipt-completion-1",
        final_asset_id: "asset-final-1",
        matching_node_ids: ["node-video-1", "node-editing-1"],
        matching_asset_ids: ["asset-video-1", "asset-final-1"],
      },
    });

    expect(session.completion).toEqual({
      authoring: "ready",
      delivery: "ready",
      plan_document_id: "document-plan-1",
      plan_revision: 3,
      editing_preparation: "prepared",
      editing_node_id: "node-editing-1",
      preparation_receipt_id: "receipt-preparation-1",
      manifest_revision: 2,
      export_status: "completed",
      export_id: "export-1",
      final_completion_receipt_id: "receipt-completion-1",
      final_asset_id: "asset-final-1",
      matching_node_ids: ["node-video-1", "node-editing-1"],
      matching_asset_ids: ["asset-video-1", "asset-final-1"],
    });
  });

  it("normalizes the canonical progressive guidance timeline", () => {
    const timeline = normalizeAgentCanvasChatTimelineV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      guidance_session: progressiveGuidanceSessionPayload(),
      guidance_advance_precondition: {
        schema_version: "1",
        workflow_id: "workflow-1",
        workflow_revision: 9,
        session_id: "guidance-1",
        session_revision: 3,
        session_status: "active",
        journey_stage: "scene",
        journey_stage_status: "working",
        journey_stage_revision: 4,
        source_id: "stage:scene:4",
        requirement_revision_id: "requirement-1",
        requirement_digest: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        active_action_digest: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        owner_state_digest: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        authority_digest: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      },
      continuations: [{
        continuation_id: "continuation-1",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        source_turn_id: "turn-1",
        continuation_turn_id: "turn-2",
        operation: "resume_guidance",
        payload_digest: "digest-1",
        status: "superseded",
        attempt_count: 1,
        max_attempts: 3,
        next_attempt_at: "2026-08-04T09:01:00Z",
        lease_owner: null,
        lease_generation: 0,
        lease_expires_at: null,
        last_error_code: null,
        last_error_message: null,
        created_at: "2026-08-04T09:00:00Z",
        updated_at: "2026-08-04T09:01:00Z",
      }],
      current_session_actions: [{
        action_id: "guidance-1:3:stop_guidance",
        logical_key: "guidance-1:3:stop_guidance",
        action: "stop_guidance",
        state: "pending",
        creating_turn_id: "turn-2",
        expected_session_revision: 3,
        label: "Stop guidance",
        workflow_id: "workflow-1",
        confirmation_required: true,
        reason: "Pause the current guidance session.",
      }],
      items: [],
      next_cursor: 2,
    });

    expect(timeline.guidanceSession).toMatchObject({
      session_id: "guidance-1",
      revision: 3,
      response_locale: "zh-CN",
      goal: { requested_output: "video" },
    });
    expect(timeline.current_session_actions[0]).toMatchObject({
      action: "stop_guidance",
      expected_session_revision: 3,
    });
    expect(timeline.continuations[0]?.delivery_status).toBe("superseded");
    expect(timeline.guidanceAdvancePrecondition?.authority_digest)
      .toBe("sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd");
  });

  it("normalizes progressive proposal descriptors and application receipts", () => {
    const proposal = normalizeConceptProposalV2({
      proposal_id: "proposal-scene-1",
      workflow_id: "workflow-1",
      turn_id: "turn-1",
      video_skill_run_id: "style-run-1",
      topic_id: "topic-scene",
      creative_direction_snapshot_id: "direction-1",
      proposal_revision: 1,
      source_proposal_id: null,
      proposal_kind: "scene",
      capability_id: "scene_design",
      capability_display_name: "Scene Designer",
      options: [{
        option_id: "scene-1",
        title: "Quiet studio",
        public_summary: "A calm daylight studio.",
        key_decisions: ["Keep the set minimal and naturally lit."],
      }],
      proposed_references: [],
      target_node_id: null,
      target_node_revision: null,
      proposal_purpose: "Choose the setting",
      availability: "open",
      application_count: 1,
      latest_application: {
        application_id: "application-1",
        option_id: "scene-custom-1",
        action: "custom_direction",
        receipt_id: "receipt-1",
        created_node_ids: ["node-scene-1"],
        queued_execution_ids: [],
        created_at: "2026-08-04T09:02:00Z",
      },
      guidance_session_id: "guidance-1",
      guidance_session_revision: 3,
      actions: [{
        action_id: "proposal-scene-1:1:select_option",
        action: "select_option",
        label: "Select",
        proposal_id: "proposal-scene-1",
        expected_session_revision: 3,
        confirmation_required: false,
        reason: "Create one editable Draft.",
      }, {
        action_id: "proposal-scene-1:1:custom_direction",
        action: "custom_direction",
        label: "Use a custom direction",
        proposal_id: "proposal-scene-1",
        expected_session_revision: 3,
        confirmation_required: false,
        reason: "Submit a user-authored direction for this topic.",
      }],
      created_at: "2026-08-04T09:00:00Z",
      updated_at: "2026-08-04T09:02:00Z",
    });
    const receipt = normalizeAgentActionReceiptV2({
      receipt_id: "receipt-1",
      workflow_id: "workflow-1",
      plan_id: null,
      action_id: "proposal-scene-1:1:select_option",
      proposal_id: "proposal-scene-1",
      proposal_option_id: "scene-1",
      proposal_action: "select_option",
      actor_kind: "user",
      idempotency_key: "proposal-select-1",
      status: "applied",
      summary: "Created a scene draft.",
      created_node_ids: ["node-scene-1"],
      updated_node_ids: [],
      deleted_node_ids: [],
      created_binding_ids: [],
      deleted_binding_ids: [],
      queued_execution_ids: [],
      run_queue_errors: [],
      operation_results: [],
      workflow_revision: 4,
      before_workflow_revision: 3,
      placement_hints: [],
      continuation_turn_id: null,
      superseded_by: null,
      error_code: null,
      error_message: null,
      created_at: "2026-08-04T09:02:00Z",
    });

    expect(proposal.actions[0]).toMatchObject({
      action: "select_option",
      expected_session_revision: 3,
    });
    expect(proposal.actions[1]).toMatchObject({
      action: "custom_direction",
      expected_session_revision: 3,
    });
    expect(proposal.latest_application?.action).toBe("custom_direction");
    expect(receipt).toMatchObject({
      proposal_id: "proposal-scene-1",
      proposal_option_id: "scene-1",
      proposal_action: "select_option",
    });
  });

  it("normalizes progressive turn, provider capability, and style skill projections", () => {
    const turn = normalizeAgentCanvasChatTurnV2({
      turn_id: "turn-1",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: "completed",
      turn_kind: "message",
      request: { text: "Make a calm ad." },
      creation_mode: null,
      guidance_session_revision: 3,
      continuation: null,
      error_code: null,
      error_message: null,
      created_at: "2026-08-04T09:00:00Z",
      updated_at: "2026-08-04T09:01:00Z",
    });
    const capabilities = normalizeProviderModelCapabilityListV2({
      items: [{
        provider: "volcengine",
        model_id: "image-model-1",
        output_type: "image",
        accepted_input_types: ["text", "image"],
        max_references: 4,
        reference_limits: { image: 4 },
        supported_parameters: ["size"],
        supported_aspect_ratios: ["16:9"],
        duration_range_seconds: null,
        pixel_bounds: [512, 2048],
        available: true,
        unavailable_reason: null,
        supports_native_audio: false,
        capability_revision: 8,
      }],
    });
    const skillRun = normalizeAgentCanvasVideoSkillRunV2({
      skill_run_id: "style-run-1",
      workflow_id: "workflow-1",
      skill_id: "platform-default",
      skill_version: "1",
      source_skill_run_id: null,
      status: "active",
      active_creative_direction_snapshot_id: "direction-1",
      created_at: "2026-08-04T09:00:00Z",
      updated_at: "2026-08-04T09:01:00Z",
    });

    expect(turn.turn_kind).toBe("message");
    expect(turn.guidance_session_revision).toBe(3);
    expect(capabilities[0]?.capability_revision).toBe(8);
    expect(skillRun.active_creative_direction_snapshot_id).toBe("direction-1");
  });

  it("accepts optional and nullable guidance session ids in project creation responses", () => {
    const response = {
      ...validWorkflowPayload(),
      active_style_skill_run_id: "style-skill-run-1",
    };

    expect(normalizeAgentCanvasProjectCreateResponseV2(response).guidance_session_id).toBeNull();
    expect(normalizeAgentCanvasProjectCreateResponseV2({
      ...response,
      guidance_session_id: null,
    }).guidance_session_id).toBeNull();
    expect(normalizeAgentCanvasProjectCreateResponseV2({
      ...response,
      guidance_session_id: "",
    }).guidance_session_id).toBe("");
  });

  it("accepts the v2 role contract returned for newly created nodes", () => {
    const workflow = normalizeAgentCanvasWorkflowV2({
      ...validWorkflowPayload(),
      nodes: validWorkflowPayload().nodes.map((node) => ({
        ...node,
        role_contract_version: "ad-media-role-v2",
      })),
    });

    expect(workflow.nodes.map((node) => node.role_contract_version)).toEqual([
      "ad-media-role-v2",
      "ad-media-role-v2",
    ]);
  });

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
      source_asset_version_id: null,
    });
  });

  it("rejects more current session actions than the bounded backend contract allows", () => {
    expect(() => normalizeAgentCanvasChatTimelineResponseV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      current_session_actions: ["one", "two", "three"].map((suffix, index) => ({
        action_id: `action-${suffix}`,
        logical_key: `logical-${suffix}`,
        action: index === 2 ? "resume_guidance" : "stop_guidance",
        state: "pending",
        creating_turn_id: `turn-${suffix}`,
        expected_session_revision: index + 1,
        label: suffix,
        workflow_id: "workflow-1",
        confirmation_required: false,
        reason: `Reason ${suffix}`,
      })),
      items: [],
      next_cursor: 0,
    })).toThrowError(/current_session_actions.*at most 2/i);
  });

  it("hydrates omitted empty timeline collections from backend defaults", () => {
    const timeline = normalizeAgentCanvasChatTimelineResponseV2({
      workflow_id: "workflow-empty",
      conversation_id: null,
      next_cursor: 0,
    });

    expect(timeline.items).toEqual([]);
    expect(timeline.continuations).toEqual([]);
    expect(timeline.current_session_actions).toEqual([]);
  });

  it("normalizes a complete canonical workflow payload", () => {
    const workflow = normalizeAgentCanvasWorkflowV2({
      ...validWorkflowPayload(),
      active_style_skill: {
        skill_run_id: "style-run-1",
        skill_id: "platform-default",
        skill_version: "1.0.0",
        title: "Platform Default",
        summary: "Balanced commercial video direction.",
        category: "commercial-craft",
        creative_direction_snapshot_id: "direction-1",
      },
    });

    expect(workflow.canvas_model).toBe("agent_canvas_v1");
    expect(workflow.revision).toBe(7);
    expect(workflow.layout_revision).toBe(3);
    expect(workflow.nodes).toHaveLength(2);
    expect(workflow.nodes[0]?.execution_mode).toBe("source_only");
    expect(workflow.nodes[1]?.execution_mode).toBe("generative");
    expect(workflow.bindings[1]?.source.kind).toBe("image_asset");
    expect(workflow.assets[0]?.checksum).toBe("sha256-output-1");
    expect(workflow.active_style_skill).toMatchObject({
      skill_run_id: "style-run-1",
      title: "Platform Default",
    });
  });


  it("normalizes the public video Style catalog without exposing private Skill content", () => {
    const catalog = normalizeVideoSkillCatalogResponseV2({
      catalog_version: "1",
      categories: [{
        category_id: "commercial-craft",
        title: "Commercial Craft",
        display_order: 10,
      }],
      items: [{
        skill_id: "platform-default",
        version: "1.0.0",
        title: "Platform Default",
        summary: "Balanced commercial video direction.",
        category: "commercial-craft",
        tags: ["commercial", "balanced"],
        supported_use_cases: ["general advertising"],
        preview: { kind: "none", summary: null, media_url: null },
        display_order: 10,
      }],
      next_cursor: "Mg",
    });

    expect(catalog.categories[0]).toEqual({
      category_id: "commercial-craft",
      title: "Commercial Craft",
      display_order: 10,
    });
    expect(catalog.items[0]).toMatchObject({
      skill_id: "platform-default",
      preview: { kind: "none" },
    });
    expect(catalog.next_cursor).toBe("Mg");
    expect(() => normalizeVideoSkillPublicDetailV2({
      ...catalog.items[0],
      skill_body: "private prompt content",
    })).toThrowError(/unknown field/i);
  });

  it("normalizes public Style metadata returned with an activated Skill Run", () => {
    const publicSkill = {
      skill_id: "cinematic-poetic-realism",
      version: "1.0.0",
      title: "Cinematic Poetic Realism",
      summary: "A restrained cinematic treatment.",
      category: "cinematic-narrative",
      tags: ["cinematic"],
      supported_use_cases: ["brand film"],
      preview: {
        kind: "image",
        summary: "Public visual preview.",
        media_url: "/assets/previews/style.jpg",
      },
      display_order: 20,
    };
    const skillRun = normalizeAgentCanvasVideoSkillRunV2({
      skill_run_id: "style-run-2",
      workflow_id: "workflow-1",
      skill_id: publicSkill.skill_id,
      skill_version: publicSkill.version,
      source_skill_run_id: "style-run-1",
      status: "active",
      active_creative_direction_snapshot_id: "direction-2",
      public_skill: publicSkill,
      created_at: "2026-08-05T01:00:00Z",
      updated_at: "2026-08-05T01:00:01Z",
    });

    expect(skillRun.public_skill).toMatchObject({
      skill_id: "cinematic-poetic-realism",
      preview: { kind: "image" },
    });
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

  it("normalizes a post-ready checkpoint without accepting unknown fields", () => {
    const checkpoint = normalizeCanvasPostReadyCheckpointV2({
      checkpoint_id: "checkpoint-1",
      workflow_id: "workflow-1",
      execution_id: "execution-1",
      execution_status: "waiting",
      status: "pending",
      counts: {
        total: 2,
        queued: 1,
        running: 1,
        completed: 0,
        failed: 0,
      },
      effects: [{
        effect_id: "effect-1",
        effect_type: "advance_storyboard_progression",
        node_id: "node-script-1",
        status: "running",
        attempt_no: 1,
        error: null,
        updated_at: "2026-08-17T10:00:00Z",
      }],
      error: null,
      updated_at: "2026-08-17T10:00:00Z",
    });

    expect(checkpoint).toMatchObject({
      checkpoint_id: "checkpoint-1",
      status: "pending",
      execution_status: "waiting",
      counts: { total: 2, running: 1 },
      effects: [{ effect_type: "advance_storyboard_progression", status: "running" }],
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
          parameter_compilation_snapshot_id: "parameter-compilation-1",
          input_manifest_id: "manifest-1",
          effective_parameters: {
            duration_seconds: 15,
            generate_audio: false,
          },
          normalizations: [
            "duration_clamped_to_provider_limit",
            {
              field: "duration_seconds",
              requested_value: 20,
              effective_value: 15,
              normalization_code: "duration_clamped_to_maximum",
            },
          ],
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
      parameter_compilation_snapshot_id: "parameter-compilation-1",
      effective_parameters: {
        duration_seconds: 15,
        generate_audio: false,
      },
      normalizations: [
        "duration_clamped_to_provider_limit",
        {
          field: "duration_seconds",
          requested_value: 20,
          effective_value: 15,
          normalization_code: "duration_clamped_to_maximum",
        },
      ],
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
      guidance_session: null,
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
          proposal_id: null,
          proposal_option_id: null,
          proposal_action: null,
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
          superseded_by: null,
          error_code: "guided_action_no_effect",
          error_message: "No new sibling draft was created.",
          created_at: "2026-07-31T04:01:00Z",
        },
        created_at: "2026-07-31T04:01:00Z",
      }],
      next_cursor: 2,
    });

    expect(accepted).toMatchObject({ turn_id: "turn-1", status: "queued" });
    expect(turn.continuation).toMatchObject({ delivery_status: "leased", attempt_count: 3 });
    expect(timeline.items[0]).toMatchObject({
      item_type: "action_receipt",
      action_receipt: {
        status: "not_applied",
        continuation_turn_id: null,
        error_code: "guided_action_no_effect",
      },
    });
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
      guidance_session_revision: null,
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
      created_node_ids: ["node-sibling-1", "node-turnaround-1"],
      created_binding_ids: ["binding-copy-1", "binding-pair-1"],
      placement_hints: [{
        intent: "right_sibling",
        anchor_node_id: "node-image-1",
        group_key: "pair-1",
      }, {
        intent: "right_sibling",
        anchor_node_id: "node-sibling-1",
        group_key: "pair-1",
      }],
    });

    expect(workflow.nodes[1]?.variation_draft?.variation_revision).toBe(2);
    expect(timeline.items.map((item) => item.item_type)).toEqual([
      "command_plan",
      "action_receipt",
    ]);
    expect(layout.layout_revision).toBe(4);
    expect(materialized.sibling_node.node_id).toBe("node-sibling-1");
    expect(materialized.run?.execution_id).toBe("execution-1");
    expect(materialized.created_node_ids).toEqual(["node-sibling-1", "node-turnaround-1"]);
    expect(materialized.created_binding_ids).toEqual(["binding-copy-1", "binding-pair-1"]);
    expect(materialized.placement_hints).toHaveLength(2);
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
            capability_id: "character_design",
            capability_display_name: "Character Designer",
            options: [
              {
                option_id: "option-1",
                title: "Option A",
                public_summary: "Athletic streetwear lead.",
                key_decisions: ["Use a confident athletic silhouette."],
              },
            ],
            proposed_references: [],
            target_node_id: null,
            target_node_revision: null,
            proposal_purpose: null,
            availability: "open",
            application_count: 0,
            latest_application: null,
            guidance_session_id: "guidance-1",
            guidance_session_revision: 2,
            actions: [{
              action_id: "proposal-1:1:select_option",
              action: "select_option",
              label: "Use this direction",
              proposal_id: "proposal-1",
              expected_session_revision: 2,
              confirmation_required: false,
              reason: "Create one editable Draft.",
            }],
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
            timeline_start_seconds: 5,
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
        timeline_duration_seconds: 30,
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
    expect(editing.manifest.video_entries[0]?.timeline_start_seconds).toBe(5);
    expect(editing.manifest.timeline_duration_seconds).toBe(30);
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

  it("normalizes the persisted prompt preparation projection without changing the visible Draft status", () => {
    const normalized = normalizeCanvasNodeV2({
      ...validWorkflowPayload().nodes[1],
      generation_prompt: null,
      error: null,
      prompt_preparation: {
        status: "working",
        operation_id: "prompt-operation-1",
        presentation_stream_id: "presentation-stream-1",
        attempt_no: 1,
        context_snapshot_id: "snapshot-1",
        occurrence_id: null,
        character_phase: null,
        prompt_digest: null,
        error: null,
        updated_at: "2026-08-11T10:00:00Z",
      },
    });

    expect(normalized.status).toBe("draft");
    expect(normalized.prompt_preparation).toMatchObject({
      status: "working",
      operation_id: "prompt-operation-1",
      presentation_stream_id: "presentation-stream-1",
      attempt_no: 1,
      context_snapshot_id: "snapshot-1",
      occurrence_id: null,
      character_phase: null,
      prompt_digest: null,
      error: null,
      updated_at: "2026-08-11T10:00:00Z",
    });
  });

  it("accepts the explicit not-applicable prompt preparation state", () => {
    const normalized = normalizeCanvasNodeV2({
      ...validWorkflowPayload().nodes[1],
      execution_mode: "source_only",
      generation_prompt: null,
      error: null,
      prompt_preparation: {
        status: "not_applicable",
        operation_id: null,
        presentation_stream_id: null,
        attempt_no: 0,
        context_snapshot_id: null,
        occurrence_id: null,
        character_phase: null,
        prompt_digest: null,
        role_variant: null,
        recipe_id: null,
        recipe_version: null,
        recipe_digest: null,
        requirement_revision_id: null,
        requirement_revision_no: null,
        document_revisions: {},
        binding_digest: null,
        style_projection_digest: null,
        brief_digest: null,
        parameter_origins: [],
        assertion_evidence: null,
        attempt_stage: null,
        error: null,
        updated_at: "2026-08-11T10:00:00Z",
      },
    });

    expect(normalized.prompt_preparation).toMatchObject({
      status: "not_applicable",
      presentation_stream_id: null,
    });
  });

  it("accepts a superseded chat turn as terminal and non-retryable", () => {
    const normalized = normalizeAgentCanvasChatTurnV2({
      turn_id: "turn-superseded-1",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: "superseded",
      turn_kind: "message",
      request: {},
      error_code: null,
      error_message: null,
      retryable: false,
      created_at: "2026-08-11T10:00:00Z",
      updated_at: "2026-08-11T10:00:01Z",
    });

    expect(normalized.status).toBe("superseded");
    expect(() => normalizeAgentCanvasChatTurnV2({
      turn_id: "turn-superseded-2",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: "superseded",
      turn_kind: "message",
      request: {},
      error_code: null,
      error_message: null,
      retryable: true,
      created_at: "2026-08-11T10:00:00Z",
      updated_at: "2026-08-11T10:00:01Z",
    })).toThrowError(/superseded.*retryable/i);
  });

  it("accepts role-specific prompt preparation and V3 authoritative document projections", () => {
    const node = normalizeCanvasNodeV2({
      ...validWorkflowPayload().nodes[1],
      prompt_preparation: {
        status: "superseded",
        attempt_no: 2,
        role_variant: "character_turnaround",
        recipe_id: "recipe-character",
        recipe_version: "1",
        recipe_digest: "sha256:" + "a".repeat(64),
        requirement_revision_id: "requirement-2",
        requirement_revision_no: 2,
        document_revisions: { "doc-plan": 3 },
        binding_digest: "sha256:" + "b".repeat(64),
        style_projection_digest: null,
        brief_digest: null,
        parameter_origins: [{
          name: "duration_seconds",
          value: 15,
          source_kind: "storyboard_plan",
          source_id: "doc-plan",
          source_revision: 3,
        }],
        assertion_evidence: {
          schema_version: "1",
          policy_ref: "adcraft.prompt-policy",
          policy_version: "1",
          policy_digest: "sha256:" + "c".repeat(64),
          recipe_id: "recipe-character",
          recipe_version: "1",
          assertion_ids: ["preserve-character-identity"],
          assertion_block_digest: "sha256:" + "d".repeat(64),
          prepared_prompt_digest: "e".repeat(64),
          source_snapshots: [{
            schema_version: "1",
            source_kind: "document",
            document_id: "doc-plan",
            document_revision: 3,
          }],
          document_revisions: { "doc-plan": 3 },
          sequence_id: null,
          engine_owned_fields_digest: "sha256:" + "f".repeat(64),
          evidence_digest: "sha256:" + "1".repeat(64),
        },
        attempt_stage: "context_ready",
        error: null,
        updated_at: "2026-08-15T10:00:00Z",
      },
    });
    expect(node.prompt_preparation.status).toBe("superseded");
    expect(node.prompt_preparation.parameter_origins[0]?.source_kind).toBe("storyboard_plan");
    expect(node.prompt_preparation.assertion_evidence?.source_snapshots[0]).toMatchObject({
      source_kind: "document",
      document_id: "doc-plan",
      document_revision: 3,
    });

    const document = normalizeAgentWorkingDocumentV2({
      document_id: "doc-v3", workflow_id: "workflow-1", guidance_session_id: "session-1",
      kind: "anchor_registry", title: "Anchors", revision: 3, content_schema_version: 3,
      content_digest: "sha256:document", created_by_agent_run_id: "run-1", updated_by_agent_run_id: "run-1",
      linked_nodes: [], created_at: "2026-08-15T10:00:00Z", updated_at: "2026-08-15T10:00:00Z",
      content: { schema_version: "3", anchors: [{
        alias: "HERO", identity_id: "identity-1", semantic_role: "character", display_name: "Hero",
        summary: "Lead talent", lifecycle: "active",
        source: {
          source_kind: "image_asset_version",
          workflow_id: "workflow-1",
          node_id: "node-character-main",
          node_revision: 2,
          asset_id: "asset-character-main",
          asset_version_id: "asset-version-character-main",
        },
        role_sources: [{
          role: "character_main",
          source: {
            source_kind: "node",
            workflow_id: "workflow-1",
            node_id: "node-character-main",
            node_revision: 2,
          },
        }, {
          role: "character_turnaround",
          source: {
            source_kind: "node",
            workflow_id: "workflow-1",
            node_id: "node-character-turnaround",
            node_revision: 1,
          },
        }],
        acceptance_evidence: [{ evidence_id: "evidence-1", actor: "user", decision: "accepted", action_id: "action-1", requirement_revision_id: "requirement-2", requirement_revision_no: 2, node_revision: 2, asset_version_id: null, document_revision: 3, recorded_at: "2026-08-15T10:00:00Z" }],
      }] },
    });
    expect(document.content_schema_version).toBe(3);
    expect(document.content).toMatchObject({
      schema_version: "3",
      anchors: [{
        role_sources: [{
          role: "character_main",
          source: { node_id: "node-character-main", node_revision: 2 },
        }, {
          role: "character_turnaround",
          source: { node_id: "node-character-turnaround", node_revision: 1 },
        }],
      }],
    });
  });

  it.each(["schema_version", "source_snapshots", "document_revisions"])(
    "rejects prompt assertion evidence without required %s",
    (missingField) => {
      const assertionEvidence: Record<string, unknown> = {
        schema_version: "1",
        policy_ref: "adcraft.prompt-policy",
        policy_version: "1",
        policy_digest: "sha256:" + "a".repeat(64),
        recipe_id: "recipe-character",
        recipe_version: "1",
        assertion_ids: ["preserve-character-identity"],
        assertion_block_digest: "sha256:" + "b".repeat(64),
        prepared_prompt_digest: "c".repeat(64),
        source_snapshots: [],
        document_revisions: {},
        sequence_id: null,
        engine_owned_fields_digest: "sha256:" + "d".repeat(64),
        evidence_digest: "sha256:" + "e".repeat(64),
      };
      delete assertionEvidence[missingField];

      expect(() => normalizeCanvasNodeV2({
        ...validWorkflowPayload().nodes[1],
        prompt_preparation: {
          status: "ready",
          attempt_no: 1,
          prompt_digest: "f".repeat(64),
          assertion_evidence: assertionEvidence,
          error: null,
          updated_at: "2026-08-15T10:00:00Z",
        },
      })).toThrowError(new RegExp(`assertion_evidence\\.${missingField}`));
    },
  );

  it("rejects malformed prompt preparation errors instead of accepting untyped backend payloads", () => {
    expect(() => normalizeCanvasNodeV2({
      ...validWorkflowPayload().nodes[1],
      prompt_preparation: {
        status: "failed",
        operation_id: "prompt-operation-1",
        attempt_no: 1,
        context_snapshot_id: "snapshot-1",
        prompt_digest: null,
        error: null,
        updated_at: "2026-08-11T10:00:00Z",
      },
    })).toThrowError(/prompt_preparation.error/i);
  });

  it("accepts parameter provenance returned by current canvas workflow reads", () => {
    const normalized = normalizeCanvasNodeV2({
      ...validWorkflowPayload().nodes[1],
      parameters: { duration_seconds: 10 },
      parameter_provenance: {
        duration_seconds: {
          origin: "binding",
          source_node_id: "node-text-1",
          binding_id: "binding-1",
          source_revision: 3,
          requested_value: 18,
          effective_value: 15,
          normalization_code: "duration_clamped_to_maximum",
        },
      },
    });

    expect(normalized.parameter_provenance.duration_seconds).toEqual({
      origin: "binding",
      source_node_id: "node-text-1",
      binding_id: "binding-1",
      source_revision: 3,
      requested_value: 18,
      effective_value: 15,
      normalization_code: "duration_clamped_to_maximum",
    });
    expect(normalizeCanvasNodeV2({
      ...validWorkflowPayload().nodes[0],
      parameter_provenance: {
        duration_seconds: {
          origin: "manual",
          requested_value: 10,
          effective_value: 10,
        },
      },
    }).parameter_provenance.duration_seconds).toEqual({
      origin: "manual",
      source_node_id: null,
      binding_id: null,
      source_revision: null,
      requested_value: 10,
      effective_value: 10,
      normalization_code: null,
    });
  });

  it("accepts every parameter provenance origin in the backend contract", () => {
    const origins = [
      "manual",
      "node_prompt",
      "binding",
      "user_explicit",
      "structured_content",
      "guidance_default",
      "role_default",
      "provider_clamp",
    ] as const;
    const parameterProvenance = Object.fromEntries(origins.map((origin, index) => [
      `field_${index}`,
      {
        origin,
        ...(origin === "binding" ? {
          source_node_id: "node-text-1",
          binding_id: "binding-1",
          source_revision: 3,
        } : {}),
        requested_value: 18,
        effective_value: 15,
      },
    ]));

    const normalized = normalizeCanvasNodeV2({
      ...validWorkflowPayload().nodes[1],
      parameter_provenance: parameterProvenance,
    });

    expect(Object.values(normalized.parameter_provenance).map(({ origin }) => origin)).toEqual(origins);
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
        default_parameters: {
          duration_seconds: 5,
        },
        supported_resolutions: ["720p", "1080p"],
        supported_aspect_ratios: ["16:9"],
        duration_range_seconds: [3, 12],
        pixel_bounds: null,
        available: true,
        unavailable_reason: null,
        supports_native_audio: true,
      }],
    });

    expect(capabilities[0]?.supports_native_audio).toBe(true);
    expect(capabilities[0]?.default_parameters).toEqual({ duration_seconds: 5 });
    expect(capabilities[0]?.supported_resolutions).toEqual(["720p", "1080p"]);
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
    expect(timeline.presentation_items).toBeNull();
  });

  it("accepts the additive user presentation projection without changing raw timeline pagination", () => {
    const payload = {
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      items: [{
        entry_id: "entry-1",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        sequence_no: 7,
        entry_type: "planning_progress",
        speaker: null,
        content: "Planning the next creative action.",
        metadata: {},
        command_plan: null,
        action_receipt: null,
        created_at: "2026-08-13T10:10:00Z",
      }],
      presentation_items: [{
        entry_id: "entry-1",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        sequence_no: 7,
        entry_type: "planning_progress",
        speaker: null,
        content: "Planning the next creative action.",
        metadata: {},
        command_plan: null,
        action_receipt: null,
        created_at: "2026-08-13T10:10:00Z",
        presentation_key: "planning:next-action-1",
        presentation_revision: 2,
        source_entry_ids: ["entry-0", "entry-1"],
        message_key: "planning_progress.next_action",
        message_args: {},
        response_locale: "zh-CN",
      }],
      next_cursor: 7,
    };

    const raw = normalizeAgentCanvasChatTimelineResponseV2(payload);
    const timeline = normalizeAgentCanvasChatTimelineV2(payload);

    expect(raw.next_cursor).toBe(7);
    expect(raw.presentation_items?.[0]).toMatchObject({
      presentation_key: "planning:next-action-1",
      presentation_revision: 2,
      source_entry_ids: ["entry-0", "entry-1"],
      response_locale: "zh-CN",
    });
    expect(timeline.presentationItems?.[0]).toMatchObject({
      presentation_key: "planning:next-action-1",
      presentation_revision: 2,
      item: {
        item_type: "message",
        text: "Planning the next creative action.",
        sequence: 7,
      },
    });
  });

  it("preserves planning progress provenance and typed thread relations", () => {
    const timeline = normalizeAgentCanvasChatTimelineV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      items: [{
        entry_id: "entry-planning-1",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        sequence_no: 8,
        entry_type: "planning_progress",
        speaker: null,
        content: "Preparing the selected direction.",
        metadata: {
          capability_id: "world_setting",
          proposal_id: "proposal-world-1",
        },
        command_plan: null,
        action_receipt: null,
        created_at: "2026-08-13T10:10:01Z",
      }],
      next_cursor: 8,
    });

    expect(timeline.items[0]).toMatchObject({
      item_type: "message",
      message_kind: "planning_progress",
      capability_id: "world_setting",
      proposal_id: "proposal-world-1",
    });
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

  it("accepts canonical asset version and generation metadata from workflow reads", () => {
    const asset = normalizeProjectAssetSummaryV2({
      ...validWorkflowPayload().assets[0],
      version_id: "version-asset-output-1",
      actual_media_facts: {
        width: 1024,
        height: 1024,
        mime_type: "image/png",
      },
      generation_provenance: {
        input_manifest_id: "manifest-1",
        node_revision: 5,
      },
    });

    expect(asset.version_id).toBe("version-asset-output-1");
    expect(asset.actual_media_facts).toEqual({
      width: 1024,
      height: 1024,
      mime_type: "image/png",
    });
    expect(asset.generation_provenance).toEqual({
      input_manifest_id: "manifest-1",
      node_revision: 5,
    });
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
      run_intent_snapshot_ids: {
        "node-image-1": "run-intent-snapshot-1",
      },
      events_cursor: 18,
    })).toMatchObject({
      status: "partial_completed",
      run_intent_snapshot_ids: {
        "node-image-1": "run-intent-snapshot-1",
      },
    });

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
      active_creative_direction_snapshot_id: "direction-3",
      created_at: "2026-07-30T08:00:00Z",
      updated_at: "2026-07-30T08:01:00Z",
    })).toMatchObject({
      status: "active",
      active_creative_direction_snapshot_id: "direction-3",
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
      active_creative_direction_snapshot_id: null,
      updated_at: null,
    });
  });

  it("normalizes Agent execution settings without accepting unrelated fields", () => {
    expect(normalizeAgentExecutionSettingsV2({
      workflow_id: "workflow-1",
      media_execution_mode: "automatic",
      revision: 3,
      created_at: "2026-08-06T08:00:00Z",
      updated_at: "2026-08-06T08:01:00Z",
    })).toMatchObject({
      media_execution_mode: "automatic",
      revision: 3,
    });

    expect(() => normalizeAgentExecutionSettingsV2({
      workflow_id: "workflow-1",
      media_execution_mode: "automatic",
      revision: 3,
      created_at: "2026-08-06T08:00:00Z",
      updated_at: "2026-08-06T08:01:00Z",
      guidance_mode: "delegated",
    })).toThrowError(/guidance_mode/i);
  });

  it("normalizes read-only Anchor Registry and Storyboard Production Plan documents", () => {
    const base = {
      workflow_id: "workflow-1",
      guidance_session_id: "session-1",
      revision: 2,
      content_digest: "sha256:document",
      created_by_agent_run_id: "run-1",
      updated_by_agent_run_id: "run-2",
      linked_nodes: [{
        node_id: "node-grid-1",
        node_type: "image",
        creative_role: "storyboard_sequence",
        status: "ready",
        revision: 4,
      }],
      created_at: "2026-08-06T08:00:00Z",
      updated_at: "2026-08-06T08:02:00Z",
    };
    const anchorRegistry = normalizeAgentWorkingDocumentV2({
      ...base,
      document_id: "doc-anchor-1",
      kind: "anchor_registry",
      title: "Campaign anchors",
      content: {
        anchors: [{
          alias: "HERO",
          anchor_type: "subject",
          display_name: "Lead talent",
          summary: "Primary on-screen subject.",
          source_kind: "node",
          source_id: "node-character-1",
          availability: "available",
        }],
      },
    });
    const storyboardPlan = normalizeAgentWorkingDocumentV2({
      ...base,
      document_id: "doc-plan-1",
      kind: "storyboard_production_plan",
      title: "Storyboard plan",
      content: {
        narrative_outline: "A calm product reveal.",
        global_parameters: {
          aspect_ratio: "16:9",
          total_duration_seconds: 15,
          segment_count: 1,
        },
        segments: [{
          sequence_id: "sequence-1",
          order: 1,
          start_seconds: 0,
          end_seconds: 15,
          narrative_goal: "Reveal the product.",
          start_state: "Closed frame.",
          end_state: "Product hero frame.",
          continuity_from_previous: null,
          terminal_policy: "close",
        }],
        rows: [{
          shot_index: 1,
          sequence_id: "sequence-1",
          panel_index: 1,
          content_beat: "Product enters frame.",
          anchor_aliases: ["HERO"],
          camera_description: "Slow push in.",
        }],
        node_records: [{
          sequence_id: "sequence-1",
          node_role: "storyboard_grid",
          node_id: "node-grid-1",
        }],
        materialized_panel_cursor: 1,
        segment_materializations: [{
          sequence_id: "sequence-1",
          status: "materialized",
          generation_prompt: "Generate a warm product reveal with a slow push in.",
        }],
        visual_anchor: {
          node_id: "node-grid-1",
          asset_id: "asset-grid-1",
          node_revision: 4,
          document_revision: 2,
        },
      },
    });

    expect(anchorRegistry.content).toMatchObject({ anchors: [{ alias: "HERO" }] });
    expect(storyboardPlan.content).toMatchObject({
      global_parameters: { aspect_ratio: "16:9", segment_count: 1 },
      segments: [{ terminal_policy: "close" }],
      materialized_panel_cursor: 1,
      segment_materializations: [{
        sequence_id: "sequence-1",
        status: "materialized",
      }],
      visual_anchor: {
        asset_id: "asset-grid-1",
        document_revision: 2,
      },
    });
    expect(normalizeAgentWorkingDocumentPageV2({
      items: [anchorRegistry, storyboardPlan],
      next_cursor: "cursor-2",
    })).toMatchObject({ next_cursor: "cursor-2" });
  });

  it("accepts guidance advance command turns returned by the canonical backend", () => {
    const turn = normalizeAgentCanvasChatTurnV2({
      turn_id: "turn-guidance-command-1",
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      status: "completed",
      turn_kind: "guidance_advance",
      request: { source_id: "stage:foundation_design:4" },
      error_code: null,
      error_message: null,
      creation_mode: null,
      guidance_session_revision: 8,
      continuation: null,
      retry_of_turn_id: null,
      retry_attempt_no: 1,
      retryable: false,
      operation_stage: null,
      operation_failure: null,
      created_at: "2026-08-17T10:00:00Z",
      updated_at: "2026-08-17T10:00:01Z",
    });

    expect(turn.turn_kind).toBe("guidance_advance");
  });

  it("restores Agent Document references from the persisted chat timeline", () => {
    const timeline = normalizeAgentCanvasChatTimelineV2({
      workflow_id: "workflow-1",
      conversation_id: "conversation-1",
      guidance_session: null,
      continuations: [],
      current_session_actions: [],
      items: [{
        entry_id: "entry-document-1",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        sequence_no: 1,
        entry_type: "agent_document_reference",
        speaker: null,
        content: "Storyboard plan",
        metadata: {
          type: "agent_document_reference",
          document_id: "doc-plan-1",
          document_kind: "storyboard_production_plan",
          revision: 4,
          content_digest: "sha256:plan",
          title: "Storyboard plan",
        },
        command_plan: null,
        action_receipt: null,
        created_at: "2026-08-06T08:00:00Z",
      }],
      next_cursor: 1,
    });

    expect(timeline.items).toEqual([expect.objectContaining({
      item_type: "agent_document",
      document_id: "doc-plan-1",
      document_kind: "storyboard_production_plan",
      revision: 4,
    })]);
  });
});

describe("normalizeCanvasEditingExportImportResponseV2", () => {
  it("accepts the authoritative source-only node import response", () => {
    const workflow = validWorkflowPayload();
    const node = {
      ...workflow.nodes[1],
      node_id: "video-export",
      node_type: "video",
      creative_role: "general_video",
      status: "ready",
      execution_mode: "source_only",
      generation_prompt: null,
      output_asset_id: "asset-export",
    };
    const asset = {
      ...workflow.assets[0],
      asset_id: "asset-export",
      media_type: "video",
      mime_type: "video/mp4",
      display_name: "Final cut source",
      width: 1920,
      height: 1080,
      preview_url: "/api/v2/assets/asset-export/content",
      media_url: "/api/v2/assets/asset-export/content",
    };
    const binding = {
      ...workflow.bindings[0],
      binding_id: "binding-editing-export",
      source: { kind: "node_output", source_node_id: "editing-1" },
      target_node_id: "video-export",
      input_role: "video_reference",
    };

    const normalized = normalizeCanvasEditingExportImportResponseV2({
      workflow_id: "workflow-1",
      revision: 9,
      layout_revision: 4,
      node,
      binding,
      asset,
      events_cursor: 41,
      replayed: true,
    });

    expect(normalized).toMatchObject({
      revision: 9,
      layout_revision: 4,
      events_cursor: 41,
      replayed: true,
      node: {
        node_id: "video-export",
        execution_mode: "source_only",
        output_asset_id: "asset-export",
      },
      binding: { binding_id: "binding-editing-export" },
      asset: { asset_id: "asset-export", media_type: "video" },
    });
  });
});
