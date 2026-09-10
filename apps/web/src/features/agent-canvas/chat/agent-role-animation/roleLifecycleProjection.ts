import type {
  AgentCanvasChatTurnV2,
  AgentCanvasWorkflowV2,
  AgentCapabilityIdV2,
  CanvasNodeV2,
  CanvasRuntimeSnapshotV2,
  ChatProposalCardV2,
  GuidedProductionJourneyV2,
  GuidedSessionStateV2,
} from "../../../../types-v2.ts";
import type { StageThreadUnit } from "../stageThreadProjection.ts";
import type { AgentRoleMotionState } from "./types.ts";

export type RoleLifecyclePhase =
  | "queued"
  | "working"
  | "awaiting_user"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "superseded"
  | "unknown";

export interface RoleLifecycleIdentity {
  workflowId: string;
  capabilityId: AgentCapabilityIdV2;
  occurrenceId: string | null;
  characterPhase: "main" | "turnaround" | null;
  attemptKey: string;
}

export interface RoleLifecycleEvidence {
  source: "prompt_preparation" | "node_runtime" | "guidance_awaiting" | "journey_action"
    | "materialization" | "activity" | "planning" | "node_attempt" | "node" | "unresolved";
  turnId?: string;
  materializationId?: string;
  nodeId?: string;
  operationId?: string;
  reason?: string;
}

export interface RoleLifecycleProjection {
  identity: RoleLifecycleIdentity;
  phase: RoleLifecyclePhase;
  motionState: AgentRoleMotionState;
  evidence: RoleLifecycleEvidence;
}

export interface ProjectRoleLifecyclesInput {
  threads: readonly StageThreadUnit[];
  workflow: Pick<AgentCanvasWorkflowV2, "workflow_id" | "nodes">;
  runtime: CanvasRuntimeSnapshotV2 | null;
  session: GuidedSessionStateV2 | null;
  turnsById: Readonly<Record<string, AgentCanvasChatTurnV2>>;
}

const CAPABILITY_BY_STAGE: Partial<Record<GuidedProductionJourneyV2["stage"], AgentCapabilityIdV2>> = {
  world_view: "world_setting", product: "product_design", props: "prop_design", character: "character_design",
  scene: "scene_design", narrative_direction: "script_authoring", storyboard_plan: "storyboard_design",
  storyboard_grids: "storyboard_design", videos: "video_direction", bgm: "bgm_direction", editing: "video_direction",
};

function motionState(phase: RoleLifecyclePhase): AgentRoleMotionState {
  if (phase === "working") return "working";
  if (phase === "queued" || phase === "awaiting_user") return "waiting";
  return "idle";
}

function requestIdentity(turn: AgentCanvasChatTurnV2 | null | undefined): {
  occurrenceId: string | null;
  characterPhase: "main" | "turnaround" | null;
} {
  const occurrenceId = typeof turn?.request.occurrence_id === "string" ? turn.request.occurrence_id : null;
  const characterPhase = turn?.request.character_phase === "main" || turn?.request.character_phase === "turnaround"
    ? turn.request.character_phase
    : null;
  return { occurrenceId, characterPhase };
}

function scopedProposal(unit: StageThreadUnit, session: GuidedSessionStateV2 | null, workflowId: string): ChatProposalCardV2 | null {
  const action = session?.journey.active_action;
  const proposals = unit.proposals.filter(({ proposal }) => proposal.workflow_id === workflowId)
    .toSorted((left, right) => right.sequence - left.sequence);
  if (action && CAPABILITY_BY_STAGE[action.stage] === unit.capability_id) {
    const exact = proposals.find(({ proposal }) => (
      proposal.occurrence_id === action.occurrence_id
      && proposal.character_phase === action.character_phase
    ));
    if (exact) return exact;
    return null;
  }
  return proposals[0] ?? null;
}

