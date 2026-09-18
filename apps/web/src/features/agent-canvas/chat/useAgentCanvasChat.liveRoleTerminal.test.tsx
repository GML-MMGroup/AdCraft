import { useMemo } from "react";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  AgentCapabilityIdV2, AgentCanvasChatViewTimelineV2, AgentCanvasWorkflowV2,
  ChatTimelineItemV2, ConceptProposalKindV2, ConceptProposalV2,
} from "../../../types-v2.ts";
import { buildStageThreadTimeline } from "./stageThreadProjection.ts";
import { useTimelineRoleLifecycles } from "./agent-role-animation/roleLifecycleProjection.ts";

const api = vi.hoisted(() => ({
  agentCanvasChatTimeline: vi.fn(), agentCanvasCreativeSession: vi.fn(),
  agentCanvasProposal: vi.fn(), agentCanvasDecisionBundle: vi.fn(), agentCanvasChatTurn: vi.fn(),
}));
vi.mock("../../../api/agentCanvasApi.ts", () => ({ agentCanvasApi: api, isV2ApiError: () => false }));
import { useAgentCanvasChat } from "./useAgentCanvasChat.ts";

const kinds = {
  world_setting: "world_setting", product_design: "product", prop_design: "prop",
  character_design: "character", scene_design: "scene", script_authoring: "script",
  storyboard_design: "storyboard", video_direction: "video", bgm_direction: "bgm", quick_media: "video",
} satisfies Record<AgentCapabilityIdV2, ConceptProposalKindV2>;
const roles = Object.keys(kinds) as AgentCapabilityIdV2[];
const date = "2026-09-15T00:00:00Z";
const noEvents: [] = [];

function proposal(capability: AgentCapabilityIdV2 = "prop_design"): ConceptProposalV2 {
  return {
    proposal_id: "proposal-1", workflow_id: "workflow-1", turn_id: "proposal-turn-1",
    capability_id: capability, capability_display_name: capability, proposal_kind: kinds[capability],
    video_skill_run_id: null, topic_id: null, occurrence_id: null, occurrence_index: null,
    occurrence_count: null, character_phase: null, creative_direction_snapshot_id: null,
    proposal_revision: 1, source_proposal_id: null, options: [], proposed_references: [],
    target_node_id: null, target_node_revision: null, proposal_purpose: null,
    availability: "open", application_count: 0, latest_application: null,
    guidance_session_id: "session-1", guidance_session_revision: 1, actions: [],
    created_at: date, updated_at: date,
    materialization: {
      materialization_id: "materialization-1", option_id: "option-1", turn_id: "materialization-turn-1",
      status: "working", attempt_no: 1, retryable: false, error: null, created_at: date, updated_at: date,
    },
  };
}

function timeline(capability: AgentCapabilityIdV2 = "prop_design", workflowId = "workflow-1"): AgentCanvasChatViewTimelineV2 {
  const items: ChatTimelineItemV2[] = [
    { item_type: "proposal_pointer", proposal_id: "proposal-1", sequence: 15, created_at: date },
    { item_type: "message", message_id: "planning-1", conversation_id: "conversation-1",
      speaker: "adcraft_video_agent", text: "Preparing the selected direction.", message_kind: "planning_progress",
      capability_id: capability, proposal_id: "proposal-1", sequence: 16, created_at: date,
      metadata: { materialization_id: "materialization-1", proposal_id: "proposal-1", status: "queued" } },
  ];
  return {
    workflow_id: workflowId, conversation_id: "conversation-1", items, next_cursor: 16,
    guidanceSession: null, guidanceAdvancePrecondition: null, continuations: [], current_session_actions: [],
    presentationItems: items.map((item, index) => ({
      presentation_key: `presentation-${index}`, presentation_revision: 1, source_entry_ids: [`entry-${index}`],
      message_key: null, message_args: {}, response_locale: "en-US", item,
    })),
  };
}

function useHarness({ revision = 0, workflowId = "workflow-1" } = {}) {
  const workflow = useMemo<AgentCanvasWorkflowV2>(() => ({
    workflow_id: workflowId, project_id: `project-${workflowId}`, workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1", revision: 1, layout_revision: 1, nodes: [], bindings: [], assets: [], active_style_skill: null,
  }), [workflowId]);
  const chat = useAgentCanvasChat({ workflow, chatRevision: revision, chatEvents: noEvents });
  const threads = useMemo(() => buildStageThreadTimeline(chat.state.items)
    .filter(item => item.unit_type === "stage_thread"), [chat.state.items]);
  const lifecycles = useTimelineRoleLifecycles({ workflowId, threads, turnsById: chat.state.turnsById });
  return { ...chat, lifecycles };
}

