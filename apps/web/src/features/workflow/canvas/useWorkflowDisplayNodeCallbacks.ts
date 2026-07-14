import { useCallback, useMemo, type MutableRefObject } from "react";
import { mediaUrl } from "../../../api/client";
import type { UploadedAsset } from "../../../types";
import type { WorkflowItemV2 } from "../../../types-v2.ts";
import { mediaAssetOriginalPath, mediaAssetPosterPath, mediaAssetPreviewPath } from "../../../workflow/mediaPreview.ts";
import type { MediaLightboxState } from "../page/workflowPageTypes.ts";
import type { V2StoryboardVideoPreviewTarget, WorkflowNodeData } from "../types.ts";

type WorkflowDisplayNodeCallbacks = Pick<
  WorkflowNodeData,
  | "onOpenMedia"
  | "onSelectDynamicItem"
  | "onOpenScreenplay"
  | "onOpenV2SlotEditor"
  | "onOpenV2StoryboardPrompt"
  | "onOpenV2StoryboardVideoPreview"
  | "onChangeV2SlotPrompt"
  | "onChangeV2SlotNegativePrompt"
  | "onUploadV2SlotReference"
  | "onSelectV2SlotLibraryReference"
  | "onRemoveV2SlotReference"
  | "onOpenV2SlotAssetLibraryReplace"
  | "onOpenV2SlotAssetLibrarySave"
  | "onSaveV2ItemPrompt"
  | "onSubmitV2SlotPrompt"
  | "onSelectV2SlotVersion"
  | "onDiscardV2SlotWorkingVersion"
  | "onLoadV2SlotVersions"
>;

