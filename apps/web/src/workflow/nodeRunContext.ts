import type { StoryboardVideoReadiness } from "./mediaSegments.ts";
import type { AssetLibraryReference, NodeRunRequest, ResolvedNodeInputs, WorkflowNode, WorkflowVariable } from "../types";
import { dedupeAssets } from "./assets.ts";

export type WorkflowNodeIdentity = {
  node_id: string;
  node_type: string;
};

export function buildNodeRunInputContext(
  node: WorkflowNode,
  variables: WorkflowVariable[],
  resolvedInputs?: ResolvedNodeInputs | null,
) {
  const variableValues = Object.fromEntries(variables.map((variable) => [variable.name, variable.value ?? null]));
  const resolvedContext = recordValue(resolvedInputs?.resolved_input_context);
  const materializedPrompt = stringValue(resolvedInputs?.materialized_prompt);

  return {
    ...(recordValue(node.content) ?? {}),
    ...(recordValue(node.input_context) ?? {}),
    ...(resolvedContext ?? {}),
    ...(materializedPrompt ? { materialized_prompt: materializedPrompt } : {}),
    ...(resolvedInputs?.resolved_prompt_preview ? { system_resolved_prompt_preview: resolvedInputs.resolved_prompt_preview } : {}),
    ...(resolvedInputs?.resolved_prompt_with_assets ? { system_resolved_prompt_with_assets: resolvedInputs.resolved_prompt_with_assets } : {}),
    config: node.config ?? {},
    variables: variableValues,
  };
}

export function buildOptimizeOnlyNodeRunRequest(
  node: WorkflowNode,
  workflowId: string | null | undefined,
  editablePrompt: string,
  variables: WorkflowVariable[],
  resolvedInputs?: ResolvedNodeInputs | null,
  assetReferences: AssetLibraryReference[] = [],
): NodeRunRequest {
  const inputContext = {
    ...buildNodeRunInputContext(node, variables, resolvedInputs),
    user_prompt: editablePrompt,
  };
  const identity = workflowNodeIdentity(node);

  return {
    workflow_id: workflowId,
    ...identity,
    input_context: inputContext,
    input_assets: node.input_assets,
    asset_references: assetReferences,
    override_prompt: editablePrompt,
    mode: "real",
    media_mode: "real",
    save_outputs: true,
    auto_resolve: Boolean(workflowId),
    optimize_only: true,
    run_downstream: false,
    force_rerun: true,
  };
}

export function workflowNodeIdentity(node: WorkflowNode): WorkflowNodeIdentity {
  return {
    node_id: node.id,
    node_type: getWorkflowNodeType(node),
  };
}

export function buildFinalCompositionInputContext(
  node: WorkflowNode,
  variables: WorkflowVariable[],
  resolvedInputs: ResolvedNodeInputs | null | undefined,
  storyboardReadiness: StoryboardVideoReadiness,
) {
  const baseContext = buildNodeRunInputContext(node, variables, resolvedInputs);
  const inputAssets = dedupeAssets([...(node.input_assets ?? []), ...storyboardReadiness.assets]);
  return {
    ...baseContext,
    storyboard_video_ready: storyboardReadiness.ready,
    storyboard_video_segments: storyboardReadiness.segments,
    storyboard_video_assets: storyboardReadiness.assets,
    storyboard_video_progress: storyboardReadiness.progress,
    input_assets: inputAssets,
  };
}

function getWorkflowNodeType(node: WorkflowNode) {
  return node.node_type ?? node.type ?? node.id;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}
