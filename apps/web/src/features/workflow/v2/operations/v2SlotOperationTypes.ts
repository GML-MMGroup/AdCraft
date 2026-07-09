export type V2SlotOperationTarget = {
  workflowId: string;
  nodeId: string;
  itemId: string;
  slotId: string;
  assetId?: string | null;
  versionId?: string | null;
};

export type V2SlotVersionState = {
  selectedVersionId: string | null;
  selectedAssetId: string | null;
  workingVersionId: string | null;
  workingAssetId: string | null;
  historyVersionIds: string[];
  hasWorkingVersion: boolean;
  needsUseCurrentVersion: boolean;
  qualityStatus: "unchecked" | "passed" | "warning" | "failed" | "unavailable";
};

export type V2SlotAttachment = {
  relationId: string | null;
  sourceAssetId: string;
  sourceVersionId?: string | null;
  displayName: string;
  mediaType: "image" | "video" | "audio" | "text" | "unknown";
  previewUrl: string | null;
  semanticType: string;
  source: "upload" | "asset_library" | "workflow_asset" | "locator";
};

export type V2StructuredChatTarget = {
  target_type: "slot" | "asset";
  node_id?: string;
  item_id?: string;
  slot_id?: string;
  asset_id?: string;
  version_id?: string;
  display_name?: string;
  mention_text?: string;
};