function associatedNodes(selected: ChatProposalCardV2 | null, workflow: ProjectRoleLifecyclesInput["workflow"]) {
  if (!selected) return [];
  const nodeIds = new Set(selected.proposal.latest_application?.created_node_ids ?? []);
  if (selected.proposal.target_node_id) nodeIds.add(selected.proposal.target_node_id);
  return workflow.nodes.filter((node) => {
    if (node.workflow_id !== workflow.workflow_id) return false;
    if (!nodeIds.has(node.node_id)) return false;
    const { occurrence_id: occurrenceId, character_phase: characterPhase } = selected.proposal;
    if (occurrenceId === null && characterPhase === null) {
      return node.prompt_preparation?.occurrence_id == null
        && node.prompt_preparation?.character_phase == null;
    }
    return node.prompt_preparation?.occurrence_id === occurrenceId
      && node.prompt_preparation?.character_phase === characterPhase;
  });
}

function identityFor(
  workflowId: string,
  unit: StageThreadUnit,
  selected: ChatProposalCardV2 | null,
  node: CanvasNodeV2 | null,
  turn: AgentCanvasChatTurnV2 | null,
): RoleLifecycleIdentity {
  const turnIdentity = requestIdentity(turn);
  const occurrenceId = node?.prompt_preparation?.occurrence_id
    ?? selected?.proposal.occurrence_id
    ?? turnIdentity.occurrenceId;
  const characterPhase = node?.prompt_preparation?.character_phase
    ?? selected?.proposal.character_phase
    ?? turnIdentity.characterPhase;
  const attemptKey = node?.prompt_preparation
    ? `${node.prompt_preparation.operation_id ?? `prompt-${node.node_id}`}:${node.prompt_preparation.attempt_no}`
    : node?.latest_attempt
      ? `node:${node.node_id}:${node.latest_attempt.execution_id}`
    : selected?.proposal.materialization
      ? `${selected.proposal.materialization.materialization_id}:${selected.proposal.materialization.attempt_no}`
      : turn
        ? `${turn.retry_of_turn_id ?? turn.turn_id}:${turn.retry_attempt_no}`
        : `stage:${unit.key}`;
  return { workflowId, capabilityId: unit.capability_id, occurrenceId, characterPhase, attemptKey };
}

function result(identity: RoleLifecycleIdentity, phase: RoleLifecyclePhase, evidence: RoleLifecycleEvidence): RoleLifecycleProjection {
  return { identity, phase, motionState: motionState(phase), evidence };
}

function nodeAttemptIdentity(identity: RoleLifecycleIdentity, node: CanvasNodeV2): RoleLifecycleIdentity {
  return node.latest_attempt
    ? { ...identity, attemptKey: `node:${node.node_id}:${node.latest_attempt.execution_id}` }
    : identity;
}