async function flushRefresh() {
  await act(async () => { await vi.advanceTimersByTimeAsync(80); });
}

describe("live entity detail refresh without changing presentation identity", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    api.agentCanvasCreativeSession.mockResolvedValue(null);
    api.agentCanvasChatTimeline.mockResolvedValue(timeline());
    api.agentCanvasProposal.mockResolvedValue(proposal());
  });
  afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); vi.resetAllMocks(); });

  it.each(roles)("stops %s on completion without remounting or changing presentation revision", async capability => {
    api.agentCanvasChatTimeline.mockResolvedValue(timeline(capability));
    const initial = proposal(capability);
    api.agentCanvasProposal.mockResolvedValue(initial);
    const { result, rerender } = renderHook(useHarness, { initialProps: { revision: 0 } });
    await flushRefresh();
    expect(result.current.lifecycles.get(`stage:${capability}`)?.motionState).toBe("working");
    api.agentCanvasProposal.mockResolvedValue({ ...initial, availability: "applied",
      materialization: { ...initial.materialization!, status: "completed" } });
    rerender({ revision: 1 });
    await flushRefresh();
    expect(api.agentCanvasProposal).toHaveBeenCalledTimes(2);
    expect(result.current.lifecycles.get(`stage:${capability}`)).toMatchObject({ terminal: "completed", motionState: "idle" });
    expect(result.current.state.items[0]).toMatchObject({ item_type: "proposal", sequence: 15, created_at: date });
    // No new API call for repeated refreshes within this revision.
    await act(async () => { await result.current.actions.refresh(); });
    expect(api.agentCanvasProposal).toHaveBeenCalledTimes(2);
  });

  it.each(["failed", "superseded"] as const)("settles %s and supports a new materialization attempt", async terminal => {
    const initial = proposal();
    const { result, rerender } = renderHook(useHarness, { initialProps: { revision: 0 } });
    await flushRefresh();
    api.agentCanvasProposal.mockResolvedValue(terminal === "superseded"
      ? { ...initial, availability: "superseded" }
      : { ...initial, materialization: { ...initial.materialization!, status: "failed" } });
    rerender({ revision: 1 });
    await flushRefresh();
    expect(result.current.lifecycles.get("stage:prop_design")).toMatchObject({ terminal, motionState: "idle" });
    // A stale detail cannot revive the same operation.
    api.agentCanvasProposal.mockResolvedValue(initial);
    rerender({ revision: 2 });
    await flushRefresh();
    expect(result.current.lifecycles.get("stage:prop_design")?.motionState).toBe("idle");
    api.agentCanvasProposal.mockResolvedValue({ ...initial, proposal_revision: 2,
      materialization: { ...initial.materialization!, attempt_no: 2 } });
    rerender({ revision: 3 });
    await flushRefresh();
    expect(result.current.lifecycles.get("stage:prop_design")?.motionState).toBe("working");
  });

  it("retains visible detail while its refresh fails and retries on the next refresh", async () => {
    const initial = proposal();
    const { result, rerender } = renderHook(useHarness, { initialProps: { revision: 0 } });
    await flushRefresh();
    let reject!: (reason: Error) => void;
    api.agentCanvasProposal.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
    rerender({ revision: 1 });
    await flushRefresh();
    expect(api.agentCanvasProposal).toHaveBeenCalledTimes(2);
    expect(result.current.state.items[0]).toMatchObject({ item_type: "proposal", proposal: initial });
    await act(async () => { reject(new Error("Temporary failure")); });
    expect(result.current.state.items[0]).toMatchObject({ item_type: "proposal", proposal: initial });
    api.agentCanvasProposal.mockResolvedValue({ ...initial, materialization: { ...initial.materialization!, status: "completed" } });
    await act(async () => { await result.current.actions.refresh(); });
    expect(result.current.lifecycles.get("stage:prop_design")?.motionState).toBe("idle");
    expect(result.current.state.timelineRecovery).toBeNull();
  });

  it("refreshes entity detail without moving a card back to older wire placement", async () => {
    const current = timeline();
    current.presentationItems![0]!.presentation_revision = 2;
    const { result, rerender } = renderHook(useHarness, { initialProps: { revision: 0 } });
    api.agentCanvasChatTimeline.mockResolvedValue(current);
    await flushRefresh();
    const older = timeline();
    older.presentationItems![0]!.item = { ...older.presentationItems![0]!.item, sequence: 1 };
    api.agentCanvasChatTimeline.mockResolvedValue(older);
    api.agentCanvasProposal.mockResolvedValue({ ...proposal(), availability: "applied",
      materialization: { ...proposal().materialization!, status: "completed" } });
    rerender({ revision: 1 });
    await flushRefresh();
    expect(result.current.state.items[0]).toMatchObject({ item_type: "proposal", sequence: 15 });
    expect(result.current.lifecycles.get("stage:prop_design")?.motionState).toBe("idle");
  });

  it("deduplicates repeated proposal references while refreshing every matching presentation", async () => {
    const snapshot = timeline();
    snapshot.presentationItems!.push({ ...snapshot.presentationItems![0]!, presentation_key: "repeated-proposal" });
    api.agentCanvasChatTimeline.mockResolvedValue(snapshot);
    const { result, rerender } = renderHook(useHarness, { initialProps: { revision: 0 } });
    await flushRefresh();
    expect(api.agentCanvasProposal).toHaveBeenCalledTimes(1);
    api.agentCanvasProposal.mockResolvedValue({ ...proposal(), materialization: { ...proposal().materialization!, status: "completed" } });
    rerender({ revision: 1 });
    await flushRefresh();
    expect(api.agentCanvasProposal).toHaveBeenCalledTimes(2);
    expect(result.current.lifecycles.get("stage:prop_design")?.motionState).toBe("idle");
  });

  it("refreshes an already hydrated decision bundle at the same presentation revision", async () => {
    const snapshot = timeline();
    snapshot.presentationItems = [{ ...snapshot.presentationItems![0]!, item: {
      item_type: "decision_bundle_pointer", bundle_id: "bundle-1", sequence: 15, created_at: date,
    } }];
    snapshot.items = snapshot.presentationItems.map(x => x.item);
    api.agentCanvasChatTimeline.mockResolvedValue(snapshot);
    const bundle = { bundle_id: "bundle-1", workflow_id: "workflow-1", conversation_id: "conversation-1",
      source_turn_id: "turn-1", replacement_bundle_id: null, status: "open", revision: 1,
      title: "Creative decisions", introduction: "Choose a mood.", questions: [], answers: [],
      requirement_revision_no: null, created_at: date, updated_at: date, closed_at: null };
    api.agentCanvasDecisionBundle.mockResolvedValue(bundle);
    const { result, rerender } = renderHook(useHarness, { initialProps: { revision: 0 } });
    await flushRefresh();
    api.agentCanvasDecisionBundle.mockResolvedValue({ ...bundle, status: "skipped", revision: 2, closed_at: date });
    rerender({ revision: 1 });
    await flushRefresh();
    expect(api.agentCanvasDecisionBundle).toHaveBeenCalledTimes(2);
    expect(result.current.state.items[0]).toMatchObject({ item_type: "decision_bundle",
      sequence: 15, decision_bundle: { status: "skipped", revision: 2 } });
    await act(async () => { await result.current.actions.refresh(); });
    expect(api.agentCanvasDecisionBundle).toHaveBeenCalledTimes(2);
  });

  it.each(["newer refresh", "workflow switch"])("ignores late old detail after %s", async reason => {
    const initial = proposal();
    const { result, rerender } = renderHook(useHarness, { initialProps: { revision: 0, workflowId: "workflow-1" } });
    await flushRefresh();
    let finish!: (value: ConceptProposalV2) => void;
    api.agentCanvasProposal.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    rerender({ revision: 1, workflowId: "workflow-1" });
    await flushRefresh();
    expect(api.agentCanvasProposal).toHaveBeenCalledTimes(2);
    const workflowId = reason === "workflow switch" ? "workflow-2" : "workflow-1";
    api.agentCanvasChatTimeline.mockResolvedValue(timeline("prop_design", workflowId));
    api.agentCanvasProposal.mockResolvedValue({ ...initial, workflow_id: workflowId,
      materialization: { ...initial.materialization!, status: "completed" } });
    rerender({ revision: 2, workflowId });
    await flushRefresh();
    await act(async () => { finish(initial); });
    expect(result.current.state.items[0]).toMatchObject({ proposal: { workflow_id: workflowId, materialization: { status: "completed" } } });
    expect(result.current.lifecycles.get("stage:prop_design")?.motionState).toBe("idle");
  });
});
