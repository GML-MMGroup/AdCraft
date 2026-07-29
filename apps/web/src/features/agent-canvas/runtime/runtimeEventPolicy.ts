import type { CanvasRuntimeEventV2 } from "../../../types-v2.ts";

export type AgentCanvasRuntimeRefreshPolicy = {
  refreshRuntime: boolean;
  refreshWorkflow: boolean;
  refreshAssets: boolean;
  refreshChat: boolean;
  refreshNodeId: string | null;
  refreshEditingNodeId: string | null;
};

const CHAT_EVENT_FRAGMENTS = [
  "chat_",
  "concept_",
  "proposal_",
  "expert_activity",
  "specialist_",
  "planning_",
  "script_artifact",
  "director_",
];

const AUTHORING_EVENT_FRAGMENTS = [
  "canvas_node_",
  "canvas_binding_",
  "binding_",
  "workflow_",
];

const AGENT_COMMAND_CHAT_EVENTS = new Set([
  "agent_command_plan_created",
  "agent_command_confirmation_required",
  "agent_command_confirmation_invalidated",
  "agent_command_plan_replaced",
  "agent_command_plan_replanned",
  "agent_command_plan_applied",
  "agent_command_plan_rejected",
  "agent_command_plan_failed",
  "agent_action_receipt_created",
  "agent_planning_continuation_queued",
]);

const AGENT_COMMAND_WORKFLOW_EVENTS = new Set([
  "agent_command_plan_applied",
  "agent_action_receipt_created",
]);

const AGENT_CANVAS_AUTHORING_EVENTS = new Set([
  "canvas_variation_draft_saved",
  "canvas_variation_draft_discarded",
  "canvas_variation_materialized",
  "canvas_layout_updated",
]);

export function runtimeEventPolicy(
  event: CanvasRuntimeEventV2,
): AgentCanvasRuntimeRefreshPolicy {
  const type = event.event_type;
  const editing = type.startsWith("editing_");
  const assetPublished = type === "asset_published";
  const runtimeEvent = (
    type.startsWith("execution_")
    || type.startsWith("node_")
    || type.startsWith("provider_")
    || type.startsWith("scheduler_")
  );
  const nodeChanged = new Set([
    "node_ready",
    "node_failed",
    "node_cancelled",
    "node_run_cancelled",
  ]).has(type);
  return {
    refreshRuntime:
      assetPublished
      || runtimeEvent,
    refreshWorkflow:
      editing
      || type === "proposal_selected"
      || AGENT_COMMAND_WORKFLOW_EVENTS.has(type)
      || AGENT_CANVAS_AUTHORING_EVENTS.has(type)
      || AUTHORING_EVENT_FRAGMENTS.some((fragment) => type.includes(fragment)),
    refreshAssets: assetPublished,
    refreshChat:
      AGENT_COMMAND_CHAT_EVENTS.has(type)
      || CHAT_EVENT_FRAGMENTS.some((fragment) => type.includes(fragment)),
    refreshNodeId: nodeChanged ? event.node_id : null,
    refreshEditingNodeId: editing ? event.node_id : null,
  };
}
