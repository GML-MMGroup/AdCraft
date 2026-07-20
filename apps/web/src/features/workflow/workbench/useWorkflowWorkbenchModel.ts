import { useMemo } from "react";
import type {
  MediaStatus,
  NodeRunResult,
  ResolvedNodeInputs,
  UploadedAsset,
  WorkflowNode,
} from "../../../types.ts";
import { assetLibraryOutputAssetsForNode } from "../../../workflow/assetLibrarySave.ts";
import { dedupeAssets } from "../../../workflow/assets.ts";
import { dynamicMediaItemsForNode } from "../../../workflow/dynamicMediaItems.ts";
import { nodePanelModel } from "../../../workflow/nodePanelModel.ts";
import {
  optimizedPromptForNode,
  providerPromptForNode,
  systemSuggestedPromptForNode,
} from "../../../workflow/runtimeResults.ts";
import {
  derivedLibraryEntitiesForAsset,
  isAssetLibrarySourcedAsset,
} from "../assets/assetLibraryReferenceModel.ts";
import { qualitySummaryForNode } from "../assets/workflowAssetPreviewModel.ts";
import {
  assetBindingsFromSources,
  assetFlowDebugFromSources,
  identityCertificationForNodeRun,
  promptOptimizerMetadataForNode,
  providerDebugFromSources,
  providerReferencePlanFromSources,
} from "../debug/workflowDebugViewModel.ts";
import { isV2InlineRegionNode } from "../v2/v2RegionNode.ts";
import { getNodePrompt } from "../graph/workflowGraphPayloadModel.ts";
import {
  getAssetArrayFromNodeContext,
  getAssetArrayFromRecord,
  getNodeMissingInputs,
  getRecordArrayFromNodeContext,
  getStringArrayFromNode,
  getStringFromRecord,
  getSystemResolvedContext,
} from "../runtime/resolvedInputsViewModel.ts";
import {
  getReferencePolicyFromNode,
  hasActiveOutputFailure,
  isStrictReferenceFailure,
} from "../runtime/workflowRunOutputViewModel.ts";

export type WorkflowWorkbenchModelArgs = {
  selectedPlanNode?: WorkflowNode | null;
  selectedRun?: NodeRunResult | null;
  selectedResolvedInputs?: ResolvedNodeInputs | null;
  mediaStatus?: MediaStatus | null;
  currentWorkflowIsV2: () => boolean;
};

