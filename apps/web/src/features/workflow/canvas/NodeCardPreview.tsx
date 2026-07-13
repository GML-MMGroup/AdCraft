import type { UploadedAsset } from "../../../types.ts";
import type { WorkflowNodeData } from "../types.ts";
import { NodePreviewLoading } from "./NodePreviewLoading.tsx";
import { V2RegionCardPreview } from "./V2RegionCardPreview.tsx";

export type NodeCardPreviewProps = {
  data: WorkflowNodeData;
  isRunning?: boolean;
};

export function NodeCardPreview({ data, isRunning }: NodeCardPreviewProps) {
  if (data.isV2Region) {
    return (
      <V2RegionCardPreview
        items={data.v2Items ?? []}
        slots={data.v2Slots ?? []}
        assetVersions={data.v2AssetVersions ?? []}
        runtime={data.v2Runtime}
        v2SlotRuntimeStatusById={data.v2SlotRuntimeStatusById}
        title={data.title}
        isRunning={isRunning}
        openSlotId={data.v2OpenSlotId}
        openStoryboardItemId={data.v2OpenStoryboardItemId}
        slotDraftsById={data.v2SlotDraftsById}
        referenceAssetsBySlotId={data.v2ReferenceAssetsBySlotId}
        onOpenScreenplay={data.onOpenScreenplay}
        onOpenSlotEditor={data.onOpenV2SlotEditor}
        onOpenStoryboardPrompt={data.onOpenV2StoryboardPrompt}
        onSelectSlotVersion={data.onSelectV2SlotVersion}
        onDiscardSlotWorkingVersion={data.onDiscardV2SlotWorkingVersion}
      />
    );
  }

  return (
    <div className="workflow-card-preview empty">
      {data.contentPreview || data.description || `${data.family} node`}
      {isRunning ? <NodePreviewLoading type={previewLoadingType(data, data.previewAssets[0])} /> : null}
    </div>
  );
}

function previewLoadingType(data: WorkflowNodeData, asset?: UploadedAsset) {
  if (asset?.asset_type === "image") return "image";
  if (asset?.asset_type === "audio") return "audio";
  if (asset?.asset_type === "video") return "video";
  if (data.family === "Text") return "text";
  if (data.family === "Image") return "image";
  if (data.family === "Audio") return "audio";
  if (data.family === "Video" || data.family === "Preview") return "video";
  return "generic";
}
