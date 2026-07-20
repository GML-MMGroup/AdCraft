import type { NodeRunResult, WorkflowNode } from "../types";
import { dedupeAssets } from "./assets.ts";
import { isStoryboardVideoNode, shouldPollStoryboardVideoMedia } from "./mediaSegments.ts";

type NodeRunLookup = Map<string, NodeRunResult> | NodeRunResult[];

const OUTPUT_TEXT_KEYS = [
  "text",
  "content",
  "summary",
  "description",
  "concept",
  "key_message",
  "showcase_focus",
  "presentation_strategy",
  "script",
  "hook",
  "body",
  "cta",
  "final_video_prompt",
  "generation_prompt",
  "music_style",
  "mood",
];

export function createNodeRunMap(runs: NodeRunResult[] = []) {
  const runMap = new Map<string, NodeRunResult>();
  for (const run of runs) {
    if (run.node_id) {
      runMap.set(run.node_id, run);
      continue;
    }
    if (run.node_type && !runMap.has(run.node_type)) runMap.set(run.node_type, run);
  }
  return runMap;
}

export function mergeWorkflowNodesWithRuns(nodes: WorkflowNode[], runs: NodeRunLookup) {
  const runMap = Array.isArray(runs) ? createNodeRunMap(runs) : runs;
  return nodes.map((node) => mergeWorkflowNodeWithRun(node, findNodeRunForWorkflowNode(node, runMap, nodes)));
}

export function mergeWorkflowNodeWithRun(node: WorkflowNode, run?: NodeRunResult): WorkflowNode {
  if (!run) return node;
  const keepActiveOutput = Boolean(run.has_active_output && isFailedNodeStatus(run.status));
  const keepReferenceFailureOutput = keepActiveOutput || isStrictReferenceFailure(run);
  const output = keepReferenceFailureOutput ? node.output : mergeNodeOutput(node, run);
  const outputAssets = run.output_assets?.length ? dedupeAssets([...run.output_assets, ...(node.output_assets ?? [])]) : dedupeAssets(node.output_assets ?? []);
  const inputAssets = run.input_assets?.length ? run.input_assets : run.materialized_assets?.length ? run.materialized_assets : node.input_assets;
  const inputContext = mergeMaterializedInputContext(node.input_context, run);
  const status = isStrictReferenceFailure(run) ? "failed" : isStoryboardVideoNode(node) && shouldPollStoryboardVideoMedia(run) ? "running" : run.status ?? node.status;

  return {
    ...node,
    status,
    ...(output ? { output } : {}),
    ...(inputContext ? { input_context: inputContext } : {}),
    ...(inputAssets ? { input_assets: inputAssets } : {}),
    ...(keepReferenceFailureOutput ? { output_assets: node.output_assets } : outputAssets.length ? { output_assets: outputAssets } : {}),
    stale_reason: run.error ?? node.stale_reason,
    metadata: {
      ...(node.metadata ?? {}),
      node_run_id: run.node_run_id,
      trace_path: run.trace_path,
      metadata_path: run.metadata_path,
      error: run.error,
      resolved_prompt_preview: run.resolved_prompt_preview,
      resolved_prompt_with_assets: run.resolved_prompt_with_assets,
      effective_prompt: run.effective_prompt,
      resolved_input_assets: run.resolved_input_assets,
      materialized_prompt: run.materialized_prompt,
      materialized_assets: run.materialized_assets,
      source_mappings: run.source_mappings,
      reference_policy: run.reference_policy,
      selected_provider: run.selected_provider,
      provider_strategy: run.provider_strategy,
      provider_attempts: run.provider_attempts,
      fallback_warnings: run.fallback_warnings,
      optimizer_metadata: run.optimizer_metadata,
      optimizer_agent: run.resolved_input_context?.optimizer_agent,
      selected_skill_ids: run.resolved_input_context?.selected_skill_ids,
      optimizer_warnings: run.resolved_input_context?.optimizer_warnings,
      quality_notes: run.resolved_input_context?.quality_notes ?? run.output?.quality_notes,
      identity_certification: run.identity_certification,
      missing_inputs: run.missing_inputs,
      stale_upstream_nodes: run.stale_upstream_nodes,
      locked_upstream_nodes: run.locked_upstream_nodes,
    },
  };
}

