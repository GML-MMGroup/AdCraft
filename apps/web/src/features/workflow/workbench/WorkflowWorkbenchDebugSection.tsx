import { WorkflowDebugPanel } from "../../../components/WorkflowDebugPanel";
import { validationIssueKey, workingVersionDebugKey } from "../assets/dynamicMediaItemListModel.ts";
import {
  AssetBindingScopePanel,
  AssetFlowDebugPanel,
  AssetLibrarySources,
  IdentityCertificationPanel,
  LazyDebugJson,
  MissingInputList,
  PromptOptimizerPanel,
  ProviderReferencePlanPanel,
  ProviderStrategyPanel,
  QualityReviewPanel,
  ReferencePolicyPanel,
  ReferencedInputAssets,
  SourceMappingsPanel,
} from "../panels/WorkflowDebugSections.tsx";
import { validationIssues } from "../graph/workflowGraphValidationModel.ts";
import type { WorkflowWorkbenchSurfaceActions, WorkflowWorkbenchSurfaceModel } from "./WorkflowWorkbenchSurface.tsx";

export function WorkflowWorkbenchDebugSection({
  model,
  actions,
}: {
  model: WorkflowWorkbenchSurfaceModel;
  actions: WorkflowWorkbenchSurfaceActions;
}) {
  const {
    selectedPlanNode,
    workflow,
    staleReason,
    selectedRun,
    debugLoadState,
    selectedQualitySummary,
    selectedOutputAssets,
    qualityReviewingNodeIds,
    selectedReferencePolicy,
    selectedProviderDebug,
    selectedProviderReferencePlan,
    selectedAssetFlowDebug,
    selectedAssetBindings,
    selectedPromptOptimizerDebug,
    selectedIdentityCertification,
    selectedSourceMappings,
    assetLibrarySourceMappings,
    displayInputAssets,
    assetLibraryResolvedAssets,
    derivedLibraryEntityIds,
    hasResolvedDebugData,
    selectedMaterializedPrompt,
    selectedMaterializedAssets,
    selectedResolvedContext,
    selectedResolvedAssets,
    nodeVersions,
    selectedMissingInputs,
    selectedStaleUpstreamNodes,
    selectedLockedUpstreamNodes,
    validationResult,
    affectedNodes,
    debugListPreviewLimit,
    formatEditableJson,
  } = model;
  const {
    updateSelectedConfig,
    setStaleReason,
    getWorkflowNodeType,
    ensureSelectedResolvedInputs,
    reviewSelectedNodeQuality,
    ensureNodeVersions,
    refreshNodeVersions,
  } = actions;

  if (!selectedPlanNode) return null;

  return (
    <WorkflowDebugPanel>
      <summary>Advanced / Debug</summary>
      <label className="node-config-field">
        <span>Config JSON</span>
        <textarea value={formatEditableJson(selectedPlanNode.config ?? {})} onChange={(event) => updateSelectedConfig(event.target.value)} />
      </label>
      <label className="node-config-field">
        <span>Stale reason</span>
        <input value={staleReason} onChange={(event) => setStaleReason(event.target.value)} />
      </label>
      <div className="detail-meta">
        <span>{getWorkflowNodeType(selectedPlanNode)}</span>
        <span>node v{selectedPlanNode.version ?? 1}</span>
        <span>{workflow?.workflow_id ?? "Local canvas"}</span>
        {selectedRun?.node_run_id ? <span>{selectedRun.node_run_id}</span> : null}
      </div>
      <details
        className="resolved-context-details"
        onToggle={(event) => {
          if (event.currentTarget.open) void ensureSelectedResolvedInputs();
        }}
      >
        <summary>Resolved context / assets</summary>
        {debugLoadState.resolved === "loading" ? <span className="empty-output">Loading resolved inputs...</span> : null}
        {debugLoadState.resolved === "error" ? <span className="empty-output">{debugLoadState.resolvedError ?? "Resolved inputs request failed"}</span> : null}
        <QualityReviewPanel
          summary={selectedQualitySummary}
          assets={selectedOutputAssets}
          reviewing={Boolean(qualityReviewingNodeIds[selectedPlanNode.id])}
          canReview={Boolean(workflow?.workflow_id)}
          onReview={() => void reviewSelectedNodeQuality()}
        />
        {selectedReferencePolicy ? <ReferencePolicyPanel policy={selectedReferencePolicy} /> : null}
        {selectedProviderDebug ? <ProviderStrategyPanel debug={selectedProviderDebug} referencePolicy={selectedReferencePolicy} run={selectedRun} node={selectedPlanNode} /> : null}
        {selectedProviderReferencePlan ? <ProviderReferencePlanPanel plan={selectedProviderReferencePlan} /> : null}
        {selectedAssetFlowDebug ? <AssetFlowDebugPanel debug={selectedAssetFlowDebug} /> : null}
        {selectedAssetBindings.length ? <AssetBindingScopePanel bindings={selectedAssetBindings} /> : null}
        {selectedPromptOptimizerDebug ? <PromptOptimizerPanel metadata={selectedPromptOptimizerDebug} /> : null}
        {selectedIdentityCertification ? <IdentityCertificationPanel certification={selectedIdentityCertification} run={selectedRun} node={selectedPlanNode} /> : null}
        {selectedSourceMappings.length ? <SourceMappingsPanel mappings={selectedSourceMappings} /> : null}
        {assetLibrarySourceMappings.length ? <AssetLibrarySources mappings={assetLibrarySourceMappings} /> : null}
        {displayInputAssets.length ? <ReferencedInputAssets assets={displayInputAssets} /> : null}
        {assetLibraryResolvedAssets.length ? (
          <div className="asset-library-source-panel">
            <strong>Asset Library resolved assets</strong>
            <div className="library-reference-chips">
              {assetLibraryResolvedAssets.map((asset) => (
                <span key={asset.asset_id} className="library-reference-chip">
                  <span>{asset.filename}</span>
                  <em>From Asset Library</em>
                </span>
              ))}
            </div>
          </div>
        ) : null}
        {derivedLibraryEntityIds.length ? (
          <div className="asset-library-source-panel">
            <strong>Derived from library entities</strong>
            <div className="library-reference-chips">
              {derivedLibraryEntityIds.map((entityId: string) => (
                <span key={entityId} className="library-reference-chip">
                  <span>{entityId}</span>
                  <em>derived_from_library_entities</em>
                </span>
              ))}
            </div>
          </div>
        ) : null}
        {hasResolvedDebugData ? (
          <LazyDebugJson
            label="Resolved debug JSON"
            value={{ materialized_prompt: selectedMaterializedPrompt, materialized_assets: selectedMaterializedAssets, source_mappings: selectedSourceMappings, reference_policy: selectedReferencePolicy, provider_strategy: selectedProviderDebug, provider_reference_plan: selectedProviderReferencePlan, asset_flow_debug: selectedAssetFlowDebug, asset_bindings: selectedAssetBindings, prompt_optimizer: selectedPromptOptimizerDebug, identity_certification: selectedIdentityCertification, quality_review: selectedQualitySummary, resolved_input_context: selectedResolvedContext ?? {}, resolved_input_assets: selectedResolvedAssets, display_input_assets: displayInputAssets }}
          />
        ) : debugLoadState.resolved !== "loading" ? (
          <div className="lazy-debug-empty">
            <span className="empty-output">Resolved inputs not loaded yet.</span>
            <button className="small-action" type="button" onClick={() => void ensureSelectedResolvedInputs()}>
              Load resolved inputs
            </button>
          </div>
        ) : null}
      </details>
      <details
        className="version-history-block"
        onToggle={(event) => {
          if (event.currentTarget.open) void ensureNodeVersions();
        }}
      >
        <summary>Version history</summary>
        <div className="node-preview-heading">
          <span>Version history</span>
          <button className="small-action" type="button" onClick={() => void refreshNodeVersions(selectedPlanNode.id, { force: true })}>
            Refresh
          </button>
        </div>
        {debugLoadState.versions === "loading" ? <span className="empty-output">Loading version history...</span> : null}
        {debugLoadState.versions === "error" ? <span className="empty-output">{debugLoadState.versionsError ?? "Version history request failed"}</span> : null}
        {nodeVersions.length ? (
          <div className="versions-list">
            {nodeVersions.slice(0, debugListPreviewLimit).map((version) => (
              <span key={workingVersionDebugKey(version)} className={version.active ? "active" : ""}>
                v{version.version} · {version.status ?? "unknown"}{version.active ? " · active" : ""}
              </span>
            ))}
            {nodeVersions.length > debugListPreviewLimit ? <span className="versions-list-more">+{nodeVersions.length - debugListPreviewLimit} more versions</span> : null}
          </div>
        ) : debugLoadState.versions !== "loading" ? (
          <div className="lazy-debug-empty">
            <span className="empty-output">Version history not loaded yet.</span>
            <button className="small-action" type="button" onClick={() => void ensureNodeVersions()}>
              Load version history
            </button>
          </div>
        ) : null}
      </details>
      {selectedMissingInputs.length ? <MissingInputList items={selectedMissingInputs} /> : null}
      {selectedStaleUpstreamNodes.length || selectedLockedUpstreamNodes.length ? (
        <div className="upstream-state-list">
          {selectedStaleUpstreamNodes.length ? <span className="state-chip stale">stale upstream: {selectedStaleUpstreamNodes.join(", ")}</span> : null}
          {selectedLockedUpstreamNodes.length ? <span className="state-chip locked">locked upstream: {selectedLockedUpstreamNodes.join(", ")}</span> : null}
        </div>
      ) : null}
      {validationResult ? (
        <div className="validation-list">
          {[...validationIssues(validationResult, "errors"), ...validationIssues(validationResult, "warnings")].slice(0, 4).map((issue) => (
            <span key={validationIssueKey(issue)} className={issue.level}>
              {issue.message}
            </span>
          ))}
        </div>
      ) : null}
      {affectedNodes.length ? (
        <div className="upstream-state-list">
          <span className="state-chip stale">affected: {affectedNodes.join(", ")}</span>
        </div>
      ) : null}
    </WorkflowDebugPanel>
  );
}
