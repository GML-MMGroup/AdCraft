import type {
  AssetBinding,
  AssetFlowDebug,
  IdentityCertificationIssue,
  IdentityCertificationMetadata,
  NodeRunResult,
  PromptOptimizerMetadata,
  ProviderAttempt,
  ProviderReferencePlan,
  ProviderStrategyDebug,
  ReferencePolicy,
  ResolvedNodeInputs,
  WorkflowNode,
} from "../../../types";

export function providerReferencePlanFromSources(
  run?: NodeRunResult | null,
  node?: WorkflowNode | null,
  resolvedInputs?: ResolvedNodeInputs | null,
  resolvedContext?: Record<string, unknown>,
): ProviderReferencePlan | null {
  const sources = workflowDebugSources(run, node, resolvedInputs, resolvedContext);
  for (const source of sources) {
    const nested =
      recordFromUnknown(source.provider_reference_plan) ??
      recordFromUnknown(source.providerReferencePlan) ??
      recordFromUnknown(source.reference_plan);
    if (nested) return nested as ProviderReferencePlan;
    if (
      source.accepted_reference_assets !== undefined ||
      source.transformed_reference_assets !== undefined ||
      source.prompt_only_reference_assets !== undefined ||
      source.rejected_reference_assets !== undefined
    ) {
      return source as ProviderReferencePlan;
    }
  }
  return null;
}

export function assetFlowDebugFromSources(
  run?: NodeRunResult | null,
  node?: WorkflowNode | null,
  resolvedInputs?: ResolvedNodeInputs | null,
  resolvedContext?: Record<string, unknown>,
): AssetFlowDebug | null {
  const sources = workflowDebugSources(run, node, resolvedInputs, resolvedContext);
  for (const source of sources) {
    const nested = recordFromUnknown(source.asset_flow_debug) ?? recordFromUnknown(source.assetFlowDebug);
    if (nested) return nested as AssetFlowDebug;
    if (source.failure_stage !== undefined || source.user_explainable_reason !== undefined || source.provider_attempt_count !== undefined) {
      return {
        failure_stage: stringFromUnknown(source.failure_stage) || undefined,
        user_explainable_reason: stringFromUnknown(source.user_explainable_reason) || null,
        provider_attempt_count: numberFromUnknown(source.provider_attempt_count),
        prompt_only_asset_count: numberFromUnknown(source.prompt_only_asset_count),
        rejected_reference_count: numberFromUnknown(source.rejected_reference_count),
      };
    }
  }
  return null;
}