function mergeNodeOutput(node: WorkflowNode, run: NodeRunResult) {
  if (!hasRecordValue(run.output)) return node.output;
  if (!isStoryboardVideoNode(node) || !hasRecordValue(node.output)) return mergeOutputQualityFields(node.output, run.output);
  const nodeSegments = Array.isArray(node.output.segments) ? node.output.segments : null;
  if (!nodeSegments?.length) return mergeOutputQualityFields(node.output, run.output);
  return {
    ...mergeOutputQualityFields(node.output, run.output),
    segments: nodeSegments,
    ...(node.output.media_status ? { media_status: node.output.media_status } : {}),
    ...(node.output.all_segments_ready !== undefined ? { all_segments_ready: node.output.all_segments_ready } : {}),
    ...(node.output.segments_ready !== undefined ? { segments_ready: node.output.segments_ready } : {}),
  };
}

function mergeOutputQualityFields(current: WorkflowNode["output"], next: NodeRunResult["output"]) {
  if (!hasRecordValue(next)) return current;
  if (!hasRecordValue(current) || next.quality_summary !== undefined) return next;
  if (current.quality_summary === undefined) return next;
  return {
    ...next,
    quality_summary: current.quality_summary,
  };
}

export function workflowNodeContentPreview(node: WorkflowNode, run?: Pick<NodeRunResult, "output">) {
  const candidates = [
    textFromWorkflowOutput(run?.output),
    textFromWorkflowOutput(node.output),
    textFromWorkflowOutput(node.content),
    editablePromptForNode(node),
    optimizedPromptForNode(node),
    systemSuggestedPromptForNode(node),
    node.description,
  ];
  return candidates.find((value) => typeof value === "string" && value.trim())?.trim().slice(0, 180) ?? "";
}

export function editablePromptForNode(node: WorkflowNode) {
  const candidates = [
    node.input_context?.user_prompt,
    node.prompt,
    node.override_prompt,
    node.input_context?.system_suggested_prompt,
    node.content?.prompt,
    node.metadata?.user_prompt,
    node.metadata?.prompt,
  ];
  const prompt = candidates.find((value) => typeof value === "string" && value.trim());
  return typeof prompt === "string" ? prompt : "";
}

export function userPromptForNode(node: WorkflowNode) {
  return editablePromptForNode(node);
}

export function systemSuggestedPromptForNode(node: WorkflowNode) {
  const prompt = node.input_context?.system_suggested_prompt;
  return typeof prompt === "string" && prompt.trim() ? prompt : "";
}

export function optimizedPromptForNode(node: WorkflowNode) {
  const candidates = [
    node.input_context?.optimized_generation_prompt,
    node.metadata?.optimized_generation_prompt,
  ];
  const prompt = candidates.find((value) => typeof value === "string" && value.trim());
  return typeof prompt === "string" ? prompt : "";
}

export function providerPromptForNode(node: WorkflowNode) {
  const prompt = node.input_context?.provider_prompt;
  return typeof prompt === "string" && prompt.trim() ? prompt : "";
}

export function systemPromptForNode(node: WorkflowNode) {
  const candidates = [
    node.input_context?.system_suggested_prompt,
    node.input_context?.materialized_prompt,
    node.input_context?.system_resolved_prompt_with_assets,
    node.input_context?.system_resolved_prompt_preview,
    node.metadata?.materialized_prompt,
    node.metadata?.resolved_prompt_with_assets,
    node.metadata?.effective_prompt,
    node.metadata?.resolved_prompt_preview,
  ];
  const prompt = candidates.find((value) => typeof value === "string" && value.trim());
  return typeof prompt === "string" ? prompt : "";
}

export function materializedPromptForNode(node: WorkflowNode) {
  return systemPromptForNode(node);
}

export function textFromWorkflowOutput(value: unknown): string {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (typeof value !== "object" || Array.isArray(value)) return "";

  const record = value as Record<string, unknown>;
  for (const key of OUTPUT_TEXT_KEYS) {
    const text = stringValue(record[key]);
    if (text) return text;
  }

  const subtitleLines = record.subtitle_lines;
  if (Array.isArray(subtitleLines)) {
    const lines = subtitleLines.map((item) => stringValue(item)).filter(Boolean);
    if (lines.length) return lines.slice(0, 2).join(" ");
  }

  for (const key of ["characters", "scenes", "assets", "segments"]) {
    const text = textFromFirstArrayItem(record[key]);
    if (text) return text;
  }

  for (const value of Object.values(record)) {
    const text = stringValue(value);
    if (text) return text;
  }
  return "";
}