function nodeProjection(
  identity: RoleLifecycleIdentity,
  node: CanvasNodeV2,
  runtime: CanvasRuntimeSnapshotV2 | null,
  session: GuidedSessionStateV2 | null,
): RoleLifecycleProjection | null {
  const preparation = node.prompt_preparation;
  const currentRuntime = runtime?.workflow_id === node.workflow_id ? runtime : null;
  const nodeRuntime = currentRuntime?.node_runtime[node.node_id];
  const runtimeIsCurrent = Boolean(
    nodeRuntime?.execution_id
    && node.latest_attempt?.execution_id === nodeRuntime.execution_id
    && currentRuntime?.active_execution_id === nodeRuntime.execution_id,
  );
  if (preparation?.status === "failed") {
    return result(identity, "failed", { source: "prompt_preparation", nodeId: node.node_id,
      operationId: preparation?.operation_id ?? undefined });
  }
  if (runtimeIsCurrent && currentRuntime?.failed_node_ids.includes(node.node_id)) {
    return result(nodeAttemptIdentity(identity, node), "failed", { source: "node_runtime", nodeId: node.node_id });
  }
  if (preparation?.status === "superseded") return result(identity, "superseded", {
    source: "prompt_preparation", nodeId: node.node_id, operationId: preparation.operation_id ?? undefined,
  });
  const awaiting = session?.awaiting;
  if (awaiting?.requires_user_action && awaiting.node_ids.includes(node.node_id)) {
    return result(identity, "awaiting_user", { source: "guidance_awaiting", nodeId: node.node_id });
  }
  if (runtimeIsCurrent && nodeRuntime) {
    if (nodeRuntime.phase === "queued" || nodeRuntime.phase === "waiting_for_input" || nodeRuntime.phase === "blocked_by_upstream") {
      return result(nodeAttemptIdentity(identity, node), "queued", { source: "node_runtime", nodeId: node.node_id });
    }
    if (nodeRuntime.phase) return result(nodeAttemptIdentity(identity, node), "working", {
      source: "node_runtime", nodeId: node.node_id,
    });
  }
  const attemptStatus = node.latest_attempt?.status;
  if (preparation?.status === "working") return result(identity, "working", {
    source: "prompt_preparation", nodeId: node.node_id, operationId: preparation.operation_id ?? undefined,
  });
  if (preparation?.status === "queued") return result(identity, "queued", {
    source: "prompt_preparation", nodeId: node.node_id, operationId: preparation.operation_id ?? undefined,
  });
  if (preparation?.status === "waiting_user") return result(identity, "awaiting_user", {
    source: "prompt_preparation", nodeId: node.node_id,
  });
  if (attemptStatus === "running") {
    return result(nodeAttemptIdentity(identity, node), "working", { source: "node_attempt", nodeId: node.node_id });
  }
  if (attemptStatus === "queued" || attemptStatus === "waiting" || attemptStatus === "blocked") {
    return result(nodeAttemptIdentity(identity, node), "queued", { source: "node_attempt", nodeId: node.node_id });
  }
  if (attemptStatus === "succeeded" || attemptStatus === "failed" || attemptStatus === "cancelled"
    || attemptStatus === "skipped_dependency") {
    const phase = attemptStatus === "succeeded" ? "succeeded"
      : attemptStatus === "failed" ? "failed" : "cancelled";
    return result(nodeAttemptIdentity(identity, node), phase, { source: "node_attempt", nodeId: node.node_id });
  }
  if (node.status === "failed") return result(identity, "failed", { source: "node", nodeId: node.node_id });
  if (node.status === "ready" && (node.execution_mode === "source_only" || node.output_asset_id !== null
    || node.output_asset_version_id !== null)) {
    return result(identity, "succeeded", { source: "node", nodeId: node.node_id });
  }
  if (preparation?.status === "ready") return result(identity, "queued", {
    source: "prompt_preparation", nodeId: node.node_id, operationId: preparation.operation_id ?? undefined,
    reason: "prompt ready; awaiting an authoritative downstream terminal operation",
  });
  return null;
}