export function assetBindingsFromSources(
  run?: NodeRunResult | null,
  node?: WorkflowNode | null,
  resolvedInputs?: ResolvedNodeInputs | null,
  resolvedContext?: Record<string, unknown>,
): AssetBinding[] {
  const sources = workflowDebugSources(run, node, resolvedInputs, resolvedContext);
  const bindings = sources.flatMap((source) => [
    ...assetBindingArrayFromUnknown(source.asset_bindings),
    ...assetBindingArrayFromUnknown(source.assetBindings),
    ...assetBindingArrayFromUnknown(source.bindings),
  ]);
  const seen = new Set<string>();
  return bindings.filter((binding, index) => {
    const keyParts = [
      binding.binding_id,
      binding.asset_id,
      binding.entity_id,
      binding.scope_type,
      binding.scope_id,
      binding.role,
    ].filter(Boolean).join(":");
    const key = keyParts || `binding-${index}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function assetBindingScopeLabel(scopeType?: string | null) {
  if (scopeType === "global") return "全局参考";
  if (scopeType === "node") return "当前节点参考";
  if (scopeType === "item") return "当前 item 参考";
  if (scopeType === "shot") return "当前 shot 参考";
  if (scopeType === "final_composition") return "Final composition reference";
  return scopeType || "reference scope";
}

export function failureStageUserMessage(stage?: string | null, reason?: string | null) {
  if (reason) return reason;
  if (stage === "prompt_optimizer") return "还没进入媒体生成：提示词优化阶段失败。";
  if (stage === "reference_policy") return "参考图约束不被支持，请调整或移除参考素材。";
  if (stage === "provider_selection") return "没有 provider 满足当前约束，请更换参考图或模型设置。";
  if (stage === "provider_call") return "provider 已调用但生成失败，旧预览会保留。";
  if (stage === "output_contract") return "模型返回成功但没有登记到资产，请查看后端输出契约。";
  if (stage === "persistence") return "资产持久化失败，旧预览会保留。";
  return "No asset flow failure reported.";
}

export function providerDebugFromSources(
  run?: NodeRunResult | null,
  node?: WorkflowNode | null,
  resolvedInputs?: ResolvedNodeInputs | null,
  resolvedContext?: Record<string, unknown>,
): ProviderStrategyDebug | null {
  const sources = [
    recordFromUnknown(run),
    recordFromUnknown(run?.provider_strategy),
    recordFromUnknown(node?.output),
    recordFromUnknown(node?.output?.provider_strategy),
    recordFromUnknown(node?.metadata),
    recordFromUnknown(node?.metadata?.provider_strategy),
    recordFromUnknown(resolvedInputs),
    recordFromUnknown(resolvedInputs?.provider_strategy),
    resolvedContext,
    recordFromUnknown(resolvedContext?.provider_strategy),
  ].filter((item): item is Record<string, unknown> => Boolean(item));
  if (!sources.length) return null;

  const attempts = firstProviderAttemptsFromSources(sources);
  const fallbackWarnings = firstProviderDebugItemsFromSources(sources, "fallback_warnings");
  const rejectedProviders = firstProviderDebugItemsFromSources(sources, "rejected_providers");
  const eligibleProviders = firstStringArrayFromSources(sources, "eligible_providers");
  const fallbackUsed = firstBooleanFromSources(sources, "fallback_used");
  const debug: ProviderStrategyDebug = {
    selected_provider: firstStringFromSources(sources, ["selected_provider", "provider"]) ?? null,
    ...(fallbackUsed !== undefined ? { fallback_used: fallbackUsed } : {}),
    selection_reason: firstStringFromSources(sources, ["selection_reason", "reason"]) ?? null,
    reference_mode: firstStringFromSources(sources, ["reference_mode"]) ?? null,
    ...(eligibleProviders.length ? { eligible_providers: eligibleProviders } : {}),
    ...(rejectedProviders.length ? { rejected_providers: rejectedProviders } : {}),
    ...(attempts.length ? { provider_attempts: attempts } : {}),
    ...(fallbackWarnings.length ? { fallback_warnings: fallbackWarnings } : {}),
  };
  const hasDebug =
    Boolean(debug.selected_provider || debug.selection_reason || debug.reference_mode) ||
    debug.fallback_used !== undefined ||
    Boolean(debug.eligible_providers?.length || debug.rejected_providers?.length || debug.provider_attempts?.length || debug.fallback_warnings?.length);
  return hasDebug ? debug : null;
}

export function providerDebugItems(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string" && item.trim()) return [item.trim()];
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    const label = [
      stringFromUnknown(record.provider),
      stringFromUnknown(record.status),
      stringFromUnknown(record.error_code) || stringFromUnknown(record.code),
      stringFromUnknown(record.message) || stringFromUnknown(record.reason) || stringFromUnknown(record.error),
    ].filter(Boolean).join(" - ");
    return label ? [label] : [JSON.stringify(record)];
  });
}

export function promptOptimizerMetadataForNode(
  node?: WorkflowNode | null,
  run?: NodeRunResult | null,
  resolvedInputs?: ResolvedNodeInputs | null,
): PromptOptimizerMetadata | null {
  const runMetadata = recordFromUnknown(run?.metadata);
  const nodeMetadata = recordFromUnknown(node?.metadata);
  const nodeInputContext = recordFromUnknown(node?.input_context);
  const nodeOutput = recordFromUnknown(node?.output);
  const resolvedContext = recordFromUnknown(resolvedInputs?.resolved_input_context ?? run?.resolved_input_context);
  const runOutput = recordFromUnknown(run?.output);
  const rawSources = [
    recordFromUnknown(resolvedInputs?.optimizer_metadata),
    recordFromUnknown(run?.optimizer_metadata),
    resolvedContext,
    nodeInputContext,
    nodeMetadata,
    runMetadata,
    nodeOutput,
    runOutput,
  ].filter((item): item is Record<string, unknown> => Boolean(item));
  const sources = rawSources.flatMap((source) => {
    const nested = recordFromUnknown(source.optimizer_metadata);
    return nested ? [source, nested] : [source];
  });
  if (!sources.length) return null;

  const optimizerSkillIds =
    firstStringArrayFromSources(sources, "selected_skill_ids").length
      ? firstStringArrayFromSources(sources, "selected_skill_ids")
      : firstStringArrayFromSources(sources, ["selected", "SkillIds"].join(""));
  const optimizerWarnings =
    firstProviderDebugItemsFromSources(sources, "optimizer_warnings").length
      ? firstProviderDebugItemsFromSources(sources, "optimizer_warnings")
      : firstProviderDebugItemsFromSources(sources, "optimizerWarnings");
  const qualityNotes = firstQualityNotesFromSources(sources);
  const metadata: PromptOptimizerMetadata = {
    optimizer_agent: firstStringFromSources(sources, ["optimizer_agent", "optimizerAgent"]) || null,
    ...(optimizerSkillIds.length ? { selected_skill_ids: optimizerSkillIds } : {}),
    ...(optimizerWarnings.length ? { optimizer_warnings: optimizerWarnings } : {}),
    ...(qualityNotes !== undefined ? { quality_notes: qualityNotes } : {}),
  };
  const hasMetadata =
    Boolean(metadata.optimizer_agent) ||
    Boolean(metadata.selected_skill_ids?.length) ||
    Boolean(metadata.optimizer_warnings?.length) ||
    metadata.quality_notes !== undefined;
  return hasMetadata ? metadata : null;
}

export function optimizerQualityNoteItems(value: PromptOptimizerMetadata["quality_notes"] | undefined): string[] {
  if (typeof value === "string" && value.trim()) return [value.trim()];
  if (Array.isArray(value)) return value.filter((item) => typeof item === "string" && Boolean(item.trim())).map((item) => item.trim());
  if (value && typeof value === "object") return [JSON.stringify(value)];
  return [];
}

export function providerFailureCode(
  run?: NodeRunResult | null,
  node?: WorkflowNode | null,
  referencePolicy?: ReferencePolicy | null,
  debug?: ProviderStrategyDebug | null,
) {
  const recordRun = run as (NodeRunResult & Record<string, unknown>) | null | undefined;
  const candidates = [
    stringFromUnknown(recordRun?.error_code),
    stringFromUnknown(run?.error),
    stringFromUnknown(run?.last_error),
    stringFromUnknown(node?.metadata?.error_code),
    stringFromUnknown(node?.metadata?.error),
    stringFromUnknown(node?.metadata?.last_error),
    stringFromUnknown(node?.output?.error_code),
    stringFromUnknown(node?.output?.error),
    providerDebugItems(debug?.fallback_warnings).join(" "),
    providerDebugItems(debug?.rejected_providers).join(" "),
    (debug?.provider_attempts ?? []).map((attempt) => [attempt.error_code, attempt.error].filter(Boolean).join(" ")).join(" "),
    referencePolicyItems(referencePolicy?.errors).join(" "),
    referencePolicyItems(referencePolicy?.warnings).join(" "),
  ].join(" ");
  const knownCodes = [
    "provider_strategy_all_attempts_failed",
    "provider_strategy_no_eligible_provider",
    "reference_policy_failed",
    "provider_capability_missing",
    "provider_reference_type_unsupported",
    "provider_timeout",
    "provider_exception",
    "strict_reference_not_supported",
    "identity_lock_not_supported",
  ];
  return knownCodes.find((code) => candidates.includes(code)) ?? "";
}

export function formatProviderFailureMessage(code?: string | null) {
  if (code === "provider_strategy_all_attempts_failed") return "All provider attempts failed. Current preview keeps the last successful output when available.";
  if (code === "provider_strategy_no_eligible_provider") return "当前没有可用模型能满足这次严格参考要求，请更换参考类型或移除参考图。";
  if (code === "provider_timeout") return "Provider request timed out.";
  if (code === "provider_exception") return "Provider request failed unexpectedly.";
  if (code === "reference_policy_failed") return "当前参考素材不符合后端参考策略，请调整或移除参考素材。";
  if (code === "provider_capability_missing") return "当前参考图类型不被模型严格参考能力支持，请更换参考类型或移除参考图。";
  if (code === "provider_reference_type_unsupported") return "当前参考图类型不被模型严格参考能力支持，请更换参考类型或移除参考图。";
  if (code === "strict_reference_not_supported") return "当前参考图类型不被模型严格参考能力支持，请更换参考类型或移除参考图。";
  if (code === "identity_lock_not_supported") return "当前模型无法满足角色一致性要求，请更换模型或移除角色参考。";
  return "";
}

export function identityCertificationForNodeRun(
  run?: NodeRunResult | null,
  node?: WorkflowNode | null,
  resolvedInputs?: ResolvedNodeInputs | null,
): IdentityCertificationMetadata | null {
  const runMetadata = recordFromUnknown(run?.metadata);
  const nodeMetadata = recordFromUnknown(node?.metadata);
  const nodeOutput = recordFromUnknown(node?.output);
  const sources = [
    run?.identity_certification,
    runMetadata?.identity_certification,
    resolvedInputs?.identity_certification,
    nodeMetadata?.identity_certification,
    nodeOutput?.identity_certification,
  ];
  for (const source of sources) {
    const certification = normalizeIdentityCertificationForView(source);
    if (certification) return certification;
  }
  return null;
}

export function identityCertificationStatusLabel(status?: string | null) {
  if (status === "certified") return "已使用认证身份能力。";
  if (status === "experimental") return "实验性身份能力，仅尽力保持一致。";
  if (status === "revoked") return "身份能力认证已被撤销。";
  return "身份一致性仅为 best effort。";
}

export function identityCertificationIssueMessage(issue: IdentityCertificationIssue) {
  const parts = [
    issue.code,
    issue.message,
    issue.entity_id ? `entity ${issue.entity_id}` : "",
    issue.asset_id ? `asset ${issue.asset_id}` : "",
    issue.semantic_type,
  ].filter(Boolean);
  return parts.join(" · ") || JSON.stringify(issue);
}

export function identityCertificationFailureCode(
  run?: NodeRunResult | null,
  node?: WorkflowNode | null,
  certification?: IdentityCertificationMetadata | null,
) {
  const recordRun = run as (NodeRunResult & Record<string, unknown>) | null | undefined;
  const issueMessages = [...(certification?.warnings ?? []), ...(certification?.errors ?? [])]
    .map(identityCertificationIssueMessage)
    .join(" ");
  const candidates = [
    stringFromUnknown(recordRun?.error_code),
    stringFromUnknown(run?.error),
    stringFromUnknown(run?.last_error),
    stringFromUnknown(node?.metadata?.error_code),
    stringFromUnknown(node?.metadata?.error),
    stringFromUnknown(node?.metadata?.last_error),
    stringFromUnknown(node?.output?.error_code),
    stringFromUnknown(node?.output?.error),
    issueMessages,
  ].join(" ");
  const knownCodes = [
    "identity_certification_required",
    "identity_certification_revoked",
    "identity_lock_not_supported",
    "provider_capability_missing",
    "provider_strategy_no_eligible_provider",
    "strict_reference_not_supported",
  ];
  return knownCodes.find((code) => candidates.includes(code)) ?? "";
}

export function formatIdentityCertificationFailureMessage(code?: string | null) {
  if (code === "identity_certification_required") return "当前严格身份参考需要认证 provider。";
  if (code === "identity_certification_revoked") return "该身份认证能力已被撤销。";
  if (code === "identity_lock_not_supported") return "当前模型无法满足角色一致性要求，请更换模型或移除角色参考。";
  if (code === "provider_capability_missing") return "当前模型不支持严格参考这类素材，请更换模型或移除参考素材。";
  if (code === "provider_strategy_no_eligible_provider") return "当前身份参考没有可用 provider。";
  if (code === "strict_reference_not_supported") return "当前 provider 不支持严格身份参考。";
  return "";
}

export function identityCertificationDebugFlags(
  run?: NodeRunResult | null,
  node?: WorkflowNode | null,
  certification?: IdentityCertificationMetadata | null,
) {
  const sources = [
    recordFromUnknown(certification),
    recordFromUnknown(run),
    recordFromUnknown(run?.metadata),
    recordFromUnknown(node?.input_context),
    recordFromUnknown(node?.metadata),
    recordFromUnknown(node?.output),
  ].filter((item): item is Record<string, unknown> => Boolean(item));
  const flags: string[] = [];
  if (sources.some((source) => source.lock_identity === true)) flags.push("lock_identity");
  const referenceMode = firstStringFromSources(sources, ["reference_mode", "mode"]);
  if (referenceMode) flags.push(`reference_mode: ${referenceMode}`);
  return flags;
}

function workflowDebugSources(
  run?: NodeRunResult | null,
  node?: WorkflowNode | null,
  resolvedInputs?: ResolvedNodeInputs | null,
  resolvedContext?: Record<string, unknown>,
) {
  return [
    recordFromUnknown(run),
    recordFromUnknown(run?.metadata),
    recordFromUnknown(run?.output),
    recordFromUnknown(node),
    recordFromUnknown(node?.metadata),
    recordFromUnknown(node?.output),
    recordFromUnknown(node?.input_context),
    recordFromUnknown(resolvedInputs),
    recordFromUnknown(resolvedInputs?.resolved_input_context),
    resolvedContext,
  ].filter((item): item is Record<string, unknown> => Boolean(item));
}

function assetBindingArrayFromUnknown(value: unknown): AssetBinding[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => recordFromUnknown(item))
    .filter((item): item is AssetBinding => Boolean(item));
}

function firstStringFromSources(sources: Record<string, unknown>[], keys: string[]) {
  for (const source of sources) {
    for (const key of keys) {
      const text = stringFromUnknown(source[key]);
      if (text) return text;
    }
  }
  return "";
}

function firstBooleanFromSources(sources: Record<string, unknown>[], key: string) {
  for (const source of sources) {
    if (typeof source[key] === "boolean") return source[key] as boolean;
  }
  return undefined;
}

function firstStringArrayFromSources(sources: Record<string, unknown>[], key: string) {
  for (const source of sources) {
    const value = source[key];
    if (!Array.isArray(value)) continue;
    const items = value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()));
    if (items.length) return items;
  }
  return [];
}

function firstProviderAttemptsFromSources(sources: Record<string, unknown>[]) {
  for (const source of sources) {
    const attempts = normalizeProviderAttemptsForDebug(source.provider_attempts);
    if (attempts.length) return attempts;
  }
  return [];
}

function normalizeProviderAttemptsForDebug(value: unknown): ProviderAttempt[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item, index): ProviderAttempt | null => {
      if (!item || typeof item !== "object" || Array.isArray(item)) return null;
      const record = item as Record<string, unknown>;
      return {
        provider: stringFromUnknown(record.provider) || stringFromUnknown(record.provider_name) || stringFromUnknown(record.name) || `provider-${index + 1}`,
        status: stringFromUnknown(record.status) || "skipped",
        error_code: stringFromUnknown(record.error_code) || stringFromUnknown(record.code) || null,
        error: stringFromUnknown(record.error) || stringFromUnknown(record.message) || stringFromUnknown(record.reason) || null,
        duration_ms: typeof record.duration_ms === "number" && Number.isFinite(record.duration_ms) ? record.duration_ms : null,
      };
    })
    .filter((item): item is ProviderAttempt => Boolean(item));
}

function firstProviderDebugItemsFromSources(sources: Record<string, unknown>[], key: string) {
  for (const source of sources) {
    const items = providerDebugItems(source[key]);
    if (items.length) return items;
  }
  return [];
}

function firstQualityNotesFromSources(sources: Record<string, unknown>[]): PromptOptimizerMetadata["quality_notes"] | undefined {
  for (const source of sources) {
    for (const key of ["quality_notes", "qualityNotes"]) {
      const notes = qualityNotesFromUnknown(source[key]);
      if (notes !== undefined) return notes;
    }
  }
  return undefined;
}

function qualityNotesFromUnknown(value: unknown): PromptOptimizerMetadata["quality_notes"] | undefined {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (Array.isArray(value)) {
    const items = value.flatMap((item) => {
      if (typeof item === "string" && item.trim()) return [item.trim()];
      if (item && typeof item === "object" && !Array.isArray(item)) return [JSON.stringify(item)];
      return [];
    });
    return items.length ? items : undefined;
  }
  if (value && typeof value === "object") return value as Record<string, unknown>;
  return undefined;
}

function normalizeIdentityCertificationForView(value: unknown): IdentityCertificationMetadata | null {
  const record = recordFromUnknown(value);
  if (!record || !Object.keys(record).length) return null;
  const status = stringFromUnknown(record.status) || "uncertified";
  return {
    ...(record as IdentityCertificationMetadata),
    status,
    ...(stringFromUnknown(record.mode) ? { mode: stringFromUnknown(record.mode) } : {}),
    provider: stringFromUnknown(record.provider) || stringFromUnknown(record.selected_provider) || null,
    model_id: stringFromUnknown(record.model_id) || stringFromUnknown(record.model) || null,
    reference_semantic_types: identityCertificationStringItems(record.reference_semantic_types, ["semantic_type", "type"]),
    certification_ids: identityCertificationStringItems(record.certification_ids, ["certification_id", "certificate_id", "id"]),
    warnings: identityCertificationIssues(record.warnings),
    errors: identityCertificationIssues(record.errors),
  };
}

function identityCertificationStringItems(value: unknown, objectKeys: string[]) {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string" && item.trim()) return [item.trim()];
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    for (const key of objectKeys) {
      const text = stringFromUnknown(record[key]);
      if (text) return [text];
    }
    return [];
  });
}

function identityCertificationIssues(value: unknown): IdentityCertificationIssue[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): IdentityCertificationIssue[] => {
    if (typeof item === "string" && item.trim()) return [{ message: item.trim() }];
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    const issue: IdentityCertificationIssue = { ...(record as IdentityCertificationIssue) };
    const code = stringFromUnknown(record.code) || stringFromUnknown(record.error_code);
    const message = stringFromUnknown(record.message) || stringFromUnknown(record.reason) || stringFromUnknown(record.error);
    const assetId = stringFromUnknown(record.asset_id);
    const entityId = stringFromUnknown(record.entity_id) || stringFromUnknown(record.library_entity_id);
    const semanticType = stringFromUnknown(record.semantic_type);
    if (code) issue.code = code;
    if (message) issue.message = message;
    if (assetId) issue.asset_id = assetId;
    if (entityId) issue.entity_id = entityId;
    if (semanticType) issue.semantic_type = semanticType;
    return [issue];
  });
}

function referencePolicyItems(value: unknown): string[] {
  if (!value) return [];
  if (Array.isArray(value)) return value.flatMap(referencePolicyItems).filter(Boolean);
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return [String(value)];
  if (typeof value !== "object") return [];
  const record = value as Record<string, unknown>;
  const label =
    stringFromUnknown(record.display_name) ||
    stringFromUnknown(record.filename) ||
    stringFromUnknown(record.name) ||
    stringFromUnknown(record.entity_id) ||
    stringFromUnknown(record.library_entity_id) ||
    stringFromUnknown(record.asset_id) ||
    stringFromUnknown(record.code) ||
    stringFromUnknown(record.message) ||
    stringFromUnknown(record.reason);
  return label ? [label] : [JSON.stringify(record)];
}

function recordFromUnknown(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function numberFromUnknown(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
