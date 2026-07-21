import type { NodeProps } from "@xyflow/react";
import type { CanvasRuntimeConnectionState } from "../../../workflow/canvasRuntime.ts";
import type { QualityReviewIssue, UploadedAsset } from "../../../types";
import type { CanvasNode, NodePort } from "../types";
import {
  sameStringRecord,
  sameV2AssetVersionList,
  sameV2AssetVersionMap,
  sameV2Items,
  sameV2LibraryReferenceOptions,
  sameV2Slots,
} from "./nodeDataEquality.ts";

export function formatCanvasRuntimeConnectionState(state: CanvasRuntimeConnectionState) {
  if (state === "connected") return "Live";
  if (state === "connecting") return "Connecting";
  if (state === "reconnecting") return "Reconnecting";
  if (state === "degraded_polling") return "Sync delayed";
  return "";
}

export function areWorkflowCanvasNodePropsEqual(previous: NodeProps<CanvasNode>, next: NodeProps<CanvasNode>) {
  const previousData = previous.data;
  const nextData = next.data;
  return (
    previous.selected === next.selected &&
    previousData.title === nextData.title &&
    previousData.status === nextData.status &&
    previousData.nodeId === nextData.nodeId &&
    previousData.kind === nextData.kind &&
    previousData.family === nextData.family &&
    previousData.category === nextData.category &&
    previousData.contentPreview === nextData.contentPreview &&
    previousData.version === nextData.version &&
    previousData.locked === nextData.locked &&
    previousData.stale === nextData.stale &&
    previousData.staleReason === nextData.staleReason &&
    previousData.output === nextData.output &&
    previousData.qualitySummary === nextData.qualitySummary &&
    previousData.candidateCount === nextData.candidateCount &&
    previousData.candidateWarningCount === nextData.candidateWarningCount &&
    previousData.pendingVisibleCandidateCount === nextData.pendingVisibleCandidateCount &&
    previousData.isV2Region === nextData.isV2Region &&
    sameV2Items(previousData.v2Items ?? [], nextData.v2Items ?? []) &&
    sameV2Slots(previousData.v2Slots ?? [], nextData.v2Slots ?? []) &&
    sameV2AssetVersionList(previousData.v2AssetVersions ?? [], nextData.v2AssetVersions ?? []) &&
	    sameStringRecord(previousData.v2SlotRuntimeStatusById, nextData.v2SlotRuntimeStatusById) &&
	    previousData.v2OpenSlotId === nextData.v2OpenSlotId &&
	    previousData.v2OpenStoryboardItemId === nextData.v2OpenStoryboardItemId &&
	    previousData.v2SlotDraftsById === nextData.v2SlotDraftsById &&
	    sameV2AssetVersionMap(previousData.v2ReferenceAssetsBySlotId, nextData.v2ReferenceAssetsBySlotId) &&
	    sameV2LibraryReferenceOptions(previousData.v2LibraryReferenceOptions, nextData.v2LibraryReferenceOptions) &&
	    previousData.onOpenScreenplay === nextData.onOpenScreenplay &&
	    previousData.onOpenV2SlotEditor === nextData.onOpenV2SlotEditor &&
	    previousData.onOpenV2StoryboardPrompt === nextData.onOpenV2StoryboardPrompt &&
	    previousData.onChangeV2SlotPrompt === nextData.onChangeV2SlotPrompt &&
    previousData.onChangeV2SlotNegativePrompt === nextData.onChangeV2SlotNegativePrompt &&
    previousData.onUploadV2SlotReference === nextData.onUploadV2SlotReference &&
    previousData.onSelectV2SlotLibraryReference === nextData.onSelectV2SlotLibraryReference &&
    previousData.onRemoveV2SlotReference === nextData.onRemoveV2SlotReference &&
	    previousData.onOpenV2SlotAssetLibraryReplace === nextData.onOpenV2SlotAssetLibraryReplace &&
	    previousData.onOpenV2SlotAssetLibrarySave === nextData.onOpenV2SlotAssetLibrarySave &&
	    previousData.onSaveV2ItemPrompt === nextData.onSaveV2ItemPrompt &&
	    previousData.onSubmitV2SlotPrompt === nextData.onSubmitV2SlotPrompt &&
    previousData.onSelectV2SlotVersion === nextData.onSelectV2SlotVersion &&
    previousData.onDiscardV2SlotWorkingVersion === nextData.onDiscardV2SlotWorkingVersion &&
    previousData.onOpenMedia === nextData.onOpenMedia &&
    previousData.onSelectDynamicItem === nextData.onSelectDynamicItem &&
    sameAssetList(previousData.previewAssets, nextData.previewAssets) &&
    samePortList(previousData.inputPorts, nextData.inputPorts) &&
    samePortList(previousData.outputPorts, nextData.outputPorts) &&
    previousData.runningDynamicItemById === nextData.runningDynamicItemById
  );
}

function qualityIssuesForAsset(asset: UploadedAsset): QualityReviewIssue[] {
  return Array.isArray(asset.quality_issues) ? asset.quality_issues : [];
}

function qualityWarningsForAsset(asset: UploadedAsset): QualityReviewIssue[] {
  return Array.isArray(asset.quality_warnings) ? asset.quality_warnings : [];
}

function sameAssetList(left: UploadedAsset[], right: UploadedAsset[]) {
  if (left === right) return true;
  if (left.length !== right.length) return false;
  return left.every((asset, index) => {
    const other = right[index];
    return (
      asset.asset_id === other.asset_id &&
      asset.local_path === other.local_path &&
      asset.public_url === other.public_url &&
      asset.preview_path === other.preview_path &&
      asset.preview_url === other.preview_url &&
      asset.poster_path === other.poster_path &&
      asset.poster_url === other.poster_url &&
      asset.version === other.version &&
      asset.is_active === other.is_active &&
      asset.is_archived === other.is_archived &&
      asset.quality_status === other.quality_status &&
      asset.quality_score === other.quality_score &&
      asset.reviewer === other.reviewer &&
      qualityIssuesForAsset(asset).length === qualityIssuesForAsset(other).length &&
      qualityWarningsForAsset(asset).length === qualityWarningsForAsset(other).length
    );
  });
}

function samePortList(left: NodePort[], right: NodePort[]) {
  if (left === right) return true;
  if (left.length !== right.length) return false;
  return left.every((port, index) => {
    const other = right[index];
    return (
      port.id === other.id &&
      port.label === other.label &&
      port.dataType === other.dataType &&
      port.required === other.required &&
      port.multiple === other.multiple
    );
  });
}
