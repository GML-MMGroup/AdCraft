import { useCallback, useMemo, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { AgentConversationEvent, DynamicMediaItem, UploadedAsset } from "../../../types";
import { appendConversationEvent, appendConversationEvents } from "../../../workflow/agentConversations.ts";
import { dynamicItemActionAsset } from "../assets/dynamicItemAssetModel.ts";
import {
  assetTypeForRevisionSemanticType,
  conversationEventMetadata,
  conversationEventSemanticType,
} from "./agentConversationPanelModel.ts";
import { stringFromUnknown } from "../runtime/resolvedInputsViewModel.ts";

type PendingNodePatchLike = {
  timerId: number;
};

export function useWorkflowConversationPageActions({
  selectedDynamicMediaItemsRef,
  pendingNodePatches,
  setConversationEventsById,
  setSelectedNodeId,
  setDetailsOpen,
  invalidateNodeDebugCache,
}: {
  selectedDynamicMediaItemsRef: MutableRefObject<DynamicMediaItem[]>;
  pendingNodePatches: MutableRefObject<Map<string, PendingNodePatchLike>>;
  setConversationEventsById: Dispatch<SetStateAction<Record<string, AgentConversationEvent[]>>>;
  setSelectedNodeId: Dispatch<SetStateAction<string>>;
  setDetailsOpen: (open: boolean) => void;
  invalidateNodeDebugCache: (nodeId: string) => void;
}) {
  const appendConversationEventForConversation = useCallback((conversationId: string, event: AgentConversationEvent) => {
    setConversationEventsById((current) => ({
      ...current,
      [conversationId]: appendConversationEvent(current[conversationId] ?? [], event),
    }));
  }, [setConversationEventsById]);

  const appendConversationEventsForConversation = useCallback((conversationId: string, events: AgentConversationEvent[]) => {
    if (!events.length) return;
    setConversationEventsById((current) => ({
      ...current,
      [conversationId]: appendConversationEvents(current[conversationId] ?? [], events),
    }));
  }, [setConversationEventsById]);

  const selectConversationActionTarget = useCallback((target: { node_id?: string | null; item_id?: string | null; asset_id?: string | null }) => {
    if (target.node_id) {
      setSelectedNodeId(target.node_id);
      setDetailsOpen(true);
    }
    window.setTimeout(() => {
      const itemSelector = target.item_id ? `[data-item-id="${escapeCssAttribute(target.item_id)}"]` : "";
      const assetSelector = target.asset_id ? `[data-asset-id="${escapeCssAttribute(target.asset_id)}"]` : "";
      const element = itemSelector
        ? document.querySelector<HTMLElement>(itemSelector)
        : assetSelector
          ? document.querySelector<HTMLElement>(assetSelector)
          : null;
      element?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 80);
  }, [setDetailsOpen, setSelectedNodeId]);

  const clearPendingNodePatch = useCallback((nodeId: string) => {
    const pending = pendingNodePatches.current.get(nodeId);
    if (pending) window.clearTimeout(pending.timerId);
    pendingNodePatches.current.delete(nodeId);
  }, [pendingNodePatches]);

  const clearNodeDebugCache = useCallback((nodeId: string) => {
    invalidateNodeDebugCache(nodeId);
  }, [invalidateNodeDebugCache]);

  const dynamicMediaItemAssetFromRevisionEvent = useCallback((event: AgentConversationEvent, itemId: string): UploadedAsset => {
    const matchingItem = selectedDynamicMediaItemsRef.current.find((item) => item.itemId === itemId);
    if (matchingItem) return dynamicItemActionAsset(matchingItem);
    const semanticType = conversationEventSemanticType(event) || "unknown";
    const metadata = conversationEventMetadata(event);
    const targetAssetId = stringFromUnknown(metadata.target_asset_id) || stringFromUnknown(metadata.asset_id) || itemId;
    return {
      asset_id: targetAssetId,
      asset_type: assetTypeForRevisionSemanticType(semanticType),
      asset_role: "reference",
      filename: itemId,
      mime_type: "application/octet-stream",
      local_path: "",
      entity_id: itemId,
      semantic_type: semanticType,
    };
  }, [selectedDynamicMediaItemsRef]);

  return useMemo(() => ({
    appendConversationEventForConversation,
    appendConversationEventsForConversation,
    selectConversationActionTarget,
    clearPendingNodePatch,
    clearNodeDebugCache,
    dynamicMediaItemAssetFromRevisionEvent,
  }), [
    appendConversationEventForConversation,
    appendConversationEventsForConversation,
    clearNodeDebugCache,
    clearPendingNodePatch,
    dynamicMediaItemAssetFromRevisionEvent,
    selectConversationActionTarget,
  ]);
}

function escapeCssAttribute(value: string) {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}