function mergeMaterializedInputContext(current: Record<string, unknown> | undefined, run: NodeRunResult) {
  const resolvedInputContext = run.resolved_input_context;
  const optimizerAgent = resolvedInputContext?.optimizer_agent;
  const optimizerSkillIds = resolvedInputContext?.selected_skill_ids;
  const optimizerWarnings = resolvedInputContext?.optimizer_warnings;
  const qualityNotes = resolvedInputContext?.quality_notes;
  const outputQualityNotes = run.output?.quality_notes;
  if (
    !resolvedInputContext &&
    !run.resolved_input_assets?.length &&
    !run.materialized_prompt &&
    !run.materialized_assets?.length &&
    !run.source_mappings?.length &&
    !run.reference_policy &&
    !run.selected_provider &&
    !run.provider_strategy &&
    !run.provider_attempts?.length &&
    !run.fallback_warnings?.length &&
    !run.optimizer_metadata &&
    !optimizerAgent &&
    !optimizerSkillIds &&
    !optimizerWarnings &&
    !qualityNotes &&
    !outputQualityNotes &&
    !run.identity_certification &&
    !run.resolved_prompt_preview &&
    !run.resolved_prompt_with_assets &&
    !run.missing_inputs?.length
  ) {
    return current;
  }

  return {
    ...(current ?? {}),
    ...(resolvedInputContext ? { system_resolved_input_context: resolvedInputContext, resolved_input_context: resolvedInputContext } : {}),
    ...(resolvedInputContext?.system_suggested_prompt ? { system_suggested_prompt: resolvedInputContext.system_suggested_prompt } : {}),
    ...(resolvedInputContext?.optimized_generation_prompt ? { optimized_generation_prompt: resolvedInputContext.optimized_generation_prompt } : {}),
    ...(resolvedInputContext?.provider_prompt ? { provider_prompt: resolvedInputContext.provider_prompt } : {}),
    ...(resolvedInputContext?.user_prompt ? { user_prompt: resolvedInputContext.user_prompt } : {}),
    ...(run.resolved_input_assets?.length ? { resolved_input_assets: run.resolved_input_assets } : {}),
    ...(run.materialized_prompt ? { materialized_prompt: run.materialized_prompt } : {}),
    ...(run.materialized_assets?.length ? { materialized_assets: run.materialized_assets } : {}),
    ...(run.source_mappings?.length ? { source_mappings: run.source_mappings } : {}),
    ...(run.reference_policy ? { reference_policy: run.reference_policy } : {}),
    ...(run.selected_provider ? { selected_provider: run.selected_provider } : {}),
    ...(run.provider_strategy ? { provider_strategy: run.provider_strategy } : {}),
    ...(run.provider_attempts?.length ? { provider_attempts: run.provider_attempts } : {}),
    ...(run.fallback_warnings?.length ? { fallback_warnings: run.fallback_warnings } : {}),
    ...(run.optimizer_metadata ? { optimizer_metadata: run.optimizer_metadata } : {}),
    ...(optimizerAgent ? { optimizer_agent: optimizerAgent } : {}),
    ...(optimizerSkillIds ? { selected_skill_ids: optimizerSkillIds } : {}),
    ...(optimizerWarnings ? { optimizer_warnings: optimizerWarnings } : {}),
    ...(qualityNotes ? { quality_notes: qualityNotes } : {}),
    ...(outputQualityNotes ? { output_quality_notes: outputQualityNotes } : {}),
    ...(run.identity_certification ? { identity_certification: run.identity_certification } : {}),
    ...(run.resolved_prompt_preview ? { system_resolved_prompt_preview: run.resolved_prompt_preview } : {}),
    ...(run.resolved_prompt_with_assets ? { system_resolved_prompt_with_assets: run.resolved_prompt_with_assets } : {}),
    ...(run.missing_inputs?.length ? { missing_inputs: run.missing_inputs } : {}),
    ...(run.stale_upstream_nodes?.length ? { stale_upstream_nodes: run.stale_upstream_nodes } : {}),
    ...(run.locked_upstream_nodes?.length ? { locked_upstream_nodes: run.locked_upstream_nodes } : {}),
  };
}

