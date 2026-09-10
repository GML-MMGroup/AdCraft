import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { agentCanvasApi } from "../../src/api/agentCanvasApi.ts";
import { AgentCanvasChatPanel } from "../../src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx";
import { projectRoleLifecycles } from "../../src/features/agent-canvas/chat/agent-role-animation/roleLifecycleProjection.ts";
import { buildStageThreadTimeline } from "../../src/features/agent-canvas/chat/stageThreadProjection.ts";
import type { AgentCanvasChatTurnV2, AgentCanvasChatViewTimelineV2, AgentCanvasWorkflowV2, CanvasNodeV2,
  CanvasRuntimeSnapshotV2, ChatProposalCardV2, ChatTimelineItemV2, GuidedSessionStateV2 } from "../../src/types-v2.ts";
import "../../src/features/agent-canvas/chat/agent-canvas-chat.css";

const now = "2026-09-07T00:00:00Z";
type CharacterPhase = "main" | "turnaround";
type Selection = { occurrence: string; phase: CharacterPhase };
type FixtureState = "prompt-working" | "draft-waiting" | "media-working" | "succeeded" | "failed" | "cancelled" | "superseded";
const selections: Selection[] = [
  { occurrence: "character-1", phase: "main" },
  { occurrence: "character-2", phase: "main" },
  { occurrence: "character-2", phase: "turnaround" },
  { occurrence: "character-3", phase: "main" },
];

function turn(id: string, status: AgentCanvasChatTurnV2["status"], selected: Selection, attempt = 1): AgentCanvasChatTurnV2 {
  return { turn_id: id, workflow_id: "fixture-lifecycle", conversation_id: "fixture-conversation", status,
    turn_kind: "capability", request: { occurrence_id: selected.occurrence, character_phase: selected.phase },
    error_code: null, error_message: null, creation_mode: null, guidance_session_revision: null, continuation: null,
    retry_of_turn_id: attempt > 1 ? `${selected.occurrence}-${selected.phase}-turn-1` : null, retry_attempt_no: attempt,
    retryable: false, operation_stage: status === "running" ? "running" : null, operation_failure: null,
    created_at: now, updated_at: now };
}

function proposal(selected: Selection, index: number): ChatProposalCardV2 {
  const id = `${selected.occurrence}-${selected.phase}`;
  const occurrenceIndex = Number(selected.occurrence.replace("character-", ""));
  return { item_type: "proposal", sequence: index + 1, created_at: now, proposal: {
    proposal_id: `proposal-${id}`, workflow_id: "fixture-lifecycle", turn_id: `${id}-proposal-turn`, video_skill_run_id: null,
    topic_id: null, occurrence_id: selected.occurrence, occurrence_index: occurrenceIndex, occurrence_count: 3,
    character_phase: selected.phase, creative_direction_snapshot_id: null, proposal_revision: 1, source_proposal_id: null,
    proposal_kind: "character", capability_id: "character_design", capability_display_name: "Character Designer",
    options: [], proposed_references: [], target_node_id: `node-${id}`, target_node_revision: 1, proposal_purpose: null,
    availability: "applied", application_count: 1, latest_application: { application_id: `application-${id}`,
      option_id: "selected", action: "select_option", receipt_id: `receipt-${id}`, created_node_ids: [`node-${id}`],
      queued_execution_ids: [], created_at: now }, guidance_session_id: "session-1", guidance_session_revision: 1,
    actions: [], created_at: now, updated_at: now, materialization: { materialization_id: `materialization-${id}`,
      option_id: "selected", turn_id: `${id}-turn-1`, status: "completed", attempt_no: 1, retryable: false,
      error: null, created_at: now, updated_at: now } } };
}

