import { useEffect, useMemo, useRef, useState } from "react";
import { NodeAttachmentPreview } from "../components/NodeAttachmentPreview.tsx";
import type { MediaLightboxState } from "../page/workflowPageTypes.ts";
import type {
  AssetBinding,
  AssetFlowDebug,
  IdentityCertificationIssue,
  IdentityCertificationMetadata,
  MissingInputReport,
  NodeRunResult,
  PromptOptimizerMetadata,
  ProviderAttempt,
  ProviderReferencePlan,
  ProviderStrategyDebug,
  QualityReviewIssue,
  QualityReviewStatus,
  QualityReviewSummary,
  ReferencePolicy,
  UploadedAsset,
  WorkflowNode,
} from "../../../types";

const DEBUG_LIST_PREVIEW_LIMIT = 12;

function recordFromUnknown(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function stringArrayFromUnknown(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : [];
}

function statusClass(value: string) {
  return value.replace(/[^a-z0-9_-]/gi, "-").toLowerCase();
}

function formatJson(value: unknown) {
  const text = JSON.stringify(value, null, 2);
  return text.length > 1400 ? text.slice(0, 1400) + "\n..." : text;
}

function referencePolicyItems(value: unknown): string[] {
  if (typeof value === "string" && value.trim()) return [value.trim()];
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    if (typeof item === "string") return item.trim();
    const record = recordFromUnknown(item);
    return stringFromUnknown(record?.display_name) || stringFromUnknown(record?.asset_id) || stringFromUnknown(record?.entity_id) || stringFromUnknown(record?.message) || stringFromUnknown(record?.code) || JSON.stringify(item);
  }).filter(Boolean);
}

function providerDebugItems(value: unknown): string[] {
  if (typeof value === "string" && value.trim()) return [value.trim()];
  if (!Array.isArray(value)) return [];
  return value.map((item) => typeof item === "string" ? item.trim() : JSON.stringify(item)).filter(Boolean);
}

function optimizerQualityNoteItems(value: PromptOptimizerMetadata["quality_notes"] | undefined): string[] {
  if (typeof value === "string" && value.trim()) return [value.trim()];
  if (Array.isArray(value)) return value.map((item) => typeof item === "string" ? item.trim() : JSON.stringify(item)).filter(Boolean);
  if (value && typeof value === "object") return [JSON.stringify(value)];
  return [];
}

function formatAssetLibrarySourceLabel(mapping: Record<string, unknown>) {
  const name = stringFromUnknown(mapping.display_name) || stringFromUnknown(mapping.entity_display_name) || stringFromUnknown(mapping.name) || "Asset Library entity";
  const entityId = stringFromUnknown(mapping.entity_id) || stringFromUnknown(mapping.library_entity_id) || stringFromUnknown(mapping.source_entity_id);
  const role = stringFromUnknown(mapping.role) || stringFromUnknown(mapping.entity_type);
  const targetNode = stringFromUnknown(mapping.target_node_id) || stringFromUnknown(mapping.node_id);
  const targetEntity = stringFromUnknown(mapping.target_entity_id);
  return [name, entityId, role ? "role " + role : "", targetNode ? "node " + targetNode : "", targetEntity ? "target " + targetEntity : ""].filter(Boolean).join(" · ");
}

function formatSourceMappingLabel(mapping: Record<string, unknown>) {
  const source = stringFromUnknown(mapping.reference_source) || stringFromUnknown(mapping.source_type) || stringFromUnknown(mapping.type) || "source";
  const name = stringFromUnknown(mapping.display_name) || stringFromUnknown(mapping.entity_display_name) || stringFromUnknown(mapping.name);
  const entityId = stringFromUnknown(mapping.entity_id) || stringFromUnknown(mapping.library_entity_id) || stringFromUnknown(mapping.source_entity_id);
  const assetId = stringFromUnknown(mapping.asset_id);
  const role = stringFromUnknown(mapping.role) || stringFromUnknown(mapping.entity_type);
  const targetNode = stringFromUnknown(mapping.target_node_id) || stringFromUnknown(mapping.node_id);
  return [source, name, entityId || assetId, role ? "role " + role : "", targetNode ? "node " + targetNode : ""].filter(Boolean).join(" · ");
}