export function findNodeRunForWorkflowNode(node: WorkflowNode, runMap: Map<string, NodeRunResult>, allNodes: WorkflowNode[] = []) {
  const nodeType = node.node_type ?? node.type ?? node.id;
  const directRun = runMap.get(node.id);
  if (directRun?.node_id === node.id) return directRun;
  if (isLegacyTypeRunForNode(directRun, nodeType, allNodes)) return directRun;

  const typeRun = runMap.get(nodeType);
  if (typeRun !== directRun && isLegacyTypeRunForNode(typeRun, nodeType, allNodes)) return typeRun;
  return undefined;
}

function isLegacyTypeRunForNode(run: NodeRunResult | undefined, nodeType: string, allNodes: WorkflowNode[]) {
  if (!run || run.node_id || run.node_type !== nodeType) return false;
  return !hasDuplicateWorkflowNodeType(nodeType, allNodes);
}

function hasDuplicateWorkflowNodeType(nodeType: string, allNodes: WorkflowNode[]) {
  if (!allNodes.length) return false;
  let count = 0;
  for (const candidate of allNodes) {
    const candidateType = candidate.node_type ?? candidate.type ?? candidate.id;
    if (candidateType !== nodeType) continue;
    count += 1;
    if (count > 1) return true;
  }
  return false;
}

function hasRecordValue(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length);
}

function textFromFirstArrayItem(value: unknown) {
  if (!Array.isArray(value)) return "";
  for (const item of value) {
    const text = textFromWorkflowOutput(item);
    if (text) return text;
  }
  return "";
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function isFailedNodeStatus(status?: string | null) {
  if (!status) return false;
  return ["failed", "error", "cancelled", "canceled"].includes(status.toLowerCase());
}

function isStrictReferenceFailure(run?: NodeRunResult | null) {
  if (!run) return false;
  const policyErrors = referencePolicyItems(run.reference_policy?.errors).join(" ");
  const policyRejected = referencePolicyItems(run.reference_policy?.rejected_assets).join(" ");
  const providerStrategy = run.provider_strategy;
  const providerFailures = [
    providerStrategy?.reference_mode,
    ...providerStrategyItems(providerStrategy?.fallback_warnings),
    ...providerStrategyItems(providerStrategy?.rejected_providers),
    ...providerStrategyItems(providerStrategy?.provider_attempts),
    ...providerStrategyItems(run.provider_attempts),
    ...providerStrategyItems(run.fallback_warnings),
  ].filter(Boolean).join(" ");
  const message = [run.error, run.last_error, policyErrors, policyRejected, providerFailures].filter(Boolean).join(" ");
  return Boolean(
    (isFailedNodeStatus(run.status) || policyErrors || policyRejected || providerFailures) &&
      /(strict|reference|provider_capability_missing)/i.test(message),
  );
}

function providerStrategyItems(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string" && item.trim()) return [item.trim()];
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    const label = [
      stringValue(record.provider),
      stringValue(record.status),
      stringValue(record.error_code) || stringValue(record.code),
      stringValue(record.message) || stringValue(record.reason) || stringValue(record.error),
    ].filter(Boolean).join(" - ");
    return label ? [label] : [JSON.stringify(record)];
  });
}

function referencePolicyItems(value: unknown): string[] {
  if (!value) return [];
  if (Array.isArray(value)) return value.flatMap(referencePolicyItems).filter(Boolean);
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return [String(value)];
  if (typeof value !== "object") return [];
  const record = value as Record<string, unknown>;
  const label =
    stringValue(record.display_name) ||
    stringValue(record.filename) ||
    stringValue(record.name) ||
    stringValue(record.entity_id) ||
    stringValue(record.library_entity_id) ||
    stringValue(record.asset_id) ||
    stringValue(record.code) ||
    stringValue(record.message) ||
    stringValue(record.reason);
  return label ? [label] : [JSON.stringify(record)];
}