export function useWorkflowDisplayNodeCallbacks({
  selectedNodeIdRef,
  setSelectedNodeId,
  setDetailsOpen,
  setMediaLightbox,
  onOpenScreenplay: openScreenplay,
  workflowV2Items,
  setActiveV2StoryboardItemId,
  openV2SlotEditor,
  setActiveV2SlotId,
  changeV2SlotPrompt,
  changeV2SlotNegativePrompt,
  uploadV2SlotReference,
  selectV2SlotLibraryReference,
  removeV2SlotReference,
  openV2SlotAssetLibraryReplace,
  openV2SlotAssetLibrarySave,
  saveV2ItemPrompt,
  submitV2SlotMicroPrompt,
  selectV2SlotVersion,
  discardV2WorkingVersion,
  loadV2SlotVersions,
}: {
  selectedNodeIdRef: MutableRefObject<string>;
  setSelectedNodeId: (nodeId: string) => void;
  setDetailsOpen: (open: boolean) => void;
  setMediaLightbox: (asset: MediaLightboxState | null) => void;
  onOpenScreenplay: NonNullable<WorkflowDisplayNodeCallbacks["onOpenScreenplay"]>;
  workflowV2Items?: WorkflowItemV2[];
  setActiveV2StoryboardItemId: (itemId: string | null) => void;
  openV2SlotEditor: NonNullable<WorkflowDisplayNodeCallbacks["onOpenV2SlotEditor"]>;
  setActiveV2SlotId: (slotId: string | null) => void;
  changeV2SlotPrompt: NonNullable<WorkflowDisplayNodeCallbacks["onChangeV2SlotPrompt"]>;
  changeV2SlotNegativePrompt: NonNullable<WorkflowDisplayNodeCallbacks["onChangeV2SlotNegativePrompt"]>;
  uploadV2SlotReference: NonNullable<WorkflowDisplayNodeCallbacks["onUploadV2SlotReference"]>;
  selectV2SlotLibraryReference: NonNullable<WorkflowDisplayNodeCallbacks["onSelectV2SlotLibraryReference"]>;
  removeV2SlotReference: NonNullable<WorkflowDisplayNodeCallbacks["onRemoveV2SlotReference"]>;
  openV2SlotAssetLibraryReplace: NonNullable<WorkflowDisplayNodeCallbacks["onOpenV2SlotAssetLibraryReplace"]>;
  openV2SlotAssetLibrarySave: NonNullable<WorkflowDisplayNodeCallbacks["onOpenV2SlotAssetLibrarySave"]>;
  saveV2ItemPrompt: (item: WorkflowItemV2, prompt: string) => Promise<unknown>;
  submitV2SlotMicroPrompt: (slotId: string) => Promise<unknown>;
  selectV2SlotVersion: (slotId: string, versionId: string) => Promise<unknown>;
  discardV2WorkingVersion: (slotId: string) => Promise<unknown>;
  loadV2SlotVersions: (slotId: string) => Promise<unknown>;
}) {
  const openMediaLightbox = useCallback((asset: UploadedAsset) => {
    const type = asset.asset_type === "video" ? "video" : asset.asset_type === "image" ? "image" : null;
    if (!type) return;
    const originalPath = mediaAssetOriginalPath(asset);
    const previewPath = mediaAssetPreviewPath(asset) || originalPath;
    const posterPath = mediaAssetPosterPath(asset);
    const src = mediaUrl(type === "image" ? previewPath || originalPath : originalPath || previewPath);
    if (!src) return;
    setMediaLightbox({
      type,
      src,
      poster: posterPath ? mediaUrl(posterPath) : undefined,
      title: asset.filename || "Media preview",
    });
  }, [setMediaLightbox]);

  const selectCanvasDynamicItem = useCallback((nodeId: string, itemId: string) => {
    setSelectedNodeId(nodeId);
    selectedNodeIdRef.current = nodeId;
    setDetailsOpen(true);
    const selector = `.dynamic-media-item-card[data-workbench-item-id="${escapeCssAttribute(itemId)}"], .dynamic-media-item-card[data-item-id="${escapeCssAttribute(itemId)}"]`;
    const tryScrollIntoView = (attempt = 0) => {
      const element = document.querySelector<HTMLElement>(selector);
      if (element) {
        element.scrollIntoView({ block: "center", behavior: "smooth" });
        return;
      }
      if (attempt >= 8) return;
      window.setTimeout(() => {
        requestAnimationFrame(() => {
          tryScrollIntoView(attempt + 1);
        });
      }, attempt < 2 ? 50 : attempt < 5 ? 120 : 220);
    };
    requestAnimationFrame(() => {
      tryScrollIntoView(0);
    });
  }, [selectedNodeIdRef, setDetailsOpen, setSelectedNodeId]);

  const openV2SlotEditorFromCanvas = useCallback((slotId: string) => {
    setActiveV2StoryboardItemId(null);
    openV2SlotEditor(slotId);
  }, [openV2SlotEditor, setActiveV2StoryboardItemId]);

  const openV2StoryboardPrompt = useCallback((itemId: string) => {
    const item = workflowV2Items?.find((candidate) => candidate.item_id === itemId);
    if (!item) return;
    setActiveV2SlotId(null);
    setActiveV2StoryboardItemId(itemId);
    setSelectedNodeId(item.node_id);
    selectedNodeIdRef.current = item.node_id;
  }, [selectedNodeIdRef, setActiveV2SlotId, setActiveV2StoryboardItemId, setSelectedNodeId, workflowV2Items]);

  const openV2StoryboardVideoPreview = useCallback((preview: V2StoryboardVideoPreviewTarget) => {
    setMediaLightbox({ type: "video", ...preview });
  }, [setMediaLightbox]);

  const displayNodeCallbacks = useMemo<WorkflowDisplayNodeCallbacks>(
    () => ({
      onOpenMedia: openMediaLightbox,
      onSelectDynamicItem: selectCanvasDynamicItem,
      onOpenScreenplay: openScreenplay,
      onOpenV2SlotEditor: openV2SlotEditorFromCanvas,
      onOpenV2StoryboardPrompt: openV2StoryboardPrompt,
      onOpenV2StoryboardVideoPreview: openV2StoryboardVideoPreview,
      onChangeV2SlotPrompt: changeV2SlotPrompt,
      onChangeV2SlotNegativePrompt: changeV2SlotNegativePrompt,
      onUploadV2SlotReference: uploadV2SlotReference,
      onSelectV2SlotLibraryReference: selectV2SlotLibraryReference,
      onRemoveV2SlotReference: removeV2SlotReference,
      onOpenV2SlotAssetLibraryReplace: openV2SlotAssetLibraryReplace,
      onOpenV2SlotAssetLibrarySave: openV2SlotAssetLibrarySave,
      onSaveV2ItemPrompt: (itemId: string, prompt: string) => {
        const item = workflowV2Items?.find((candidate) => candidate.item_id === itemId);
        if (item) void saveV2ItemPrompt(item, prompt);
      },
      onSubmitV2SlotPrompt: (slotId: string) => void submitV2SlotMicroPrompt(slotId),
      onSelectV2SlotVersion: (slotId: string, versionId: string) => void selectV2SlotVersion(slotId, versionId),
      onDiscardV2SlotWorkingVersion: (slotId: string) => void discardV2WorkingVersion(slotId),
      onLoadV2SlotVersions: (slotId: string) => void loadV2SlotVersions(slotId),
    }),
    [
      changeV2SlotNegativePrompt,
      changeV2SlotPrompt,
      discardV2WorkingVersion,
      loadV2SlotVersions,
      openMediaLightbox,
      openScreenplay,
      openV2SlotAssetLibraryReplace,
      openV2SlotAssetLibrarySave,
      openV2SlotEditorFromCanvas,
      openV2StoryboardPrompt,
      openV2StoryboardVideoPreview,
      removeV2SlotReference,
      saveV2ItemPrompt,
      selectCanvasDynamicItem,
      selectV2SlotLibraryReference,
      selectV2SlotVersion,
      submitV2SlotMicroPrompt,
      uploadV2SlotReference,
      workflowV2Items,
    ],
  );

  return { openMediaLightbox, selectCanvasDynamicItem, displayNodeCallbacks };
}

function escapeCssAttribute(value: string) {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}