function formatReferencePolicySummary(policy?: ReferencePolicy | null) {
  if (!policy) return "";
  const accepted = referencePolicyItems(policy.accepted_assets).length;
  const rejected = referencePolicyItems(policy.rejected_assets).length;
  const promptOnly = referencePolicyItems(policy.prompt_only_assets).length;
  return [accepted ? accepted + " accepted" : "", promptOnly ? promptOnly + " prompt-only" : "", rejected ? rejected + " rejected" : ""].filter(Boolean).join(" · ");
}

function failureStageUserMessage(stage?: string | null, reason?: string | null) {
  if (reason) return reason;
  if (!stage || stage === "none") return "No asset flow failure reported.";
  if (stage === "provider_selection") return "没有 provider 满足当前约束，请更换参考图或模型设置。";
  if (stage === "provider_call") return "provider 已调用但生成失败，旧预览会保留。";
  if (stage === "output_contract") return "模型返回成功但没有登记到资产，请查看后端输出契约。";
  if (stage === "persistence") return "资产持久化失败，旧预览会保留。";
  return "No asset flow failure reported.";
}

function assetBindingScopeLabel(scopeType?: string | null) {
  if (scopeType === "workflow") return "workflow";
  if (scopeType === "node") return "node";
  if (scopeType === "item") return "item";
  if (scopeType === "slot") return "slot";
  return scopeType || "scope";
}

function normalizedQualityStatus(status?: QualityReviewStatus | string | null): QualityReviewStatus {
  const value = typeof status === "string" && status.trim() ? status.trim().toLowerCase() : "unchecked";
  if (value === "ok" || value === "success" || value === "succeeded") return "passed";
  if (value === "warn") return "warning";
  if (value === "error") return "failed";
  return value as QualityReviewStatus;
}

function qualityStatusLabel(status?: QualityReviewStatus | string | null) {
  const normalized = normalizedQualityStatus(status);
  if (normalized === "failed") return "Needs review";
  if (normalized === "warning") return "Warning";
  if (normalized === "passed") return "Passed";
  if (normalized === "unavailable") return "Unavailable";
  return "Not reviewed yet";
}

function qualityStatusClass(status?: QualityReviewStatus | string | null) {
  return statusClass(normalizedQualityStatus(status));
}

function qualityIssuesForAsset(asset: UploadedAsset): QualityReviewIssue[] {
  return Array.isArray(asset.quality_issues) ? asset.quality_issues : [];
}

function qualityWarningsForAsset(asset: UploadedAsset): QualityReviewIssue[] {
  return Array.isArray(asset.quality_warnings) ? asset.quality_warnings : [];
}

function qualityIssueMessage(issue: QualityReviewIssue) {
  return stringFromUnknown(issue.message) || stringFromUnknown(issue.code) || JSON.stringify(issue);
}

function providerFailureCode(run?: NodeRunResult | null, node?: WorkflowNode | null, policy?: ReferencePolicy | null, debug?: ProviderStrategyDebug | null) {
  const runMetadata = recordFromUnknown(run?.metadata);
  const nodeOutput = recordFromUnknown(node?.output);
  const debugRecord = recordFromUnknown(debug);
  const policyRecord = recordFromUnknown(policy);
  return stringFromUnknown(debugRecord?.failure_code) || stringFromUnknown(runMetadata?.failure_code) || stringFromUnknown(nodeOutput?.failure_code) || stringFromUnknown(policyRecord?.error_code);
}

