import type {
  MissingInputReport,
  NodeRunResult,
  ResolvedNodeInputs,
  UploadedAsset,
  WorkflowNode,
} from "../../../types";

export function getSystemResolvedContext(node?: WorkflowNode) {
  const value = node?.input_context?.system_resolved_input_context ?? node?.input_context?.resolved_input_context ?? node?.metadata?.resolved_input_context;
  return value && typeof value === "object" ? (value as Record<string, unknown>) : undefined;
}

export function getAssetArrayFromNodeContext(node: WorkflowNode | undefined, key: string) {
  const value = node?.input_context?.[key] ?? node?.metadata?.[key];
  return Array.isArray(value) ? value.filter((item): item is UploadedAsset => Boolean(item && typeof item === "object")) : [];
}

export function getAssetArrayFromRecord(record: Record<string, unknown> | undefined, key: string) {
  const value = record?.[key];
  return Array.isArray(value) ? value.filter((item): item is UploadedAsset => Boolean(item && typeof item === "object")) : [];
}

export function getRecordArrayFromNodeContext(node: WorkflowNode | undefined, key: string) {
  const value = node?.input_context?.[key] ?? node?.metadata?.[key];
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")) : [];
}

export function getNodeMissingInputs(node?: WorkflowNode): MissingInputReport[] {
  const value = node?.input_context?.missing_inputs ?? node?.metadata?.missing_inputs;
  return Array.isArray(value) ? value.filter((item): item is MissingInputReport => Boolean(item && typeof item === "object")) : [];
}

export function getStringArrayFromNode(node: WorkflowNode | undefined, key: string) {
  const value = node?.input_context?.[key] ?? node?.metadata?.[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function getStringFromRecord(record: Record<string, unknown> | undefined, key: string) {
  const value = record?.[key];
  return typeof value === "string" ? value : "";
}

export function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

export function resolvedInputsFromNodeRun(run: NodeRunResult): ResolvedNodeInputs {
  return {
    workflow_id: run.workflow_id,
    node_id: run.node_id,
    resolved_input_context: run.resolved_input_context,
    resolved_input_assets: run.resolved_input_assets,
    materialized_prompt: run.materialized_prompt,
    materialized_assets: run.materialized_assets,
    source_mappings: run.source_mappings,
    resolved_prompt_preview: run.resolved_prompt_preview,
    resolved_prompt_with_assets: run.resolved_prompt_with_assets,
    effective_prompt: run.effective_prompt,
    missing_inputs: run.missing_inputs,
    stale_upstream_nodes: run.stale_upstream_nodes,
    locked_upstream_nodes: run.locked_upstream_nodes,
    reference_policy: run.reference_policy,
    selected_provider: run.selected_provider,
    provider_strategy: run.provider_strategy,
    provider_attempts: run.provider_attempts,
    fallback_warnings: run.fallback_warnings,
    optimizer_metadata: run.optimizer_metadata,
    identity_certification: run.identity_certification,
  };
}

export function mergeResolvedInputContext(current: Record<string, unknown> | undefined, run: NodeRunResult) {
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
  ) return current;
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

export function buildNodePromptPatch(
  node: WorkflowNode,
  prompt: string,
  promptSource: string,
  metadataPatch: Record<string, unknown> = {},
): Partial<WorkflowNode> {
  return {
    prompt,
    override_prompt: prompt,
    content: {
      ...(node.content ?? {}),
      prompt,
    },
    input_context: {
      ...(node.input_context ?? {}),
      user_prompt: prompt,
    },
    metadata: {
      ...(node.metadata ?? {}),
      ...metadataPatch,
      prompt_source: promptSource,
      manual_prompt_dirty: true,
    },
  };
}

export function promptStringFromRun(run: NodeRunResult, key: string) {
  const runRecord = run as NodeRunResult & { input_context?: Record<string, unknown>; metadata?: Record<string, unknown> };
  return (
    getStringFromRecord(runRecord.resolved_input_context, key) ||
    getStringFromRecord(runRecord.output, key) ||
    getStringFromRecord(runRecord.input_context, key) ||
    getStringFromRecord(runRecord.metadata, key)
  );
}