export function useWorkflowWorkbenchModel({
  selectedPlanNode,
  selectedRun,
  selectedResolvedInputs,
  mediaStatus,
  currentWorkflowIsV2,
}: WorkflowWorkbenchModelArgs) {
  const selectedNode = selectedPlanNode ?? undefined;
  const selectedOutputAssets = useMemo(
    () => (selectedPlanNode ? assetLibraryOutputAssetsForNode(selectedPlanNode, selectedRun, mediaStatus) : []),
    [mediaStatus, selectedPlanNode, selectedRun],
  );
  const selectedDynamicMediaItems = useMemo(
    () =>
      selectedPlanNode
        ? dynamicMediaItemsForNode(selectedPlanNode, {
            run: selectedRun ?? undefined,
            resolvedInputs: selectedResolvedInputs ?? undefined,
            outputAssets: selectedOutputAssets,
          })
        : [],
    [selectedPlanNode, selectedRun, selectedResolvedInputs, selectedOutputAssets],
  );
  const selectedStrictReferenceFailure = isStrictReferenceFailure(selectedRun);
  const selectedActiveOutputWarning = hasActiveOutputFailure(selectedRun, selectedPlanNode);
  const selectedPanelModel = selectedPlanNode ? nodePanelModel(selectedPlanNode, { output: selectedRun?.output }) : null;
  const selectedNodeUsesV2InlineRegionEditing = Boolean(currentWorkflowIsV2() && selectedPlanNode && isV2InlineRegionNode(selectedPlanNode));
  const selectedEditablePrompt = selectedPlanNode ? getNodePrompt(selectedPlanNode) : "";
  const selectedSystemSuggestion = selectedPlanNode ? systemSuggestedPromptForNode(selectedPlanNode) : "";
  const selectedOptimizedPrompt = selectedPlanNode ? optimizedPromptForNode(selectedPlanNode) : "";
  const selectedProviderPrompt = selectedPlanNode ? providerPromptForNode(selectedPlanNode) : "";
  const hasNewSystemSuggestion = Boolean(selectedPlanNode?.metadata?.has_new_system_suggestion && selectedSystemSuggestion);
  const selectedResolvedContext = selectedResolvedInputs?.resolved_input_context ?? selectedRun?.resolved_input_context ?? getSystemResolvedContext(selectedNode);
  const selectedResolvedAssets = selectedResolvedInputs?.resolved_input_assets ?? selectedRun?.resolved_input_assets ?? [];
  const selectedMaterializedPrompt = selectedResolvedInputs?.materialized_prompt ?? selectedRun?.materialized_prompt ?? getStringFromRecord(selectedNode?.input_context, "materialized_prompt");
  const selectedMaterializedAssets = selectedResolvedInputs?.materialized_assets ?? selectedRun?.materialized_assets ?? getAssetArrayFromNodeContext(selectedNode, "materialized_assets");
  const selectedSourceMappings = selectedResolvedInputs?.source_mappings ?? selectedRun?.source_mappings ?? getRecordArrayFromNodeContext(selectedNode, "source_mappings");
  const selectedReferencePolicy = selectedResolvedInputs?.reference_policy ?? selectedRun?.reference_policy ?? getReferencePolicyFromNode(selectedNode);
  const selectedProviderDebug = providerDebugFromSources(selectedRun, selectedPlanNode, selectedResolvedInputs, selectedResolvedContext);
  const selectedProviderReferencePlan = providerReferencePlanFromSources(selectedRun, selectedPlanNode, selectedResolvedInputs, selectedResolvedContext);
  const selectedAssetFlowDebug = assetFlowDebugFromSources(selectedRun, selectedPlanNode, selectedResolvedInputs, selectedResolvedContext);
  const selectedAssetBindings = assetBindingsFromSources(selectedRun, selectedPlanNode, selectedResolvedInputs, selectedResolvedContext);
  const selectedIdentityCertification = identityCertificationForNodeRun(selectedRun, selectedPlanNode, selectedResolvedInputs);
  const selectedPromptOptimizerDebug = promptOptimizerMetadataForNode(selectedPlanNode, selectedRun, selectedResolvedInputs);
  const selectedQualitySummary = qualitySummaryForNode(selectedPlanNode, selectedRun);
  const selectedMissingInputs = selectedResolvedInputs?.missing_inputs ?? selectedRun?.missing_inputs ?? getNodeMissingInputs(selectedNode);
  const selectedStaleUpstreamNodes = selectedResolvedInputs?.stale_upstream_nodes ?? selectedRun?.stale_upstream_nodes ?? getStringArrayFromNode(selectedNode, "stale_upstream_nodes");
  const selectedLockedUpstreamNodes = selectedResolvedInputs?.locked_upstream_nodes ?? selectedRun?.locked_upstream_nodes ?? getStringArrayFromNode(selectedNode, "locked_upstream_nodes");
  const assetLibrarySourceMappings = selectedSourceMappings.filter((mapping) => String(mapping.source_type ?? mapping.type ?? "").toLowerCase() === "asset_library");
  const displayInputAssets = getAssetArrayFromRecord(selectedResolvedContext, "display_input_assets");
  const assetLibraryResolvedAssets = dedupeAssets([...selectedResolvedAssets, ...displayInputAssets]).filter(isAssetLibrarySourcedAsset);
  const derivedLibraryEntityIds = selectedOutputAssets.flatMap(derivedLibraryEntitiesForAsset);
  const hasResolvedDebugData = Boolean(
    selectedResolvedInputs ||
      selectedRun?.resolved_input_context ||
      selectedMaterializedPrompt ||
      selectedMaterializedAssets.length ||
      selectedSourceMappings.length ||
      selectedReferencePolicy ||
      selectedResolvedAssets.length ||
      selectedMissingInputs.length ||
      selectedStaleUpstreamNodes.length ||
      selectedLockedUpstreamNodes.length ||
      assetLibrarySourceMappings.length ||
      assetLibraryResolvedAssets.length ||
      derivedLibraryEntityIds.length ||
      Boolean(selectedProviderDebug) ||
      Boolean(selectedProviderReferencePlan) ||
      Boolean(selectedAssetFlowDebug) ||
      selectedAssetBindings.length > 0 ||
      Boolean(selectedPromptOptimizerDebug) ||
      Boolean(selectedIdentityCertification),
  );

  return {
    selectedOutputAssets,
    selectedDynamicMediaItems,
    selectedStrictReferenceFailure,
    selectedActiveOutputWarning,
    selectedPanelModel,
    selectedNodeUsesV2InlineRegionEditing,
    selectedEditablePrompt,
    selectedSystemSuggestion,
    selectedOptimizedPrompt,
    selectedProviderPrompt,
    hasNewSystemSuggestion,
    selectedResolvedContext,
    selectedResolvedAssets,
    selectedMaterializedPrompt,
    selectedMaterializedAssets,
    selectedSourceMappings,
    selectedReferencePolicy,
    selectedProviderDebug,
    selectedProviderReferencePlan,
    selectedAssetFlowDebug,
    selectedAssetBindings,
    selectedIdentityCertification,
    selectedPromptOptimizerDebug,
    selectedQualitySummary,
    selectedMissingInputs,
    selectedStaleUpstreamNodes,
    selectedLockedUpstreamNodes,
    assetLibrarySourceMappings,
    displayInputAssets,
    assetLibraryResolvedAssets,
    derivedLibraryEntityIds,
    hasResolvedDebugData,
  };
}