function formatProviderFailureMessage(code?: string | null) {
  if (!code) return "";
  if (code === "provider_strategy_all_attempts_failed") return "All provider attempts failed. Current preview keeps the last successful output when available.";
  if (code === "provider_strategy_no_eligible_provider") return "当前没有可用模型能满足这次严格参考要求，请更换参考类型或移除参考图。";
  if (code === "provider_timeout") return "Provider request timed out.";
  if (code === "provider_exception") return "Provider request failed unexpectedly.";
  return code;
}

function identityCertificationFailureCode(run?: NodeRunResult | null, node?: WorkflowNode | null, certification?: IdentityCertificationMetadata | null) {
  const runMetadata = recordFromUnknown(run?.metadata);
  const nodeOutput = recordFromUnknown(node?.output);
  return stringFromUnknown(certification?.failure_code) || stringFromUnknown(runMetadata?.identity_failure_code) || stringFromUnknown(nodeOutput?.identity_failure_code);
}

function formatIdentityCertificationFailureMessage(code?: string | null) {
  if (!code) return "";
  if (code === "identity_lock_not_supported") return "当前模型无法满足角色一致性要求，请更换模型或移除角色参考。";
  return code;
}

function identityCertificationDebugFlags(run?: NodeRunResult | null, node?: WorkflowNode | null, certification?: IdentityCertificationMetadata | null) {
  return stringArrayFromUnknown(certification?.debug_flags)
    .concat(stringArrayFromUnknown(recordFromUnknown(run?.metadata)?.identity_debug_flags))
    .concat(stringArrayFromUnknown(recordFromUnknown(node?.metadata)?.identity_debug_flags));
}

function identityCertificationStatusLabel(status?: string | null) {
  if (status === "certified") return "Identity certified";
  if (status === "failed") return "Identity failed";
  if (status === "warning") return "Identity warning";
  return "Identity not certified";
}

function identityCertificationIssueMessage(issue: IdentityCertificationIssue) {
  return stringFromUnknown(issue.message) || stringFromUnknown(issue.code) || JSON.stringify(issue);
}

function hasActiveOutputFailure(run?: NodeRunResult | null, node?: WorkflowNode | null) {
  const status = String(run?.status ?? node?.status ?? "").toLowerCase();
  return status === "failed" || status === "error";
}
export function AssetLibrarySources({ mappings }: { mappings: Array<Record<string, unknown>> }) {
  return (
    <div className="asset-library-source-panel">
      <strong>Asset Library Sources</strong>
      <div className="asset-library-source-list">
        {mappings.map((mapping, index) => (
          <span key={[mapping.entity_id ?? mapping.library_entity_id ?? "library", index].join("-")}>
            {formatAssetLibrarySourceLabel(mapping)}
          </span>
        ))}
      </div>
    </div>
  );
}

export function SourceMappingsPanel({ mappings }: { mappings: Array<Record<string, unknown>> }) {
  const visibleMappings = mappings.slice(0, DEBUG_LIST_PREVIEW_LIMIT);
  return (
    <div className="asset-library-source-panel">
      <strong>Source mappings</strong>
      <div className="asset-library-source-list">
        {visibleMappings.map((mapping, index) => (
          <span key={[mapping.source_type ?? mapping.type ?? "source", mapping.entity_id ?? mapping.asset_id ?? index].join("-")}>
            {formatSourceMappingLabel(mapping)}
          </span>
        ))}
        {mappings.length > visibleMappings.length ? <span className="debug-list-more">+{mappings.length - visibleMappings.length} more mappings</span> : null}
      </div>
    </div>
  );
}

export function ReferencedInputAssets({ assets }: { assets: UploadedAsset[] }) {
  const visibleAssets = assets.slice(0, DEBUG_LIST_PREVIEW_LIMIT);
  return (
    <div className="asset-library-source-panel">
      <strong>Referenced input assets</strong>
      <div className="library-reference-chips">
        {visibleAssets.map((asset) => (
          <span key={asset.asset_id} className="library-reference-chip">
            <span>{asset.filename}</span>
            <em>{asset.asset_type} · {asset.semantic_type ?? asset.asset_role}</em>
          </span>
        ))}
        {assets.length > visibleAssets.length ? <span className="debug-list-more">+{assets.length - visibleAssets.length} more assets</span> : null}
      </div>
    </div>
  );
}

