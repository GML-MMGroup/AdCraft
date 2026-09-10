import { describe, expect, it } from "vitest";
import type {
  AgentCanvasChatTurnV2,
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  CanvasRuntimeSnapshotV2,
  ChatCapabilityActivityV2,
  ChatProposalCardV2,
  GuidedSessionStateV2,
  ChatMessageV2,
} from "../../../../types-v2.ts";
import type { StageThreadUnit } from "../stageThreadProjection.ts";
import { projectRoleLifecycles } from "./roleLifecycleProjection.ts";

function turn(id: string, status: AgentCanvasChatTurnV2["status"], request: Record<string, unknown> = {}): AgentCanvasChatTurnV2 {
  return { turn_id: id, workflow_id: "workflow-1", conversation_id: "conversation-1", status,
    turn_kind: "capability", request, error_code: null, error_message: null, creation_mode: null,
    guidance_session_revision: null, continuation: null, retry_of_turn_id: null, retry_attempt_no: 0,
    retryable: false, operation_stage: null, operation_failure: null,
    created_at: "2026-09-07T00:00:00Z", updated_at: "2026-09-07T00:00:00Z" };
}

function activity(id: string, turnId: string, status: ChatCapabilityActivityV2["status"], sequence = 1): ChatCapabilityActivityV2 {
  return { item_type: "expert_activity", activity_id: id, turn_id: turnId, capability_id: "character_design",
    capability_display_name: "Character Designer", status, sequence, started_at: "2026-09-07T00:00:00Z",
    finished_at: null, message: null, error_code: null, elapsed_ms: null, attempt_stage: null,
    retryable: false, validation_paths: [], suggested_actions: [], completion_mode: null, warning_code: null };
}

function proposal(occurrenceId: string, turnId: string, nodeIds: string[], sequence = 2): ChatProposalCardV2 {
  return { item_type: "proposal", sequence, created_at: "2026-09-07T00:00:00Z", proposal: {
    proposal_id: `proposal-${occurrenceId}`, workflow_id: "workflow-1", turn_id: `proposal-turn-${occurrenceId}`,
    video_skill_run_id: null, topic_id: null, occurrence_id: occurrenceId, occurrence_index: 1,
    occurrence_count: 2, character_phase: "main", creative_direction_snapshot_id: null, proposal_revision: 1,
    source_proposal_id: null, proposal_kind: "character", capability_id: "character_design",
    capability_display_name: "Character Designer", options: [], proposed_references: [], target_node_id: nodeIds[0] ?? null,
    target_node_revision: null, proposal_purpose: null, availability: "applied", application_count: 1,
    latest_application: { application_id: `application-${occurrenceId}`, option_id: "option-1", action: "select_option",
      receipt_id: `receipt-${occurrenceId}`, created_node_ids: nodeIds, queued_execution_ids: [],
      created_at: "2026-09-07T00:00:00Z" }, guidance_session_id: "session-1", guidance_session_revision: 1,
    actions: [], created_at: "2026-09-07T00:00:00Z", updated_at: "2026-09-07T00:00:00Z",
    materialization: { materialization_id: `materialization-${occurrenceId}`, option_id: "option-1", turn_id: turnId,
      status: "completed", attempt_no: 1, retryable: false, error: null,
      created_at: "2026-09-07T00:00:00Z", updated_at: "2026-09-07T00:00:00Z" } } };
}

function thread(proposals: ChatProposalCardV2[] = []): StageThreadUnit {
  return { unit_type: "stage_thread", key: "stage:character_design", capability_id: "character_design",
    capability_display_name: "Character Designer", sequence: 1, status: "working", planning: [],
    activities: [], proposals, receipts: [], selected_option: null, completed_activity_count: 0 };
}

