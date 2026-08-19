import { afterEach, describe, expect, it, vi } from "vitest";

import { v2Api } from "./v2Client.ts";

function jsonResponse(value: unknown) {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
}

function creativeSession() {
  return {
    session_id: "session-1",
    workflow_id: "workflow-1",
    status: "active",
    goal: {
      requested_output: "video",
      delivery_scope: "generated_media",
      summary: "Create a launch film.",
      explicit_constraints: {},
    },
    creative_authority: null,
    current_checkpoint: null,
    narrative_direction: null,
    element_decisions: [],
    current_topic_id: null,
    topics: [],
    active_proposal_id: null,
    active_style_skill_run_id: null,
    completion: {
      authoring: "not_ready",
      delivery: "not_ready",
      editing_preparation: "not_ready",
      editing_node_id: null,
      matching_node_ids: [],
      matching_asset_ids: [],
    },
    journey: {
      policy_version: "fixed_ad_production_v1",
      stage: "foundation_design",
      stage_status: "waiting_user",
      stage_revision: 4,
      foundation_queue: [{
        item_id: "scene-1",
        kind: "scene",
        occurrence_index: 1,
        requirement_source: "explicit_user",
        required: true,
        status: "active",
        topic_id: "topic-scene",
        selected_node_ids: [],
      }],
      foundation_cursor: 0,
      active_action: {
        action_id: "journey-action-1",
        action_kind: "wait_for_user",
        stage: "foundation_design",
        status: "waiting_user",
        turn_id: "turn-1",
        foundation_item_id: "scene-1",
      },
      suspended_action: null,
      transition_evidence: [],
    },
    revision: 8,
    updated_at: "2026-08-10T00:00:00Z",
  };
}

function decisionBundle() {
  return {
    bundle_id: "bundle-1",
    workflow_id: "workflow-1",
    conversation_id: "conversation-1",
    source_turn_id: "turn-1",
    replacement_bundle_id: null,
    status: "open",
    revision: 4,
    title: "Creative decisions",
    introduction: "Choose a direction.",
    questions: [{
      question_id: "question-1",
      prompt: "Choose the mood",
      selection_mode: "single",
      allow_custom_answer: true,
      allow_skip: true,
      options: [{
        option_id: "mood-calm",
        label: "Calm",
        description: "Quiet and precise.",
        effects: [],
      }, {
        option_id: "mood-bold",
        label: "Bold",
        description: "High energy.",
        effects: [],
      }],
    }],
    answers: [],
    requirement_revision_no: null,
    created_at: "2026-08-10T00:00:00Z",
    updated_at: "2026-08-10T00:00:00Z",
    closed_at: null,
  };
}

describe("Agent Canvas creative session client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("loads the persisted creative session and normalizes its journey", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toContain("/api/v2/workflows/workflow-1/creative-session");
      expect(init?.method).toBeUndefined();
      return jsonResponse(creativeSession());
    });
    vi.stubGlobal("fetch", fetchMock);

    const session = await v2Api.agentCanvasCreativeSession("workflow-1");

    expect(session.journey).toMatchObject({
      stage: "foundation_design",
      stage_status: "waiting_user",
      stage_revision: 4,
      foundation_cursor: 0,
      active_action: { action_id: "journey-action-1" },
    });
  });

  it("loads and answers a decision bundle with stable IDs and an idempotency key", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/decision-bundles/bundle-1")) {
        expect(init?.method).toBeUndefined();
        return jsonResponse(decisionBundle());
      }
      expect(url).toContain("/decision-bundles/bundle-1/answers");
      expect(init?.method).toBe("POST");
      expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("bundle-key");
      expect(JSON.parse(String(init?.body))).toEqual({
        action: "submit",
        expected_revision: 4,
        answers: [{
          question_id: "question-1",
          selected_option_ids: ["mood-calm"],
          custom_answer: null,
          skipped: false,
        }],
      });
      return jsonResponse({
        workflow_id: "workflow-1",
        bundle_id: "bundle-1",
        status: "answered",
        revision: 5,
        requirement_revision_no: 3,
        turn_id: "turn-2",
        events_cursor: 9,
        replayed: false,
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const bundle = await v2Api.agentCanvasDecisionBundle("workflow-1", "bundle-1");
    const accepted = await v2Api.actOnAgentCanvasDecisionBundle(
      "workflow-1",
      "bundle-1",
      {
        action: "submit",
        expected_revision: 4,
        answers: [{
          question_id: "question-1",
          selected_option_ids: ["mood-calm"],
          custom_answer: null,
          skipped: false,
        }],
      },
      "bundle-key",
    );

    expect(bundle.questions[0]?.options[0]).toEqual({
      option_id: "mood-calm",
      label: "Calm",
      description: "Quiet and precise.",
    });
    expect(accepted).toMatchObject({ status: "answered", turn_id: "turn-2" });
  });
});