export function ReferencePolicyPanel({ policy }: { policy: ReferencePolicy }) {
  const accepted_assets = referencePolicyItems(policy.accepted_assets);
  const prompt_only_assets = referencePolicyItems(policy.prompt_only_assets);
  const rejected_assets = referencePolicyItems(policy.rejected_assets);
  const warnings = referencePolicyItems(policy.warnings);
  const errors = referencePolicyItems(policy.errors);
  const rows = [
    ["accepted_assets", accepted_assets],
    ["prompt_only_assets", prompt_only_assets],
    ["rejected_assets", rejected_assets],
    ["warnings", warnings],
    ["errors", errors],
  ] as const;

  return (
    <div className="reference-policy-panel">
      <strong>Reference Policy</strong>
      <span>{formatReferencePolicySummary(policy) || "No backend reference policy decisions returned."}</span>
      <div className="reference-policy-grid">
        {rows.map(([label, items]) => (
          <div key={label} className={items.length ? "has-items" : ""}>
            <em>{label}</em>
            {items.length ? items.map((item, index) => <span key={`${label}-${index}`}>{item}</span>) : <span>None</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ProviderReferencePlanPanel({ plan }: { plan: ProviderReferencePlan }) {
  const accepted = referencePolicyItems(plan.accepted_reference_assets);
  const transformed = referencePolicyItems(plan.transformed_reference_assets);
  const promptOnly = referencePolicyItems(plan.prompt_only_reference_assets);
  const rejected = referencePolicyItems(plan.rejected_reference_assets);
  const warnings = referencePolicyItems(plan.warnings);
  const errors = referencePolicyItems(plan.errors);
  const rows = [
    ["accepted_reference_assets", accepted],
    ["transformed_reference_assets", transformed],
    ["prompt_only_reference_assets", promptOnly, "已作为提示词上下文使用"],
    ["rejected_reference_assets", rejected],
    ["warnings", warnings],
    ["errors", errors],
  ] as const;

  return (
    <div className="provider-reference-plan-panel">
      <strong>Provider Reference Plan</strong>
      <div className="provider-strategy-summary">
        {plan.provider ? (
          <span>
            <em>Provider</em>
            <b>{plan.provider}</b>
          </span>
        ) : null}
        {plan.node_type ? (
          <span>
            <em>Node type</em>
            <b>{plan.node_type}</b>
          </span>
        ) : null}
        {plan.media_type ? (
          <span>
            <em>Media type</em>
            <b>{plan.media_type}</b>
          </span>
        ) : null}
      </div>
      <div className="reference-policy-grid">
        {rows.map(([label, items, hint]) => (
          <div key={label} className={items.length ? "has-items" : ""}>
            <em>{label}</em>
            {hint && items.length ? <small>{hint}</small> : null}
            {items.length ? items.map((item, index) => <span key={`${label}-${index}`}>{item}</span>) : <span>None</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

export function AssetFlowDebugPanel({ debug }: { debug: AssetFlowDebug }) {
  const failureStage = stringFromUnknown(debug.failure_stage) || "none";
  const reason = stringFromUnknown(debug.user_explainable_reason);
  const warnings = referencePolicyItems(debug.warnings);
  const counters = [
    ["input_reference_count", debug.input_reference_count],
    ["display_asset_count", debug.display_asset_count],
    ["prompt_context_asset_count", debug.prompt_context_asset_count],
    ["provider_reference_asset_count", debug.provider_reference_asset_count],
    ["prompt_only_asset_count", debug.prompt_only_asset_count],
    ["rejected_reference_count", debug.rejected_reference_count],
    ["provider_attempt_count", debug.provider_attempt_count],
  ] as const;

  return (
    <div className="asset-flow-debug-panel">
      <strong>Asset Flow Debug</strong>
      <span className="provider-strategy-error">{failureStageUserMessage(failureStage, reason)}</span>
      <div className="provider-strategy-summary">
        <span>
          <em>failure_stage</em>
          <b>{failureStage}</b>
        </span>
        {reason ? (
          <span>
            <em>user_explainable_reason</em>
            <b>{reason}</b>
          </span>
        ) : null}
        {debug.selected_provider ? (
          <span>
            <em>selected_provider</em>
            <b>{debug.selected_provider}</b>
          </span>
        ) : null}
      </div>
      <div className="reference-policy-grid">
        {counters.map(([label, value]) => (
          value !== undefined && value !== null ? (
            <div key={label} className="has-items">
              <em>{label}</em>
              <span>{String(value)}</span>
            </div>
          ) : null
        ))}
      </div>
      {warnings.length ? (
        <div className="provider-debug-list">
          <em>Warnings</em>
          {warnings.map((item, index) => <span key={`asset-flow-warning-${index}`}>{item}</span>)}
        </div>
      ) : null}
    </div>
  );
}

export function AssetBindingScopePanel({ bindings }: { bindings: AssetBinding[] }) {
  const visibleBindings = bindings.slice(0, DEBUG_LIST_PREVIEW_LIMIT);
  return (
    <div className="asset-binding-scope-panel">
      <strong>Asset Binding Scope</strong>
      <div className="asset-binding-list">
        {visibleBindings.map((binding, index) => (
          <span key={[binding.binding_id ?? binding.asset_id ?? binding.entity_id ?? "binding", index].join("-")}>
            <b>{assetBindingScopeLabel(binding.scope_type)}</b>
            <em>{[binding.role, binding.reference_mode, binding.use_as_prompt ? "prompt context" : "", binding.lock_identity ? "consistency enabled" : ""].filter(Boolean).join(" · ") || "reference"}</em>
            <small>{[binding.scope_id ? `scope ${binding.scope_id}` : "", binding.entity_id ? `entity ${binding.entity_id}` : "", binding.asset_id ? `asset ${binding.asset_id}` : ""].filter(Boolean).join(" · ")}</small>
          </span>
        ))}
        {bindings.length > visibleBindings.length ? <span className="debug-list-more">+{bindings.length - visibleBindings.length} more bindings</span> : null}
      </div>
    </div>
  );
}

export function QualityReviewPanel({
  summary,
  assets,
  reviewing,
  canReview,
  onReview,
}: {
  summary?: QualityReviewSummary | null;
  assets: UploadedAsset[];
  reviewing: boolean;
  canReview: boolean;
  onReview: () => void;
}) {
  const status = normalizedQualityStatus(summary?.status ?? summary?.quality_status);
  const issues = [...(summary?.issues ?? []), ...(summary?.asset_issues ?? [])];
  const warnings = summary?.warnings ?? [];
  const assetsWithQuality = assets.filter((asset) => normalizedQualityStatus(asset.quality_status) !== "unchecked" || qualityIssuesForAsset(asset).length || qualityWarningsForAsset(asset).length);
  const checkedCount = summary?.checked_asset_count ?? summary?.asset_count ?? assetsWithQuality.length;
  const warningCount = summary?.warning_count ?? warnings.length + assetsWithQuality.filter((asset) => normalizedQualityStatus(asset.quality_status) === "warning").length;
  const failedCount = summary?.failed_count ?? assetsWithQuality.filter((asset) => normalizedQualityStatus(asset.quality_status) === "failed").length;
  const reviewer = summary?.reviewer ?? summary?.method ?? null;

  return (
    <div className="quality-review-panel">
      <div className="quality-review-header">
        <strong>Quality Review</strong>
        <span className={`quality-review-status status-${qualityStatusClass(status)}`}>{qualityStatusLabel(status)}</span>
        <button className="small-action" type="button" disabled={!canReview || reviewing} onClick={onReview}>
          {reviewing ? "Reviewing..." : "Review quality"}
        </button>
      </div>
      <div className="quality-review-summary">
        {reviewer ? (
          <span>
            <em>Reviewer</em>
            <b>{reviewer}</b>
          </span>
        ) : null}
        <span>
          <em>Checked assets</em>
          <b>{checkedCount ?? 0}</b>
        </span>
        <span>
          <em>Warnings</em>
          <b>{warningCount ?? 0}</b>
        </span>
        <span>
          <em>Failed</em>
          <b>{failedCount ?? 0}</b>
        </span>
        {summary?.quality_score !== undefined && summary.quality_score !== null ? (
          <span>
            <em>Score</em>
            <b>{summary.quality_score}</b>
          </span>
        ) : null}
      </div>
      {!summary ? <span className="empty-output">Not reviewed yet.</span> : null}
      {issues.length || warnings.length ? (
        <div className="quality-review-issues">
          {issues.slice(0, DEBUG_LIST_PREVIEW_LIMIT).map((issue, index) => <span key={`quality-issue-${index}`}>Issue: {qualityIssueMessage(issue)}</span>)}
          {warnings.slice(0, DEBUG_LIST_PREVIEW_LIMIT).map((issue, index) => <span key={`quality-warning-${index}`}>Warning: {qualityIssueMessage(issue)}</span>)}
        </div>
      ) : null}
      {assetsWithQuality.length ? (
        <div className="quality-review-asset-list">
          {assetsWithQuality.slice(0, DEBUG_LIST_PREVIEW_LIMIT).map((asset) => (
            <span key={asset.asset_id}>
              <b>{asset.filename}</b>
              <em>{qualityStatusLabel(asset.quality_status)}</em>
              <small>{qualityIssuesForAsset(asset).length} issue(s), {qualityWarningsForAsset(asset).length} warning(s)</small>
            </span>
          ))}
          {assetsWithQuality.length > DEBUG_LIST_PREVIEW_LIMIT ? <span className="debug-list-more">+{assetsWithQuality.length - DEBUG_LIST_PREVIEW_LIMIT} more reviewed assets</span> : null}
        </div>
      ) : null}
    </div>
  );
}

export function PromptOptimizerPanel({ metadata }: { metadata: PromptOptimizerMetadata }) {
  const optimizerSkillIds = metadata.selected_skill_ids ?? [];
  const optimizerWarnings = providerDebugItems(metadata.optimizer_warnings);
  const qualityNotes = optimizerQualityNoteItems(metadata.quality_notes);
  const hasContent = metadata.optimizer_agent || optimizerSkillIds.length || optimizerWarnings.length || qualityNotes.length;
  if (!hasContent) return null;

  return (
    <div className="prompt-optimizer-panel">
      <strong>Prompt Optimizer</strong>
      <div className="provider-strategy-summary prompt-optimizer-summary">
        {metadata.optimizer_agent ? (
          <span>
            <em>Optimizer agent</em>
            <b>{metadata.optimizer_agent}</b>
          </span>
        ) : null}
        {optimizerSkillIds.length ? (
          <span>
            <em>Selected skills</em>
            <b>{optimizerSkillIds.join(", ")}</b>
          </span>
        ) : null}
      </div>
      {optimizerWarnings.length ? (
        <div className="prompt-optimizer-list">
          <em>Optimizer warnings</em>
          {optimizerWarnings.map((item, index) => <span key={`optimizer-warning-${index}`}>{item}</span>)}
        </div>
      ) : null}
      {qualityNotes.length ? (
        <div className="prompt-optimizer-list">
          <em>Quality notes</em>
          {qualityNotes.map((item, index) => <span key={`optimizer-quality-${index}`}>{item}</span>)}
        </div>
      ) : null}
    </div>
  );
}

export function ProviderStrategyPanel({
  debug,
  referencePolicy,
  run,
  node,
}: {
  debug: ProviderStrategyDebug;
  referencePolicy?: ReferencePolicy | null;
  run?: NodeRunResult | null;
  node?: WorkflowNode | null;
}) {
  const attempts = debug.provider_attempts ?? [];
  const fallbackWarnings = providerDebugItems(debug.fallback_warnings);
  const rejectedProviders = providerDebugItems(debug.rejected_providers);
  const referenceMessages = [
    ...referencePolicyItems(referencePolicy?.errors),
    ...referencePolicyItems(referencePolicy?.warnings),
  ];
  const failureMessage = formatProviderFailureMessage(providerFailureCode(run, node, referencePolicy, debug));

  return (
    <div className="provider-strategy-panel">
      <strong>Provider Strategy</strong>
      {failureMessage ? <span className="provider-strategy-error">{failureMessage}</span> : null}
      <div className="provider-strategy-summary">
        {debug.selected_provider ? (
          <span>
            <em>Selected provider</em>
            <b>{debug.selected_provider}</b>
          </span>
        ) : null}
        {debug.fallback_used !== undefined ? (
          <span>
            <em>Fallback used</em>
            <b className={`provider-fallback-badge ${debug.fallback_used ? "is-used" : ""}`}>{String(debug.fallback_used)}</b>
          </span>
        ) : null}
        {debug.selection_reason ? (
          <span>
            <em>Selection reason</em>
            <b>{debug.selection_reason}</b>
          </span>
        ) : null}
        {debug.reference_mode ? (
          <span>
            <em>Reference mode</em>
            <b>{debug.reference_mode}</b>
          </span>
        ) : null}
      </div>
      {debug.eligible_providers?.length ? (
        <div className="provider-debug-list">
          <em>Eligible providers</em>
          <span>{debug.eligible_providers.join(", ")}</span>
        </div>
      ) : null}
      {rejectedProviders.length ? (
        <div className="provider-debug-list">
          <em>Rejected providers</em>
          {rejectedProviders.map((item, index) => <span key={`rejected-provider-${index}`}>{item}</span>)}
        </div>
      ) : null}
      {attempts.length ? (
        <div className="provider-debug-list">
          <em>Provider attempts</em>
          <ol className="provider-attempts-list">
            {attempts.map((attempt, index) => (
              <li key={[attempt.provider, attempt.status, index].join("-")}>
                <span>{index + 1}. {attempt.provider}</span>
                <b className={`status-${statusClass(attempt.status)}`}>{attempt.status}</b>
                {attempt.error_code ? <em>{attempt.error_code}</em> : null}
                {!attempt.error_code && attempt.error ? <em>{attempt.error}</em> : null}
                {attempt.duration_ms ? <small>{attempt.duration_ms}ms</small> : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {fallbackWarnings.length ? (
        <div className="provider-debug-list">
          <em>Fallback warnings</em>
          {fallbackWarnings.map((item, index) => <span key={`fallback-warning-${index}`}>{item}</span>)}
        </div>
      ) : null}
      {referenceMessages.length ? (
        <div className="provider-debug-list">
          <em>Reference policy errors / warnings</em>
          {referenceMessages.map((item, index) => <span key={`provider-reference-message-${index}`}>{item}</span>)}
        </div>
      ) : null}
    </div>
  );
}

export function IdentityCertificationPanel({
  certification,
  run,
  node,
}: {
  certification: IdentityCertificationMetadata;
  run?: NodeRunResult | null;
  node?: WorkflowNode | null;
}) {
  const status = stringFromUnknown(certification.status) || "uncertified";
  const warnings = certification.warnings ?? [];
  const errors = certification.errors ?? [];
  const referenceSemanticTypes = certification.reference_semantic_types ?? [];
  const certificationIds = certification.certification_ids ?? [];
  const failureMessage = formatIdentityCertificationFailureMessage(identityCertificationFailureCode(run, node, certification));
  const debugFlags = identityCertificationDebugFlags(run, node, certification);

  return (
    <div className="identity-certification-panel">
      <div className="identity-certification-header">
        <strong>Identity Certification</strong>
        <span className={`identity-certification-badge status-${statusClass(status)}`}>{status}</span>
      </div>
      <span className="identity-certification-copy">{identityCertificationStatusLabel(status)}</span>
      {failureMessage ? <span className="identity-certification-error">{failureMessage}</span> : null}
      {hasActiveOutputFailure(run, node) ? <span className="identity-certification-error">Latest run failed, current preview keeps the last successful output</span> : null}
      <div className="provider-strategy-summary identity-certification-summary">
        {certification.mode ? (
          <span>
            <em>Mode</em>
            <b>{certification.mode}</b>
          </span>
        ) : null}
        {certification.provider ? (
          <span>
            <em>Provider</em>
            <b>{certification.provider}</b>
          </span>
        ) : null}
        {certification.model_id ? (
          <span>
            <em>Model</em>
            <b>{certification.model_id}</b>
          </span>
        ) : null}
      </div>
      {referenceSemanticTypes.length ? (
        <div className="identity-certification-list">
          <em>Reference semantic types</em>
          <span>{referenceSemanticTypes.join(", ")}</span>
        </div>
      ) : null}
      {certificationIds.length ? (
        <div className="identity-certification-list">
          <em>Certification ids</em>
          <span>{certificationIds.join(", ")}</span>
        </div>
      ) : null}
      {debugFlags.length ? (
        <div className="identity-certification-list">
          <em>Reference flags</em>
          {debugFlags.map((flag) => <span key={flag}>{flag}</span>)}
        </div>
      ) : null}
      {warnings.length || errors.length ? (
        <div className="identity-certification-issues">
          {warnings.map((issue, index) => <span key={`identity-warning-${index}`}>Warning: {identityCertificationIssueMessage(issue)}</span>)}
          {errors.map((issue, index) => <span key={`identity-error-${index}`} className="is-error">Error: {identityCertificationIssueMessage(issue)}</span>)}
        </div>
      ) : null}
    </div>
  );
}

export function MissingInputList({ items }: { items: MissingInputReport[] }) {
  return (
    <div className="missing-input-list">
      <strong>Missing inputs</strong>
      {items.map((item, index) => (
        <span key={[item.key ?? item.input_key ?? "input", index].join("-")}>
          {item.message ?? item.reason ?? item.key ?? item.input_key ?? "missing input"}
        </span>
      ))}
    </div>
  );
}

export function LazyDebugJson({ label, value }: { label: string; value: unknown }) {
  const [open, setOpen] = useState(false);
  const json = useMemo(() => (open ? formatJson(value) : ""), [open, value]);

  return (
    <details
      className="lazy-debug-json"
      onToggle={(event) => {
        setOpen(event.currentTarget.open);
      }}
    >
      <summary>{label}</summary>
      {open ? <pre className="output-json">{json}</pre> : null}
    </details>
  );
}

/* eslint-disable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/click-events-have-key-events -- Lightbox backdrop handles dismiss/focus behavior; visible controls remain native buttons. */
export function MediaLightbox({ item, onClose }: { item: MediaLightboxState; onClose: () => void }) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  return (
    <div
      ref={dialogRef}
      className="media-lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={item.title}
      tabIndex={-1}
      onClick={onClose}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
    >
      <div className="media-lightbox-card" onClick={(event) => event.stopPropagation()}>
        <button className="media-lightbox-close" type="button" aria-label="Close media preview" onClick={onClose}>
          Close
        </button>
        {item.type === "video" ? (
          <video src={item.src} poster={item.poster} controls autoPlay playsInline />
        ) : (
          <img src={item.src} alt={item.title} />
        )}
      </div>
    </div>
  );
}
/* eslint-enable jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/click-events-have-key-events */