function node(id: string, occurrenceId: string, promptStatus: NonNullable<CanvasNodeV2["prompt_preparation"]>["status"], attemptNo = 1): CanvasNodeV2 {
  return { node_id: id, workflow_id: "workflow-1", node_type: "image", creative_role: "character",
    role_contract_version: "1", title: "opaque", status: "draft", execution_mode: "generative", summary_prompt: null,
    generation_prompt: null, structured_content: {}, model_id: null, model_selection_mode: "automatic", model_ref: null,
    model_summary: null, parameters: {}, metadata: {}, parameter_provenance: {}, prompt_context_snapshot_id: null,
    output_asset_id: null, output_asset_version_id: null, latest_attempt: { execution_id: "execution-1", member_id: "member-1",
      run_intent_snapshot_id: null, status: "running", created_at: "2026-09-07T00:00:00Z",
      updated_at: "2026-09-07T00:00:00Z", error: null }, position: { x: 0, y: 0 }, revision: 1,
    error: null, prompt_presentation: null, prompt_preparation: { status: promptStatus,
      operation_id: `prompt-${id}`, presentation_stream_id: null, attempt_no: attemptNo, context_snapshot_id: null,
      occurrence_id: occurrenceId, character_phase: "main", prompt_digest: null, role_variant: "character_main",
      recipe_id: null, recipe_version: null, recipe_digest: null, requirement_revision_id: null,
      requirement_revision_no: null, document_revisions: {}, binding_digest: null,
      character_identity_projection_digest: null, scene_environment_projection_digest: null,
      style_projection_digest: null, brief_digest: null, parameter_origins: [], compaction_policy_version: null,
      compaction_policy_digest: null, compaction_decisions: [], assertion_evidence: null, attempt_stage: null,
      error: promptStatus === "failed" ? { code: "failed", message: "failed", retryable: false } : null,
      updated_at: "2026-09-07T00:00:00Z" }, created_at: "2026-09-07T00:00:00Z", updated_at: "2026-09-07T00:00:00Z" } as CanvasNodeV2;
}

