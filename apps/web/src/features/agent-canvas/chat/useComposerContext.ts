import { useCallback, useEffect, useMemo, useState } from "react";

import type {
  AgentCanvasWorkflowV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import { useAgentCanvasAssets } from "../assets/useAgentCanvasAssets.ts";
import {
  buildComposerContextView,
  type ComposerContextView,
} from "./composerContext.ts";
import {
  conversationRecoveryFromError,
  type ConversationRecoveryView,
} from "./conversationRecovery.ts";

function toggleId(current: string[], id: string): string[] {
  return current.includes(id)
    ? current.filter((item) => item !== id)
    : [...current, id];
}

function mergeAssets(...groups: ProjectAssetSummaryV2[][]): ProjectAssetSummaryV2[] {
  const byId = new Map<string, ProjectAssetSummaryV2>();
  groups.flat().forEach((asset) => byId.set(asset.asset_id, asset));
  return [...byId.values()];
}

function retainExisting(current: string[], authority: Set<string>): string[] {
  const retained = current.filter((id) => authority.has(id));
  return retained.length === current.length && retained.every((id, index) => id === current[index])
    ? current
    : retained;
}

export function useComposerContext({
  workflow,
  onWorkflowRefresh,
}: {
  workflow: AgentCanvasWorkflowV2;
  onWorkflowRefresh?: () => Promise<void> | void;
}) {
  const projectAssets = useAgentCanvasAssets({
    workflowId: workflow.workflow_id,
    scope: "project",
    mediaType: "image",
  });
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [uploadedAssets, setUploadedAssets] = useState<ProjectAssetSummaryV2[]>([]);
  const [uploadState, setUploadState] = useState<ComposerContextView["uploadState"]>("idle");
  const [uploadIssue, setUploadIssue] = useState<ConversationRecoveryView | null>(null);

  const availableImageAssets = useMemo(() => mergeAssets(
    workflow.assets.filter((asset) => asset.media_type === "image"),
    projectAssets.items.flatMap((item) => item.projectAsset?.media_type === "image"
      ? [item.projectAsset]
      : []),
    uploadedAssets.filter((asset) => asset.media_type === "image"),
  ), [projectAssets.items, uploadedAssets, workflow.assets]);

  useEffect(() => {
    setSelectedNodeIds([]);
    setSelectedAssetIds([]);
    setUploadedAssets([]);
    setUploadState("idle");
    setUploadIssue(null);
  }, [workflow.workflow_id]);

  useEffect(() => {
    const nodeIds = new Set(workflow.nodes.map((node) => node.node_id));
    const assetIds = new Set(availableImageAssets.map((asset) => asset.asset_id));
    setSelectedNodeIds((current) => retainExisting(current, nodeIds));
    setSelectedAssetIds((current) => retainExisting(current, assetIds));
  }, [availableImageAssets, workflow.nodes]);

  const upload = useCallback(async (files: Iterable<File>): Promise<void> => {
    setUploadState("uploading");
    setUploadIssue(null);
    try {
      const uploaded = (await projectAssets.uploadFiles(files))
        .filter((asset) => asset.media_type === "image");
      setUploadedAssets((current) => mergeAssets(current, uploaded));
      setSelectedAssetIds((current) => [
        ...current,
        ...uploaded.map((asset) => asset.asset_id).filter((id) => !current.includes(id)),
      ]);
      setUploadState("idle");
      await onWorkflowRefresh?.();
    } catch (error) {
      setUploadState("failed");
      setUploadIssue(conversationRecoveryFromError("context", error, { retryable: true }));
    }
  }, [onWorkflowRefresh, projectAssets]);

  const clearMessageContext = useCallback(() => {
    setSelectedNodeIds([]);
    setSelectedAssetIds([]);
  }, []);

  const view = useMemo(() => buildComposerContextView({
    activeStyle: workflow.active_style_skill,
    assets: availableImageAssets,
    nodes: workflow.nodes,
    selectedAssetIds,
    selectedNodeIds,
    uploadState,
  }), [
    availableImageAssets,
    selectedAssetIds,
    selectedNodeIds,
    uploadState,
    workflow.active_style_skill,
    workflow.nodes,
  ]);

  return {
    view,
    selectedNodeIds,
    selectedAssetIds,
    availableImageAssets,
    uploadIssue,
    actions: {
      toggleNode: (id: string) => setSelectedNodeIds((current) => toggleId(current, id)),
      toggleAsset: (id: string) => setSelectedAssetIds((current) => toggleId(current, id)),
      removeNode: (id: string) => setSelectedNodeIds((current) => current.filter((item) => item !== id)),
      removeAsset: (id: string) => setSelectedAssetIds((current) => current.filter((item) => item !== id)),
      upload,
      clearMessageContext,
      clearUploadIssue: () => {
        setUploadState("idle");
        setUploadIssue(null);
      },
    },
  };
}