function node(selected: Selection, state: FixtureState, attempt: number): CanvasNodeV2 {
  const id = `${selected.occurrence}-${selected.phase}`;
  const promptStatus = state === "prompt-working" || state === "media-working" ? "working"
    : state === "failed" ? "failed" : state === "superseded" ? "superseded" : "ready";
  const attemptStatus = state === "succeeded" ? "succeeded" : state === "cancelled" ? "cancelled"
    : state === "failed" ? "failed" : state === "media-working" ? "running" : "queued";
  return { node_id: `node-${id}`, workflow_id: "fixture-lifecycle", node_type: "image", creative_role: "character",
    role_contract_version: "1", title: `${selected.occurrence} ${selected.phase}`, status: state === "failed" ? "failed" : "draft",
    execution_mode: "generative", summary_prompt: null, generation_prompt: null, structured_content: {}, model_id: null,
    model_selection_mode: "automatic", model_ref: null, model_summary: null, parameters: {}, metadata: {},
    parameter_provenance: {}, prompt_context_snapshot_id: null, output_asset_id: state === "succeeded" ? `asset-${id}` : null,
    output_asset_version_id: state === "succeeded" ? `version-${id}` : null,
    latest_attempt: { execution_id: `execution-${id}-${attempt}`, member_id: `member-${id}`, run_intent_snapshot_id: null,
      status: attemptStatus, created_at: now, updated_at: now, error: null }, position: { x: 0, y: 0 }, revision: attempt,
    error: null, prompt_presentation: null, prompt_preparation: { status: promptStatus, operation_id: `prompt-${id}`,
      presentation_stream_id: null, attempt_no: attempt, context_snapshot_id: null, occurrence_id: selected.occurrence,
      character_phase: selected.phase, prompt_digest: null, role_variant: selected.phase === "main" ? "character_main" : "character_turnaround",
      recipe_id: null, recipe_version: null, recipe_digest: null, requirement_revision_id: null, requirement_revision_no: null,
      document_revisions: {}, binding_digest: null, character_identity_projection_digest: null,
      scene_environment_projection_digest: null, style_projection_digest: null, brief_digest: null, parameter_origins: [],
      compaction_policy_version: null, compaction_policy_digest: null, compaction_decisions: [], assertion_evidence: null,
      attempt_stage: null, error: promptStatus === "failed" ? { code: "failed", message: "failed", retryable: true } : null,
      updated_at: now }, created_at: now, updated_at: now } as unknown as CanvasNodeV2;
}

function session(selected: Selection): GuidedSessionStateV2 {
  return { session_id: "session-1", workflow_id: "fixture-lifecycle", status: "active", response_locale: "en-US",
    goal: {} as GuidedSessionStateV2["goal"], creative_authority: null, current_checkpoint: null, narrative_direction: null,
    element_decisions: [], current_topic_id: null, topics: [], active_proposal_id: `proposal-${selected.occurrence}-${selected.phase}`,
    active_style_skill_run_id: null, completion: {} as GuidedSessionStateV2["completion"], interaction: null, awaiting: null,
    revision: 1, updated_at: now, journey: { policy_version: "fixed_ad_production_v2", stage: "character",
      stage_status: "working", stage_revision: 1, decisions: [], active_occurrence_id: selected.occurrence,
      active_action: { action_id: "select-character", action_kind: "invoke_capability", stage: "character", stage_revision: 1,
        status: "working", turn_id: null, occurrence_id: selected.occurrence, character_phase: selected.phase },
      suspended_action: null, transition_evidence: [] } };
}

let timelineSession = session(selections[0]!);
let fixtureTurns: Record<string, AgentCanvasChatTurnV2> = {};
const items: ChatTimelineItemV2[] = selections.map(proposal);
Object.assign(agentCanvasApi, Object.fromEntries(Object.keys(agentCanvasApi).map(key => [key,
  async () => { throw new Error(`API disabled in lifecycle fixture: ${key}`); }])));
Object.assign(agentCanvasApi, {
  agentCanvasExecutionSettings: async () => ({ value: { workflow_id: "fixture-lifecycle", media_execution_mode: "manual",
    revision: 1, created_at: now, updated_at: now }, etag: '"fixture"' }),
  agentCanvasCreativeSession: async () => { throw new Error("No creative session in lifecycle fixture"); },
  agentCanvasChatTimeline: async (): Promise<AgentCanvasChatViewTimelineV2> => ({ workflow_id: "fixture-lifecycle",
    conversation_id: "fixture-conversation", guidanceSession: structuredClone(timelineSession), guidanceAdvancePrecondition: null,
    continuations: [], current_session_actions: [], items: structuredClone(items), presentationItems: null, next_cursor: items.length }),
  agentCanvasChatTurn: async (_workflowId: string, turnId: string) => structuredClone(fixtureTurns[turnId]!),
} satisfies Partial<typeof agentCanvasApi>);