function workflow(nodes: CanvasNodeV2[]): AgentCanvasWorkflowV2 {
  return { workflow_id: "workflow-1", project_id: "project-1", workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1", revision: 1, layout_revision: 1, nodes, bindings: [], assets: [], active_style_skill: null };
}

function planning(turnId: string): ChatMessageV2 {
  return { item_type: "message", message_kind: "planning_progress", message_id: `message-${turnId}`,
    conversation_id: "conversation-1", speaker: "adcraft_video_agent", text: "Planning", linked_node_ids: [],
    script_node_id: null, proposal_id: null, capability_id: "character_design", metadata: { turn_id: turnId },
    sequence: 1, created_at: "2026-09-07T00:00:00Z" };
}

function runtime(nodeId: string, phase: "queued" | "running" | "waiting_provider", attemptNo = 1): CanvasRuntimeSnapshotV2 {
  return { workflow_id: "workflow-1", active_execution_id: "execution-1", execution_status: "running",
    node_runtime: { [nodeId]: { node_id: nodeId, visible_status: "working", phase, execution_id: "execution-1",
      provider_task_id: null, run_intent_snapshot_id: null, parameter_compilation_snapshot_id: null,
      effective_parameters: {}, normalizations: [], omitted_optional_inputs: [], waiting_for_node_ids: [],
      blocked_by_node_ids: [], attempt_no: attemptNo, updated_at: "2026-09-07T00:00:00Z", error: null } },
    queued_node_ids: phase === "queued" ? [nodeId] : [], working_node_ids: phase !== "queued" ? [nodeId] : [],
    waiting_node_ids: [], ready_node_ids: [], failed_node_ids: [], events_cursor: 1,
    updated_at: "2026-09-07T00:00:00Z" };
}

function session(action: Partial<GuidedSessionStateV2["journey"]["active_action"]> | null = null): GuidedSessionStateV2 {
  return { session_id: "session-1", workflow_id: "workflow-1", status: "active", response_locale: "en-US",
    goal: {} as GuidedSessionStateV2["goal"], creative_authority: null, current_checkpoint: null,
    narrative_direction: null, element_decisions: [], current_topic_id: null, topics: [], active_proposal_id: null,
    active_style_skill_run_id: null, completion: {} as GuidedSessionStateV2["completion"], interaction: null, awaiting: null,
    revision: 1, updated_at: "2026-09-07T00:00:00Z", journey: { policy_version: "fixed_ad_production_v2",
      stage: "character", stage_status: "working", stage_revision: 1, decisions: [], active_occurrence_id: null,
      active_action: action ? { action_id: "action-1", action_kind: "invoke_capability", stage: "character",
        stage_revision: 1, status: "working", turn_id: null, occurrence_id: null, character_phase: null, ...action } : null,
      suspended_action: null, transition_evidence: [] } };
}

function project(input: Partial<Parameters<typeof projectRoleLifecycles>[0]> = {}) {
  return projectRoleLifecycles({ threads: [thread()], workflow: workflow([]), runtime: null, session: null,
    turnsById: {}, ...input }).get("stage:character_design")!;
}

describe("projectRoleLifecycles", () => {
  it("keeps working after the materialization turn completes while its prompt is working", () => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    expect(project({ threads: [thread([card])], workflow: workflow([node("node-1", "character-1", "working")]),
      turnsById: { "materialize-1": turn("materialize-1", "completed") } })).toMatchObject({
      phase: "working", motionState: "working", evidence: { source: "prompt_preparation", nodeId: "node-1" },
    });
  });

  it("projects queued work and typed awaiting as waiting motion", () => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    expect(project({ threads: [thread([card])], workflow: workflow([node("node-1", "character-1", "queued")]) }))
      .toMatchObject({ phase: "queued", motionState: "waiting" });
    const waitingSession = session({ status: "waiting_user", occurrence_id: "character-1", character_phase: "main" });
    waitingSession.awaiting = { awaiting_id: "awaiting-1", workflow_id: "workflow-1", session_id: "session-1",
      checkpoint_id: "checkpoint-1", kind: "reference_source", requires_user_action: true,
      resume_policy: "submit_interaction", interaction_id: "interaction-1", node_ids: ["node-1"],
      stage: "character", stage_revision: 1, created_at: "2026-09-07T00:00:00Z" };
    expect(project({ threads: [thread([card])], workflow: workflow([node("node-1", "character-1", "ready")]),
      session: waitingSession })).toMatchObject({ phase: "awaiting_user", motionState: "waiting" });
  });

  it("does not treat prompt ready as success while associated media is running", () => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    expect(project({ threads: [thread([card])], workflow: workflow([node("node-1", "character-1", "ready")]),
      runtime: runtime("node-1", "waiting_provider") })).toMatchObject({
      phase: "working", motionState: "working", evidence: { source: "node_runtime" },
    });
  });

  it("keeps a ready Draft waiting when no authoritative terminal operation exists", () => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    const readyNode = node("node-1", "character-1", "ready");
    readyNode.latest_attempt = null;
    expect(project({ threads: [thread([card])], workflow: workflow([readyNode]) }))
      .toMatchObject({ phase: "queued", motionState: "waiting",
        evidence: { source: "prompt_preparation", nodeId: "node-1" } });
  });

  it.each([
    ["succeeded", "ready", "succeeded"],
    ["failed", "failed", "failed"],
    ["cancelled", "draft", "cancelled"],
  ] as const)("uses persisted latest-attempt %s after runtime becomes inactive", (attemptStatus, nodeStatus, phase) => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    const terminalNode = node("node-1", "character-1", "ready");
    terminalNode.status = nodeStatus;
    terminalNode.latest_attempt = { ...terminalNode.latest_attempt!, status: attemptStatus };
    expect(project({ threads: [thread([card])], workflow: workflow([terminalNode]), runtime: null }))
      .toMatchObject({ phase, motionState: "idle", evidence: { source: "node_attempt", nodeId: "node-1" } });
  });

  it("uses source-only readiness and persisted output as terminal authority", () => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    const sourceNode = node("node-1", "character-1", "ready");
    sourceNode.execution_mode = "source_only";
    sourceNode.status = "ready";
    sourceNode.latest_attempt = null;
    expect(project({ threads: [thread([card])], workflow: workflow([sourceNode]) }))
      .toMatchObject({ phase: "succeeded", motionState: "idle", evidence: { source: "node" } });

    const outputNode = node("node-1", "character-1", "ready");
    outputNode.status = "ready";
    outputNode.output_asset_id = "asset-1";
    outputNode.output_asset_version_id = "version-1";
    outputNode.latest_attempt = null;
    expect(project({ threads: [thread([card])], workflow: workflow([outputNode]) }))
      .toMatchObject({ phase: "succeeded", motionState: "idle", evidence: { source: "node" } });
  });

  it("treats superseded prompt preparation as terminal", () => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    expect(project({ threads: [thread([card])], workflow: workflow([node("node-1", "character-1", "superseded")]) }))
      .toMatchObject({ phase: "superseded", motionState: "idle", evidence: { source: "prompt_preparation" } });
  });

  it("ignores stale node runtime and failed indexes from a prior execution", () => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    const currentNode = node("node-1", "character-1", "ready");
    currentNode.latest_attempt = { ...currentNode.latest_attempt!, execution_id: "execution-2", status: "queued" };
    const staleRuntime = runtime("node-1", "running");
    staleRuntime.failed_node_ids = ["node-1"];
    expect(project({ threads: [thread([card])], workflow: workflow([currentNode]), runtime: staleRuntime }))
      .toMatchObject({ phase: "queued", motionState: "waiting", evidence: { source: "node_attempt" } });
  });

  it("stops the same task on an authoritative failure", () => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    expect(project({ threads: [thread([card])], workflow: workflow([node("node-1", "character-1", "failed")]),
      runtime: runtime("node-1", "running") })).toMatchObject({ phase: "failed", motionState: "idle" });
  });

  it("attributes a current runtime failure to its execution identity", () => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    const failedNode = node("node-1", "character-1", "ready");
    const failedRuntime = runtime("node-1", "running");
    failedRuntime.failed_node_ids = ["node-1"];
    expect(project({ threads: [thread([card])], workflow: workflow([failedNode]), runtime: failedRuntime }))
      .toMatchObject({ identity: { attemptKey: "node:node-1:execution-1" }, phase: "failed", motionState: "idle",
        evidence: { source: "node_runtime", nodeId: "node-1" } });
  });

  it("keeps a sibling node working when another node in the same materialization fails", () => {
    const card = proposal("character-1", "materialize-1", ["node-failed", "node-working"]);
    expect(project({ threads: [thread([card])], workflow: workflow([
      node("node-failed", "character-1", "failed"), node("node-working", "character-1", "working"),
    ]) })).toMatchObject({ phase: "working", motionState: "working",
      evidence: { source: "prompt_preparation", nodeId: "node-working" } });
  });

  it("does not leak node state across occurrences", () => {
    const first = proposal("character-1", "materialize-1", ["node-1"], 2);
    const second = proposal("character-2", "materialize-2", ["node-2"], 4);
    expect(project({ threads: [thread([first, second])], workflow: workflow([
      node("node-1", "character-1", "working"), node("node-2", "character-2", "failed"),
    ]), session: session({ status: "working", turn_id: "materialize-2", occurrence_id: "character-2", character_phase: "main" }) }))
      .toMatchObject({ identity: { occurrenceId: "character-2" }, phase: "failed", motionState: "idle" });
  });

  it("does not leak Main node state into the Turnaround phase", () => {
    const turnaround = proposal("character-1", "materialize-turnaround", ["node-main"], 4);
    turnaround.proposal.character_phase = "turnaround";
    expect(project({ threads: [thread([turnaround])], workflow: workflow([
      node("node-main", "character-1", "working"),
    ]) })).toMatchObject({ identity: { characterPhase: "turnaround" }, phase: "succeeded", motionState: "idle",
      evidence: { source: "materialization" } });
  });

  it("does not attach a current occurrence action to an unrelated historical header", () => {
    const historical = proposal("character-old", "materialize-old", ["node-old"], 2);
    const current = proposal("character-current", "materialize-current", ["node-current"], 4);
    const historicalThread = { ...thread([historical]), key: "stage:character_design:old" };
    const currentThread = { ...thread([current]), key: "stage:character_design:current" };
    const projected = projectRoleLifecycles({ threads: [historicalThread, currentThread], workflow: workflow([]), runtime: null,
      session: session({ status: "working", turn_id: "turn-current", occurrence_id: "character-current",
        character_phase: "main" }), turnsById: { "turn-current": turn("turn-current", "running") } });
    expect(projected.get(historicalThread.key)).toMatchObject({ phase: "unknown", motionState: "idle",
      evidence: { source: "unresolved" } });
    expect(projected.get(currentThread.key)).toMatchObject({ identity: { occurrenceId: "character-current" },
      phase: "working", motionState: "working", evidence: { source: "journey_action" } });
  });

  it("lets a newer retry attempt replace an older failed attempt", () => {
    const card = proposal("character-1", "retry-2", ["node-1"]);
    const retried = turn("retry-2", "running", { occurrence_id: "character-1", character_phase: "main" });
    retried.retry_of_turn_id = "attempt-1";
    retried.retry_attempt_no = 2;
    expect(project({ threads: [thread([card])], workflow: workflow([node("node-1", "character-1", "working", 2)]),
      runtime: runtime("node-1", "running", 2), turnsById: {
        "attempt-1": turn("attempt-1", "failed", { occurrence_id: "character-1", character_phase: "main" }),
        "retry-2": retried,
      } })).toMatchObject({ identity: { attemptKey: "node:node-1:execution-1" }, phase: "working", motionState: "working" });
  });

  it.each(["failed", "succeeded"] as const)(
    "lets an exact current action supersede an old %s node attempt in the same occurrence",
    (oldStatus) => {
      const old = proposal("character-1", "old-materialization", ["old-node"]);
      const oldNode = node("old-node", "character-1", "ready");
      oldNode.latest_attempt = { ...oldNode.latest_attempt!, status: oldStatus };
      const currentTurn = turn("current-turn", "running", { occurrence_id: "character-1", character_phase: "main" });
      const currentActivity = activity("current-activity", "current-turn", "working", 5);
      expect(project({ threads: [{ ...thread([old]), activities: [currentActivity] }], workflow: workflow([oldNode]),
        session: session({ status: "working", turn_id: "current-turn", occurrence_id: "character-1",
          character_phase: "main" }), turnsById: { "current-turn": currentTurn } }))
        .toMatchObject({ identity: { occurrenceId: "character-1", attemptKey: "current-turn:0" },
          phase: "working", motionState: "working", evidence: { source: "journey_action", turnId: "current-turn" } });
    },
  );

  it("lets an exact failed current action stop an older working node", () => {
    const old = proposal("character-1", "old-materialization", ["old-node"]);
    const failedTurn = turn("current-turn", "failed", { occurrence_id: "character-1", character_phase: "main" });
    expect(project({ threads: [{ ...thread([old]), activities: [
      activity("current-activity", "current-turn", "working", 5),
    ] }], workflow: workflow([node("old-node", "character-1", "working")]),
    session: session({ status: "working", turn_id: "current-turn", occurrence_id: "character-1",
      character_phase: "main" }), turnsById: { "current-turn": failedTurn } }))
      .toMatchObject({ identity: { attemptKey: "current-turn:0" }, phase: "failed", motionState: "idle",
        evidence: { source: "journey_action", turnId: "current-turn" } });
  });

  it("keeps current prompt work active after its exact materialization turn completes", () => {
    const current = proposal("character-1", "current-materialization", ["current-node"]);
    expect(project({ threads: [thread([current])], workflow: workflow([node("current-node", "character-1", "working")]),
      session: session({ status: "working", turn_id: "current-materialization", occurrence_id: "character-1",
        character_phase: "main" }), turnsById: {
        "current-materialization": turn("current-materialization", "completed", {
          occurrence_id: "character-1", character_phase: "main",
        }),
      } })).toMatchObject({ phase: "working", motionState: "working",
        evidence: { source: "prompt_preparation", nodeId: "current-node" } });
  });

  it("keeps exact queued materialization waiting after its action turn completes", () => {
    const current = proposal("character-1", "current-materialization", []);
    current.proposal.materialization!.status = "queued";
    expect(project({ threads: [thread([current])], session: session({ status: "working",
      turn_id: "current-materialization", occurrence_id: "character-1", character_phase: "main" }),
    turnsById: { "current-materialization": turn("current-materialization", "completed") } }))
      .toMatchObject({ phase: "queued", motionState: "waiting", evidence: { source: "materialization" } });
  });

  it("keeps historical proposals while attaching a new occurrence action through its exact current activity", () => {
    const historical = proposal("character-old", "old-materialization", ["old-node"]);
    const currentTurn = turn("current-turn", "queued", { occurrence_id: "character-current", character_phase: "main" });
    expect(project({ threads: [{ ...thread([historical]), activities: [
      activity("current-activity", "current-turn", "working", 5),
    ] }], workflow: workflow([]), session: session({ status: "reserved", turn_id: "current-turn",
      occurrence_id: "character-current", character_phase: "main" }), turnsById: { "current-turn": currentTurn } }))
      .toMatchObject({ identity: { occurrenceId: "character-current", attemptKey: "current-turn:0" },
        phase: "queued", motionState: "waiting", evidence: { source: "journey_action", turnId: "current-turn" } });
  });

  it("keeps an orphan reserved action unknown and static", () => {
    expect(project({ session: session({ status: "reserved", turn_id: "missing", occurrence_id: "character-1",
      character_phase: "main" }) })).toMatchObject({ phase: "unknown", motionState: "idle",
      evidence: { source: "unresolved" } });
  });

  it("does not keep a working activity alive after its exact owning turn fails", () => {
    expect(project({ turnsById: { failed: turn("failed", "failed") },
      workflow: workflow([]), session: null, runtime: null,
      // The activity status can lag the authoritative turn projection during refresh.
      threads: [{ ...thread(), activities: [activity("activity-1", "failed", "working")] }],
    })).toMatchObject({ phase: "failed", motionState: "idle", evidence: { source: "activity", turnId: "failed" } });
  });

  it("shows waiting when a working activity's exact owning turn is queued", () => {
    expect(project({ turnsById: { queued: turn("queued", "queued") }, workflow: workflow([]), session: null,
      runtime: null, threads: [{ ...thread(), activities: [activity("activity-1", "queued", "working")] }],
    })).toMatchObject({ phase: "queued", motionState: "waiting", evidence: { source: "activity" } });
  });

  it("keeps an active activity unknown until its exact turn is hydrated", () => {
    expect(project({ workflow: workflow([]), session: null, runtime: null, turnsById: {},
      threads: [{ ...thread(), activities: [activity("activity-1", "missing", "working")] }],
    })).toMatchObject({ phase: "unknown", motionState: "idle", evidence: { source: "unresolved" } });
  });

  it("uses only an exact existing planning metadata turn", () => {
    expect(project({ threads: [{ ...thread(), planning: [planning("planning-turn")] }],
      turnsById: { "planning-turn": turn("planning-turn", "queued") } }))
      .toMatchObject({ phase: "queued", motionState: "waiting", evidence: { source: "planning", turnId: "planning-turn" } });
  });

  it("accepts an explicitly application-associated node without prompt identity for a non-occurrence role", () => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    card.proposal.capability_id = "scene_design";
    card.proposal.proposal_kind = "scene";
    card.proposal.occurrence_id = null;
    card.proposal.character_phase = null;
    const sceneThread = { ...thread([card]), key: "stage:scene_design", capability_id: "scene_design" as const };
    const sceneNode = node("node-1", "character-1", "ready");
    sceneNode.creative_role = "scene";
    sceneNode.prompt_preparation = null;
    sceneNode.status = "ready";
    sceneNode.output_asset_id = "asset-scene";
    sceneNode.latest_attempt = null;
    expect(projectRoleLifecycles({ threads: [sceneThread], workflow: workflow([sceneNode]), runtime: null,
      session: null, turnsById: {} }).get(sceneThread.key))
      .toMatchObject({ phase: "succeeded", motionState: "idle", evidence: { source: "node", nodeId: "node-1" } });
  });

  it("uses a persisted active latest attempt when runtime is absent", () => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    card.proposal.capability_id = "scene_design";
    card.proposal.proposal_kind = "scene";
    card.proposal.occurrence_id = null;
    card.proposal.character_phase = null;
    const sceneThread = { ...thread([card]), key: "stage:scene_design", capability_id: "scene_design" as const };
    const sceneNode = node("node-1", "character-1", "ready");
    sceneNode.creative_role = "scene";
    sceneNode.prompt_preparation = null;
    sceneNode.latest_attempt = { ...sceneNode.latest_attempt!, status: "running" };
    const projected = projectRoleLifecycles({ threads: [sceneThread], workflow: workflow([sceneNode]), runtime: null,
      session: null, turnsById: {} });
    expect(projected.get(sceneThread.key)).toMatchObject({ phase: "working", motionState: "working",
      evidence: { source: "node_attempt", nodeId: "node-1" } });
  });

  it("lets a new working prompt attempt supersede an older terminal media attempt", () => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    const retryNode = node("node-1", "character-1", "working", 2);
    retryNode.latest_attempt = { ...retryNode.latest_attempt!, status: "succeeded" };
    expect(project({ threads: [thread([card])], workflow: workflow([retryNode]) }))
      .toMatchObject({ identity: { attemptKey: "prompt-node-1:2" }, phase: "working", motionState: "working",
        evidence: { source: "prompt_preparation" } });
  });

  it("uses active media execution identity after prompt preparation becomes ready", () => {
    const card = proposal("character-1", "materialize-1", ["node-1"]);
    const mediaNode = node("node-1", "character-1", "ready");
    mediaNode.latest_attempt = { ...mediaNode.latest_attempt!, execution_id: "execution-media", status: "running" };
    expect(project({ threads: [thread([card])], workflow: workflow([mediaNode]) }))
      .toMatchObject({ identity: { attemptKey: "node:node-1:execution-media" }, phase: "working", motionState: "working",
        evidence: { source: "node_attempt" } });
  });

  it("keeps an orphan working action unknown when it has no live owner", () => {
    const card = proposal("character-1", "old-materialization", [], 2);
    expect(project({ threads: [thread([card])], session: session({ status: "working", turn_id: "missing",
      occurrence_id: "character-1", character_phase: "main" }) }))
      .toMatchObject({ phase: "unknown", motionState: "idle", evidence: { source: "unresolved" } });
  });

  it("does not let a Main reference awaiting checkpoint authorize Turnaround", () => {
    const card = proposal("character-1", "old-materialization", [], 2);
    card.proposal.character_phase = "turnaround";
    const awaitingSession = session({ status: "waiting_user", turn_id: null, occurrence_id: "character-1",
      character_phase: "turnaround" });
    awaitingSession.awaiting = { awaiting_id: "awaiting-main", workflow_id: "workflow-1", session_id: "session-1",
      checkpoint_id: "checkpoint-main", kind: "reference_source", requires_user_action: true,
      resume_policy: "submit_interaction", interaction_id: "interaction-main", node_ids: [], stage: "character",
      stage_revision: 1, created_at: "2026-09-07T00:00:00Z" };
    awaitingSession.interaction = { content: { content_kind: "reference_source", reference_kind: "character_main",
      occurrence_id: "character-1" } } as GuidedSessionStateV2["interaction"];
    expect(project({ threads: [thread([card])], session: awaitingSession }))
      .toMatchObject({ phase: "unknown", motionState: "idle", evidence: { source: "unresolved" } });
  });

  it("treats an omitted Character concept-choice phase as schema-defined Main", () => {
    const card = proposal("character-1", "old-materialization", [], 2);
    const awaitingSession = session({ status: "waiting_user", turn_id: null, occurrence_id: "character-1",
      character_phase: "main" });
    awaitingSession.awaiting = { awaiting_id: "awaiting-concept", workflow_id: "workflow-1", session_id: "session-1",
      checkpoint_id: "checkpoint-concept", kind: "concept_selection", requires_user_action: true,
      resume_policy: "submit_interaction", interaction_id: "interaction-concept", node_ids: [], stage: "character",
      stage_revision: 1, created_at: "2026-09-07T00:00:00Z" };
    awaitingSession.interaction = { content: { content_kind: "concept_choice", occurrence_id: "character-1",
      stage: "character", stage_revision: 1 } } as GuidedSessionStateV2["interaction"];
    expect(project({ threads: [thread([card])], session: awaitingSession }))
      .toMatchObject({ phase: "awaiting_user", motionState: "waiting", evidence: { source: "journey_action" } });
  });

  it("rejects stale session, turn, runtime, and node authority from another workflow", () => {
    const card = proposal("character-1", "old-turn", ["old-node"]);
    card.proposal.workflow_id = "workflow-old";
    const staleNode = node("old-node", "character-1", "working");
    staleNode.workflow_id = "workflow-old";
    const staleRuntime = runtime("old-node", "running");
    staleRuntime.workflow_id = "workflow-old";
    const staleSession = session({ status: "working", turn_id: "old-turn", occurrence_id: "character-1",
      character_phase: "main" });
    staleSession.workflow_id = "workflow-old";
    const staleTurn = turn("old-turn", "running", { occurrence_id: "character-1", character_phase: "main" });
    staleTurn.workflow_id = "workflow-old";
    expect(project({ threads: [{ ...thread([card]), activities: [activity("old-activity", "old-turn", "working", 3)] }],
      workflow: workflow([staleNode]), runtime: staleRuntime, session: staleSession,
      turnsById: { "old-turn": staleTurn } })).toMatchObject({ phase: "unknown", motionState: "idle",
        evidence: { source: "unresolved" } });
  });
});
