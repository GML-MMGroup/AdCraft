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
import {
  clearProductMainHandoff,
  readProductMainHandoff,
  writeProductMainHandoff,
  type ProductMainHandoff,
} from "./productSourceHandoff.ts";
import { mediaAssetContentPath } from "../../../workflow/mediaPreview.ts";

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

export type ComposerUploadRole = "product_main" | null;

interface ComposerUploadOptions {
  semanticRole?: ComposerUploadRole;
  preserveProductMainHandoff?: boolean;
}

export function useComposerContext({
  workflow,
  onWorkflowRefresh,
  assetsEnabled = false,
}: {
  workflow: AgentCanvasWorkflowV2;
  onWorkflowRefresh?: () => Promise<void> | void;
  assetsEnabled?: boolean;
}) {
  const projectAssets = useAgentCanvasAssets({
    workflowId: workflow.workflow_id,
    scope: "project",
    mediaType: "image",
    enabled: assetsEnabled,
  });
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [uploadedAssets, setUploadedAssets] = useState<ProjectAssetSummaryV2[]>([]);
  const [uploadedAssetIdentities, setUploadedAssetIdentities] = useState(
    () => new Map<string, { versionId: string; pendingHandoffId: string | null }>(),
  );
  const [productMainHandoff, setProductMainHandoff] = useState<ProductMainHandoff | null>(
    () => readProductMainHandoff(workflow.workflow_id),
  );
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
    setUploadedAssetIdentities(new Map());
    setProductMainHandoff(readProductMainHandoff(workflow.workflow_id));
    setUploadState("idle");
    setUploadIssue(null);
  }, [workflow.workflow_id]);

  useEffect(() => {
    const nodeIds = new Set(workflow.nodes.map((node) => node.node_id));
    const assetIds = new Set(availableImageAssets.map((asset) => asset.asset_id));
    setSelectedNodeIds((current) => retainExisting(current, nodeIds));
    setSelectedAssetIds((current) => retainExisting(current, assetIds));
  }, [availableImageAssets, workflow.nodes]);

  const upload = useCallback(async (
    files: Iterable<File>,
    options: ComposerUploadOptions = {},
  ): Promise<void> => {
    setUploadState("uploading");
    setUploadIssue(null);
    try {
      const receipts = await projectAssets.uploadFilesWithReceipts(files, {
        semanticRole: options.semanticRole ?? null,
      });
      const imageReceipts = receipts.filter((receipt) => receipt.asset.media_type === "image");
      const uploaded = imageReceipts.map((receipt) => receipt.asset);
      setUploadedAssetIdentities((current) => {
        const next = new Map(current);
        imageReceipts.forEach((receipt) => {
          if (receipt.asset.version_id) {
            next.set(receipt.asset.asset_id, {
              versionId: receipt.asset.version_id,
              pendingHandoffId: receipt.pending_handoff_id,
            });
          }
        });
        return next;
      });
      setUploadedAssets((current) => mergeAssets(current, uploaded));
      setSelectedAssetIds((current) => [
        ...current,
        ...uploaded.map((asset) => asset.asset_id).filter((id) => !current.includes(id)),
      ]);
      if (options.semanticRole === "product_main") {
        const receipt = imageReceipts[0];
        if (receipt?.asset.version_id) {
          const handoff: ProductMainHandoff = {
            workflowId: workflow.workflow_id,
            assetId: receipt.asset.asset_id,
            versionId: receipt.asset.version_id,
            pendingHandoffId: receipt.pending_handoff_id,
            displayName: receipt.asset.display_name,
            previewUrl: mediaAssetContentPath(receipt.asset) || null,
          };
          setProductMainHandoff(handoff);
          writeProductMainHandoff(handoff);
        }
      } else if (!options.preserveProductMainHandoff) {
        setProductMainHandoff(null);
        clearProductMainHandoff(workflow.workflow_id);
      }
      setUploadState("idle");
      await onWorkflowRefresh?.();
    } catch (error) {
      setUploadState("failed");
      setUploadIssue(conversationRecoveryFromError("context", error));
    }
  }, [onWorkflowRefresh, projectAssets, workflow.workflow_id]);

  const clearMessageContext = useCallback(() => {
    setSelectedNodeIds([]);
    setSelectedAssetIds([]);
  }, []);

  const consumeSubmittedContext = useCallback((submitted: {
    nodeIds: string[];
    assetIds: string[];
  }) => {
    const submittedNodeIds = new Set(submitted.nodeIds);
    const submittedAssetIds = new Set(submitted.assetIds);
    setSelectedNodeIds((current) => current.filter((id) => !submittedNodeIds.has(id)));
    setSelectedAssetIds((current) => current.filter((id) => !submittedAssetIds.has(id)));
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
    productMainHandoff,
    uploadedAssetIds: [...uploadedAssetIdentities.keys()],
    uploadIssue,
    actions: {
      toggleNode: (id: string) => setSelectedNodeIds((current) => toggleId(current, id)),
      toggleAsset: (id: string) => setSelectedAssetIds((current) => toggleId(current, id)),
      removeNode: (id: string) => setSelectedNodeIds((current) => current.filter((item) => item !== id)),
      removeAsset: (id: string) => setSelectedAssetIds((current) => current.filter((item) => item !== id)),
      upload,
      markAssetAsProductMain: (assetId: string) => {
        const asset = availableImageAssets.find((candidate) => candidate.asset_id === assetId);
        const identity = uploadedAssetIdentities.get(assetId);
        if (!asset || asset.media_type !== "image" || !identity) return;
        const handoff: ProductMainHandoff = {
          workflowId: workflow.workflow_id,
          assetId,
          versionId: identity.versionId,
          pendingHandoffId: identity.pendingHandoffId,
          displayName: asset.display_name,
          previewUrl: mediaAssetContentPath(asset) || null,
        };
        setProductMainHandoff(handoff);
        writeProductMainHandoff(handoff);
      },
      clearProductMainHandoff: () => {
        setProductMainHandoff(null);
        clearProductMainHandoff(workflow.workflow_id);
      },
      clearMessageContext,
      consumeSubmittedContext,
      clearUploadIssue: () => {
        setUploadState("idle");
        setUploadIssue(null);
      },
    },
  };
}
