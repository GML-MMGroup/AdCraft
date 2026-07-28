import { useCallback, useMemo, useState } from "react";

import { isV2ApiError, v2Api } from "../../../api/v2Client.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasNodePatchRequestV2,
  CanvasNodeV2,
  EditingManifestV2,
} from "../../../types-v2.ts";
import { normalizeEditingNodeContentV2 } from "../model/normalizers.ts";
import {
  buildEditingInputs,
  moveEditingVideoBinding,
  replaceEditingManifest,
} from "./editingModel.ts";

type PatchNode = (
  nodeId: string,
  patch: CanvasNodePatchRequestV2,
  options?: { coalesce?: boolean; optimistic?: boolean },
) => Promise<void>;

function errorMessage(error: unknown, fallback: string): string {
  if (isV2ApiError(error)) {
    if (error.code === "editing_no_ready_video") {
      return "At least one connected video must be Ready before export.";
    }
    if (error.code === "editing_export_already_active") {
      return "This composition is already exporting.";
    }
    if (error.code === "editing_manifest_revision_conflict") {
      return "The composition changed elsewhere. Refresh the node before exporting again.";
    }
  }
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}

export function useAgentCanvasEditing(
  workflow: AgentCanvasWorkflowV2,
  node: CanvasNodeV2,
  patchNode: PatchNode,
) {
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const content = useMemo(() => {
    if (node.node_type !== "editing") return null;
    try {
      return normalizeEditingNodeContentV2(node.structured_content);
    } catch {
      return null;
    }
  }, [node.node_type, node.structured_content]);

  const inputs = useMemo(
    () => content ? buildEditingInputs(workflow, node.node_id, content) : { videos: [], bgm: null },
    [content, node.node_id, workflow],
  );

  const saveManifest = useCallback(async (next: EditingManifestV2) => {
    if (!content || saving) return;
    setSaving(true);
    setError(null);
    try {
      const authoringPayload = replaceEditingManifest(content, next);
      await patchNode(node.node_id, {
        structured_content: authoringPayload as unknown as Record<string, unknown>,
      });
    } catch (saveError) {
      setError(errorMessage(saveError, "Unable to update the composition."));
    } finally {
      setSaving(false);
    }
  }, [content, node.node_id, patchNode, saving]);

  const moveVideo = useCallback((bindingId: string, offset: -1 | 1) => {
    if (!content) return;
    const next = moveEditingVideoBinding(content.manifest, bindingId, offset);
    if (next !== content.manifest) void saveManifest(next);
  }, [content, saveManifest]);

  const setBgmVolume = useCallback((volume: number) => {
    if (!content) return;
    void saveManifest({
      ...content.manifest,
      bgm_volume: Math.min(1, Math.max(0, volume)),
    });
  }, [content, saveManifest]);

  const setOutput = useCallback((patch: Partial<EditingManifestV2["output"]>) => {
    if (!content) return;
    void saveManifest({
      ...content.manifest,
      output: { ...content.manifest.output, ...patch },
    });
  }, [content, saveManifest]);

  const exportComposition = useCallback(async () => {
    if (!content || exporting) return;
    setExporting(true);
    setError(null);
    try {
      await v2Api.exportAgentCanvasEditingNode(
        workflow.workflow_id,
        node.node_id,
        {
          expected_manifest_revision: content.manifest.manifest_revision,
          availability_policy: "use_ready_inputs",
        },
        createOperationKey("editing-export"),
      );
    } catch (exportError) {
      setError(errorMessage(exportError, "Unable to start export."));
    } finally {
      setExporting(false);
    }
  }, [content, exporting, node.node_id, workflow.workflow_id]);

  const cancelExport = useCallback(async () => {
    const activeExportId = content?.active_export?.export_id;
    if (!activeExportId || exporting) return;
    setExporting(true);
    setError(null);
    try {
      await v2Api.cancelAgentCanvasEditingExport(
        workflow.workflow_id,
        node.node_id,
        activeExportId,
        createOperationKey("editing-export-cancel"),
      );
    } catch (cancelError) {
      setError(errorMessage(cancelError, "Unable to cancel export."));
    } finally {
      setExporting(false);
    }
  }, [content?.active_export?.export_id, exporting, node.node_id, workflow.workflow_id]);

  const outputAsset = node.output_asset_id
    ? workflow.assets.find((asset) => asset.asset_id === node.output_asset_id) ?? null
    : null;

  return {
    content,
    inputs,
    outputAsset,
    saving,
    exporting,
    error,
    clearError: () => setError(null),
    moveVideo,
    setBgmVolume,
    setOutput,
    exportComposition,
    cancelExport,
  };
}