function projectThread(input: ProjectRoleLifecyclesInput, unit: StageThreadUnit): RoleLifecycleProjection {
  const workflowId = input.workflow.workflow_id;
  const session = input.session?.workflow_id === workflowId ? input.session : null;
  const selected = scopedProposal(unit, session, workflowId);
  const action = session?.journey.active_action;
  const currentActionTargetsUnit = Boolean(action && CAPABILITY_BY_STAGE[action.stage] === unit.capability_id);
  const actionTurnIsInThread = Boolean(action?.turn_id && (
    unit.activities.some((activity) => activity.turn_id === action.turn_id)
    || unit.planning.some((message) => message.metadata?.turn_id === action.turn_id)
  ));
  const materialization = selected?.proposal.materialization ?? null;
  const actionOwnsSelectedMaterialization = Boolean(action?.turn_id && materialization?.turn_id === action.turn_id);
  const exactActionOwner = actionTurnIsInThread || actionOwnsSelectedMaterialization;
  if (currentActionTargetsUnit && unit.proposals.length > 0 && selected === null && !exactActionOwner) {
    const fallbackIdentity = identityFor(input.workflow.workflow_id, unit, null, null, null);
    return result(fallbackIdentity, "unknown", { source: "unresolved", turnId: action?.turn_id ?? undefined,
      reason: "current action does not match this historical occurrence and phase" });
  }
  const materializationTurn = materialization ? input.turnsById[materialization.turn_id] ?? null : null;
  const owningTurn = materializationTurn?.workflow_id === workflowId ? materializationTurn : null;
  if (action && currentActionTargetsUnit && exactActionOwner) {
    const candidateActionTurn = action.turn_id ? input.turnsById[action.turn_id] ?? null : null;
    const actionTurn = candidateActionTurn?.workflow_id === workflowId ? candidateActionTurn : null;
    const actionIdentity = {
      ...identityFor(input.workflow.workflow_id, unit, null, null, actionTurn),
      occurrenceId: action.occurrence_id,
      characterPhase: action.character_phase,
    };
    if (actionTurn?.status === "queued") {
      return result(actionIdentity, "queued", { source: "journey_action", turnId: action.turn_id ?? undefined });
    }
    if (actionTurn?.status === "running") {
      const phase = action.status === "waiting_user" ? "awaiting_user"
        : action.status === "reserved" ? "queued" : "working";
      return result(actionIdentity, phase, { source: "journey_action", turnId: action.turn_id ?? undefined });
    }
    if (actionTurn?.status === "failed" || actionTurn?.status === "superseded") {
      return result(actionIdentity, actionTurn.status, {
        source: "journey_action", turnId: action.turn_id ?? undefined,
      });
    }
    if (actionTurn?.status === "completed" && !actionOwnsSelectedMaterialization) {
      return result(actionIdentity, "succeeded", {
        source: "journey_action", turnId: action.turn_id ?? undefined,
      });
    }
  }
  const nodes = associatedNodes(selected, input.workflow);
  const nodeResults = nodes.flatMap((node) => {
    const identity = identityFor(input.workflow.workflow_id, unit, selected, node, owningTurn);
    const projected = nodeProjection(identity, node, input.runtime, session);
    return projected ? [projected] : [];
  }).toSorted((left, right) => {
    const priority: Record<RoleLifecyclePhase, number> = {
      working: 4, awaiting_user: 3, queued: 3, failed: 2, cancelled: 2, superseded: 2, succeeded: 1, unknown: 0,
    };
    return priority[right.phase] - priority[left.phase];
  });
  if (nodeResults[0]) return nodeResults[0];

  const identity = identityFor(input.workflow.workflow_id, unit, selected, null, owningTurn);
  const emptyThread = unit.proposals.length === 0 && unit.activities.length === 0 && unit.planning.length === 0;
  if (action && CAPABILITY_BY_STAGE[action.stage] === unit.capability_id
    && (selected !== null || actionTurnIsInThread || emptyThread)) {
    const candidateActionTurn = action.turn_id ? input.turnsById[action.turn_id] : null;
    const actionTurn = candidateActionTurn?.workflow_id === workflowId ? candidateActionTurn : null;
    const awaiting = session?.awaiting;
    const associatedNodeIds = new Set(nodes.map((node) => node.node_id));
    const awaitingOwnsNode = Boolean(awaiting?.node_ids.some((nodeId) => associatedNodeIds.has(nodeId)));
    const interactionContent = session?.interaction?.content;
    const awaitingPhase = interactionContent?.content_kind === "reference_source"
      ? interactionContent.reference_kind === "character_main" ? "main" : null
      : interactionContent?.content_kind === "concept_choice"
        ? interactionContent.character_phase
          ?? (interactionContent.stage === "character" && interactionContent.occurrence_id !== null ? "main" : null)
        : null;
    const awaitingOwnsOccurrence = Boolean(
      awaiting?.requires_user_action
      && awaiting.stage === action.stage
      && awaiting.stage_revision === action.stage_revision
      && interactionContent && "occurrence_id" in interactionContent
      && interactionContent.occurrence_id === action.occurrence_id
      && awaitingPhase === action.character_phase,
    );
    if (actionOwnsSelectedMaterialization
      && (materialization?.status === "queued" || materialization?.status === "working")) {
      return result(identity, materialization.status, { source: "materialization",
        turnId: materialization.turn_id, materializationId: materialization.materialization_id });
    }
    const validOwner = actionTurn?.status === "queued" || actionTurn?.status === "running"
      || awaitingOwnsNode || awaitingOwnsOccurrence;
    if (!validOwner) {
      return result(identity, "unknown", { source: "unresolved", turnId: action.turn_id ?? undefined,
        reason: "active action has no live turn, associated node, or awaiting checkpoint" });
    }
    const phase = action.status === "working" ? "working" : action.status === "waiting_user" ? "awaiting_user" : "queued";
    return result(identity, phase, { source: "journey_action", turnId: action.turn_id ?? undefined });
  }
  if (materialization) {
    const phase = materialization.status === "completed" ? "succeeded" : materialization.status === "failed"
      ? "failed" : materialization.status;
    return result(identity, phase, { source: "materialization", turnId: materialization.turn_id,
      materializationId: materialization.materialization_id });
  }
  const latestActivity = [...unit.activities].sort((left, right) => right.sequence - left.sequence)[0];
  if (latestActivity) {
    const candidateTurn = input.turnsById[latestActivity.turn_id] ?? null;
    if (candidateTurn && candidateTurn.workflow_id !== workflowId) {
      return result(identity, "unknown", { source: "unresolved", turnId: latestActivity.turn_id,
        reason: "activity turn belongs to another workflow" });
    }
    if (!candidateTurn && latestActivity.status === "working") {
      return result(identity, "unknown", { source: "unresolved", turnId: latestActivity.turn_id,
        reason: "active activity turn is not hydrated" });
    }
    const turn = candidateTurn;
    const activityIdentity = identityFor(input.workflow.workflow_id, unit, null, null, turn);
    const phase = turn?.status === "queued" ? "queued"
      : turn?.status === "failed" ? "failed"
      : turn?.status === "superseded" ? "superseded"
        : turn?.status === "completed" ? "succeeded"
          : latestActivity.status === "completed" ? "succeeded" : latestActivity.status;
    return result(activityIdentity, phase, { source: "activity", turnId: latestActivity.turn_id });
  }
  const latestPlanning = [...unit.planning].sort((left, right) => right.sequence - left.sequence)
    .find((message) => typeof message.metadata?.turn_id === "string"
      && input.turnsById[message.metadata.turn_id]?.workflow_id === workflowId);
  const planningTurnId = typeof latestPlanning?.metadata?.turn_id === "string" ? latestPlanning.metadata.turn_id : null;
  const planningTurn = planningTurnId ? input.turnsById[planningTurnId] : null;
  if (planningTurnId && planningTurn) {
    const planningIdentity = identityFor(input.workflow.workflow_id, unit, null, null, planningTurn);
    const phase: RoleLifecyclePhase = planningTurn.status === "queued" ? "queued"
      : planningTurn.status === "running" ? "working"
        : planningTurn.status === "completed" ? "succeeded"
          : planningTurn.status === "failed" ? "failed" : "superseded";
    return result(planningIdentity, phase, { source: "planning", turnId: planningTurnId });
  }
  return result(identity, "unknown", { source: "unresolved", reason: "no authoritative lifecycle owner" });
}

export function projectRoleLifecycles(input: ProjectRoleLifecyclesInput): ReadonlyMap<string, RoleLifecycleProjection> {
  return new Map(input.threads.map((unit) => [unit.key, projectThread(input, unit)]));
}
