import { useCallback, useMemo, useRef, useState } from "react";

import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasNodePatchRequestV2,
  CanvasNodeV2,
  EditingBgmEntryV2,
  EditingManifestV2,
  EditingVideoEntryV2,
} from "../../../types-v2.ts";
import { normalizeEditingNodeContentV2 } from "../model/normalizers.ts";
import {
  buildEditingInputs,
  moveEditingVideoEntry,
  replaceEditingManifest,
  updateEditingVideoEntry,
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
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draftManifest, setDraftManifest] = useState<{
    nodeId: string;
    manifest: EditingManifestV2;
  } | null>(null);
  const draftManifestRef = useRef<typeof draftManifest>(null);
  const stagedManifestRef = useRef<EditingManifestV2 | null>(null);
  const queuedCommitRef = useRef<EditingManifestV2 | null>(null);
  const commitLoopRef = useRef<Promise<void> | null>(null);
  const confirmedManifestRef = useRef<EditingManifestV2 | null>(null);
  const canonicalManifestKeyRef = useRef<string | null>(null);

  const canonicalContent = useMemo(() => {
    if (node.node_type !== "editing") return null;
    try {
      return normalizeEditingNodeContentV2(node.structured_content);
    } catch {
      return null;
    }
  }, [node.node_type, node.structured_content]);

  const canonicalManifestKey = canonicalContent
    ? `${node.node_id}:${node.revision}:${canonicalContent.manifest.manifest_revision}`
    : null;
  if (canonicalManifestKey !== canonicalManifestKeyRef.current) {
    canonicalManifestKeyRef.current = canonicalManifestKey;
    if (
      canonicalContent
      && !draftManifestRef.current
      && !stagedManifestRef.current
      && !queuedCommitRef.current
      && !commitLoopRef.current
    ) {
      confirmedManifestRef.current = canonicalContent.manifest;
    }
  }

  const content = useMemo(() => {
    if (!canonicalContent) return null;
    return draftManifest?.nodeId === node.node_id
      ? {
          ...canonicalContent,
          manifest: draftManifest.manifest,
          dirty: true,
        }
      : canonicalContent;
  }, [canonicalContent, draftManifest, node.node_id]);

  const currentManifest = useCallback(() => {
    const draft = draftManifestRef.current;
    if (draft?.nodeId === node.node_id) return draft.manifest;
    return canonicalContent?.manifest ?? null;
  }, [canonicalContent?.manifest, node.node_id]);

  const setLocalDraft = useCallback((manifest: EditingManifestV2 | null) => {
    const draft = manifest ? { nodeId: node.node_id, manifest } : null;
    draftManifestRef.current = draft;
    setDraftManifest(draft);
  }, [node.node_id]);

  const inputs = useMemo(
    () => content ? buildEditingInputs(workflow, node.node_id, content) : { videos: [], bgm: null },
    [content, node.node_id, workflow],
  );

  const runCommitLoop = useCallback(async () => {
    while (queuedCommitRef.current) {
      const manifest = queuedCommitRef.current;
      queuedCommitRef.current = null;
      try {
        const authoringPayload = replaceEditingManifest(canonicalContent!, manifest);
        await patchNode(node.node_id, {
          structured_content: authoringPayload as unknown as Record<string, unknown>,
        }, { coalesce: true });
        confirmedManifestRef.current = manifest;

        if (
          draftManifestRef.current?.nodeId === node.node_id
          && draftManifestRef.current.manifest === manifest
          && !stagedManifestRef.current
          && !queuedCommitRef.current
        ) {
          setLocalDraft(null);
        }
      } catch (saveError) {
        setError(errorMessage(saveError, "Unable to update the composition."));
        if (
          draftManifestRef.current?.nodeId === node.node_id
          && draftManifestRef.current.manifest === manifest
          && !stagedManifestRef.current
          && !queuedCommitRef.current
        ) {
          const confirmedManifest = confirmedManifestRef.current;
          setLocalDraft(confirmedManifest === canonicalContent?.manifest ? null : confirmedManifest);
        }
      }
    }
  }, [canonicalContent, node.node_id, patchNode, setLocalDraft]);

  const ensureCommitLoop = useCallback(() => {
    if (!commitLoopRef.current) {
      const loop = runCommitLoop().finally(() => {
        commitLoopRef.current = null;
        setSaving(false);
      });
      commitLoopRef.current = loop;
    }
    return commitLoopRef.current;
  }, [runCommitLoop]);

  const queueManifestCommit = useCallback((manifest: EditingManifestV2) => {
    stagedManifestRef.current = null;
    queuedCommitRef.current = manifest;
    setLocalDraft(manifest);
    setSaving(true);
    setError(null);
    return ensureCommitLoop();
  }, [ensureCommitLoop, setLocalDraft]);

  const stageVideoUpdate = useCallback((
    referenceId: string,
    patch: Partial<EditingVideoEntryV2>,
  ) => {
    const manifest = currentManifest();
    if (!manifest) return;
    const next = updateEditingVideoEntry(manifest, referenceId, patch);
    if (next === manifest) return;
    stagedManifestRef.current = next;
    setLocalDraft(next);
    setError(null);
  }, [currentManifest, setLocalDraft]);

  const commitStagedManifest = useCallback(() => {
    const stagedManifest = stagedManifestRef.current;
    if (!stagedManifest) return commitLoopRef.current ?? Promise.resolve();
    return queueManifestCommit(stagedManifest);
  }, [queueManifestCommit]);

  const discardStagedManifest = useCallback(() => {
    if (!stagedManifestRef.current) return;
    stagedManifestRef.current = null;
    const confirmedManifest = confirmedManifestRef.current;
    setLocalDraft(confirmedManifest === canonicalContent?.manifest ? null : confirmedManifest);
  }, [canonicalContent?.manifest, setLocalDraft]);

  const moveVideo = useCallback((referenceId: string, offset: -1 | 1) => {
    const manifest = currentManifest();
    if (!manifest) return;
    const next = moveEditingVideoEntry(manifest, referenceId, offset);
    if (next !== manifest) void queueManifestCommit(next);
  }, [currentManifest, queueManifestCommit]);

  const updateVideo = useCallback((
    referenceId: string,
    patch: Partial<EditingVideoEntryV2>,
  ) => {
    const manifest = currentManifest();
    if (!manifest) return;
    const next = updateEditingVideoEntry(manifest, referenceId, patch);
    if (next !== manifest) void queueManifestCommit(next);
  }, [currentManifest, queueManifestCommit]);

  const setBgm = useCallback((patch: Partial<EditingBgmEntryV2>) => {
    const manifest = currentManifest();
    if (!manifest?.bgm) return;
    void queueManifestCommit({
      ...manifest,
      bgm: { ...manifest.bgm, ...patch },
    });
  }, [currentManifest, queueManifestCommit]);

  const setBgmVolume = useCallback((volume: number) => {
    setBgm({ volume: Math.min(1, Math.max(0, volume)) });
  }, [setBgm]);

  const setOutput = useCallback((patch: Partial<EditingManifestV2["output"]>) => {
    const manifest = currentManifest();
    if (!manifest) return;
    void queueManifestCommit({
      ...manifest,
      output: { ...manifest.output, ...patch },
    });
  }, [currentManifest, queueManifestCommit]);

  const exportComposition = useCallback(async () => {
    if (!content || exporting) return;
    setExporting(true);
    setError(null);
    try {
      await agentCanvasApi.exportAgentCanvasEditingNode(
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
      await agentCanvasApi.cancelAgentCanvasEditingExport(
        workflow.workflow_id,
        node.node_id,
        activeExportId,
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
  const terminalExport = content?.active_export?.status === "completed"
    ? content.active_export
    : content?.last_successful_export?.status === "completed"
      ? content.last_successful_export
      : null;
  const terminalExportAsset = terminalExport?.output_asset_id
    ? workflow.assets.find((asset) => asset.asset_id === terminalExport.output_asset_id) ?? null
    : null;
  const exportAsset = terminalExportAsset ?? outputAsset;
  const exportReadable = Boolean(
    terminalExport
    && terminalExport.output_asset_id
    && exportAsset?.status === "ready"
    && exportAsset.media_url,
  );

  const downloadExport = useCallback(async (assetId: string | null) => {
    if (!assetId || downloading) return;
    setDownloading(true);
    setError(null);
    try {
      const response = await agentCanvasApi.downloadAgentCanvasAsset(assetId);
      const url = URL.createObjectURL(response.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = response.filename ?? (
        response.mimeType.includes("mp4") ? "adcraft-export.mp4" : "adcraft-export"
      );
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (downloadError) {
      setError(errorMessage(downloadError, "Unable to download the exported video."));
    } finally {
      setDownloading(false);
    }
  }, [downloading]);

  return {
    content,
    inputs,
    outputAsset: exportAsset,
    terminalExport,
    exportReadable,
    saving,
    exporting,
    downloading,
    error,
    clearError: () => setError(null),
    stageVideoUpdate,
    commitStagedManifest,
    discardStagedManifest,
    hasPendingManifestCommit: saving,
    moveVideo,
    updateVideo,
    setBgm,
    setBgmVolume,
    setOutput,
    exportComposition,
    cancelExport,
    downloadExport,
  };
}