function LifecycleFixture() {
  const [selected, setSelected] = useState(selections[0]!);
  const [states, setStates] = useState<Record<string, FixtureState>>({
    "character-1:main": "prompt-working", "character-2:main": "draft-waiting",
    "character-2:turnaround": "failed", "character-3:main": "media-working",
  });
  const [attempts, setAttempts] = useState<Record<string, number>>({ "character-1:main": 1, "character-2:main": 1,
    "character-2:turnaround": 1, "character-3:main": 1 });
  const [revision, setRevision] = useState(1);
  const key = `${selected.occurrence}:${selected.phase}`;
  const nodes = selections.map(item => node(item, states[`${item.occurrence}:${item.phase}`]!, attempts[`${item.occurrence}:${item.phase}`]!));
  const workflow: AgentCanvasWorkflowV2 = { workflow_id: "fixture-lifecycle", project_id: "fixture-lifecycle", workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1", revision, layout_revision: 1, nodes, bindings: [], assets: [], active_style_skill: null };
  const activeNode = nodes.find(item => item.prompt_preparation?.occurrence_id === selected.occurrence && item.prompt_preparation.character_phase === selected.phase)!;
  const state = states[key]!;
  const runtime: CanvasRuntimeSnapshotV2 | null = state === "media-working" ? { workflow_id: workflow.workflow_id,
    active_execution_id: activeNode.latest_attempt!.execution_id, execution_status: "running", node_runtime: { [activeNode.node_id]: {
      node_id: activeNode.node_id, visible_status: "working", phase: "waiting_provider", execution_id: activeNode.latest_attempt!.execution_id,
      provider_task_id: "provider-1", run_intent_snapshot_id: null, parameter_compilation_snapshot_id: null, effective_parameters: {},
      normalizations: [], omitted_optional_inputs: [], waiting_for_node_ids: [], blocked_by_node_ids: [], attempt_no: attempts[key]!,
      updated_at: now, error: null } }, queued_node_ids: [], working_node_ids: [activeNode.node_id], waiting_node_ids: [],
    ready_node_ids: [], failed_node_ids: [], events_cursor: revision, updated_at: now } : null;
  timelineSession = session(selected);
  fixtureTurns = Object.fromEntries(selections.map(item => { const itemKey = `${item.occurrence}:${item.phase}`;
    return [`${item.occurrence}-${item.phase}-turn-1`, turn(`${item.occurrence}-${item.phase}-turn-1`, "completed", item, attempts[itemKey])]; }));
  const lifecycle = useMemo(() => {
    const threads = buildStageThreadTimeline(items).filter(unit => unit.unit_type === "stage_thread");
    return projectRoleLifecycles({ threads, workflow, runtime, session: timelineSession, turnsById: fixtureTurns }).values().next().value!;
  }, [workflow, runtime]);
  const update = (next: FixtureState) => { setStates(current => ({ ...current, [key]: next })); setRevision(value => value + 1); };
  const choose = (next: Selection) => { setSelected(next); setRevision(value => value + 1); };
  return <main><section className="controls"><h1>Lifecycle authority fixture</h1>
    <button onClick={() => update("draft-waiting")}>Prompt ready draft</button><button onClick={() => update("media-working")}>Media working</button>
    <button onClick={() => update("succeeded")}>Media success</button>{(["failed", "cancelled", "superseded"] as const).map(value => <button key={value} onClick={() => update(value)}>{value}</button>)}
    <button onClick={() => { setAttempts(current => ({ ...current, [key]: current[key]! + 1 })); update("prompt-working"); }}>Retry task</button>
    {selections.map(value => <button key={`${value.occurrence}-${value.phase}`} onClick={() => choose(value)}>Occurrence {value.occurrence.replace("character-", "")} {value.phase === "main" ? "Main" : "Turnaround"}</button>)}
    <output data-testid="lifecycle-occurrence">{lifecycle.identity.occurrenceId}</output><output data-testid="lifecycle-character-phase">{lifecycle.identity.characterPhase}</output>
    <output data-testid="lifecycle-phase">{lifecycle.phase}</output><output data-testid="lifecycle-evidence">{lifecycle.evidence.source}</output><output data-testid="lifecycle-attempt">{lifecycle.identity.attemptKey}</output>
  </section><AgentCanvasChatPanel workflow={workflow} runtime={runtime} chatRevision={revision} chatEvents={[]} onFocusNode={() => undefined} /></main>;
}

const style = document.createElement("style");
style.textContent = `html,body,#root{margin:0;width:100%;height:100%;background:#0a0a0a;color:#eee;font:14px system-ui}*{box-sizing:border-box}.controls{padding:32px;margin-right:410px}.controls button{margin:4px;padding:8px}.controls output{display:block;margin:5px}`;
document.head.append(style);
createRoot(document.getElementById("root")!).render(<LifecycleFixture />);
