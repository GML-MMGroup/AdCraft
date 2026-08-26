import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
  reorderEditingVideoEntries,
  replaceEditingManifest,
  updateEditingVideoEntry,
} from "./editingModel.ts";

type PatchNode = (
  nodeId: string,
  patch: CanvasNodePatchRequestV2,
  options?: { coalesce?: boolean; optimistic?: boolean },
) => Promise<void>;

type ManifestUpdater = (manifest: EditingManifestV2) => EditingManifestV2;

interface ManifestCommitItem {
  identity: string;
  nodeId: string;
  patchNode: PatchNode;
  baseManifest: EditingManifestV2;
  updateManifest: ManifestUpdater;
  authoringPayload: (manifest: EditingManifestV2) => Record<string, unknown>;
  onSuccess: (manifest: EditingManifestV2, hasNewerCommit: boolean) => void;
  onFailure: (
    error: unknown,
    confirmedManifest: EditingManifestV2,
    hasNewerCommit: boolean,
  ) => void;
}

interface ManifestCommitCoordinator {
  loop: Promise<void> | null;
  pending: boolean;
  queuedItem: ManifestCommitItem | null;
  confirmedManifest: EditingManifestV2 | null;
}

const manifestCommitCoordinators = new Map<string, ManifestCommitCoordinator>();
const manifestCommitListeners = new Map<string, Set<() => void>>();

function coordinatorFor(identity: string): ManifestCommitCoordinator {
  const existing = manifestCommitCoordinators.get(identity);
  if (existing) return existing;
  const coordinator: ManifestCommitCoordinator = {
    loop: null,
    pending: false,
    queuedItem: null,
    confirmedManifest: null,
  };
  manifestCommitCoordinators.set(identity, coordinator);
  return coordinator;
}

function notifyManifestCommitListeners(identity: string) {
  manifestCommitListeners.get(identity)?.forEach((listener) => listener());
}

function discardIdleManifestCommitCoordinator(
  identity: string,
  coordinator: ManifestCommitCoordinator,
) {
  if (!coordinator.loop && !coordinator.queuedItem) {
    manifestCommitCoordinators.delete(identity);
  }
}

function enqueueManifestCommit(item: ManifestCommitItem): Promise<void> {
  const coordinator = coordinatorFor(item.identity);
  coordinator.confirmedManifest ??= item.baseManifest;
  const queuedItem = coordinator.queuedItem;
  coordinator.queuedItem = queuedItem
    ? {
        ...item,
        baseManifest: queuedItem.baseManifest,
        updateManifest: (manifest) => item.updateManifest(queuedItem.updateManifest(manifest)),
      }
    : item;
  coordinator.pending = true;
  notifyManifestCommitListeners(item.identity);

  if (!coordinator.loop) {
    const run = async () => {
      while (coordinator.queuedItem) {
        const currentItem = coordinator.queuedItem;
        coordinator.queuedItem = null;
        const baseManifest = coordinator.confirmedManifest ?? currentItem.baseManifest;
        const manifest = currentItem.updateManifest(baseManifest);
        try {
          await currentItem.patchNode(currentItem.nodeId, {
            structured_content: currentItem.authoringPayload(manifest),
          }, { coalesce: true });
          coordinator.confirmedManifest = manifest;
          currentItem.onSuccess(manifest, Boolean(coordinator.queuedItem));
        } catch (error) {
          currentItem.onFailure(error, baseManifest, Boolean(coordinator.queuedItem));
        }
      }
    };
    coordinator.loop = run().finally(() => {
      coordinator.loop = null;
      coordinator.pending = false;
      notifyManifestCommitListeners(item.identity);
      discardIdleManifestCommitCoordinator(item.identity, coordinator);
    });
  }

  return coordinator.loop;
}

function manifestCommitPending(identity: string): boolean {
  return manifestCommitCoordinators.get(identity)?.pending ?? false;
}

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
  const manifestIdentity = JSON.stringify([workflow.workflow_id, node.node_id]);
  const [pendingManifestCommit, setPendingManifestCommit] = useState({
    identity: manifestIdentity,
    pending: manifestCommitPending(manifestIdentity),
  });
  const [exporting, setExporting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draftManifest, setDraftManifest] = useState<{
    identity: string;
    nodeId: string;
    manifest: EditingManifestV2;
  } | null>(null);
  const draftManifestRef = useRef<typeof draftManifest>(null);
  const stagedManifestRef = useRef<EditingManifestV2 | null>(null);
  const stagedBaselineManifestRef = useRef<EditingManifestV2 | null>(null);
  const stagedBaselineIsLocalDraftRef = useRef(false);
  const stagedManifestUpdaterRef = useRef<ManifestUpdater | null>(null);
  const confirmedManifestRef = useRef<EditingManifestV2 | null>(null);
  const canonicalManifestKeyRef = useRef<string | null>(null);
  const activeManifestIdentityRef = useRef(manifestIdentity);
  const mountedRef = useRef(true);

  if (activeManifestIdentityRef.current !== manifestIdentity) {
    activeManifestIdentityRef.current = manifestIdentity;
    draftManifestRef.current = null;
    stagedManifestRef.current = null;
    stagedBaselineManifestRef.current = null;
    stagedBaselineIsLocalDraftRef.current = false;
    stagedManifestUpdaterRef.current = null;
    confirmedManifestRef.current = null;
    canonicalManifestKeyRef.current = null;
  }

  useEffect(() => {
    const updatePending = () => {
      setPendingManifestCommit({
        identity: manifestIdentity,
        pending: manifestCommitPending(manifestIdentity),
      });
    };
    updatePending();
    const listeners = manifestCommitListeners.get(manifestIdentity) ?? new Set();
    listeners.add(updatePending);
    manifestCommitListeners.set(manifestIdentity, listeners);
    return () => {
      listeners.delete(updatePending);
      if (!listeners.size) manifestCommitListeners.delete(manifestIdentity);
    };
  }, [manifestIdentity]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const hasPendingManifestCommit = pendingManifestCommit.identity === manifestIdentity
    ? pendingManifestCommit.pending
    : manifestCommitPending(manifestIdentity);

  const canonicalContent = useMemo(() => {
    if (node.node_type !== "editing") return null;
    try {
      return normalizeEditingNodeContentV2(node.structured_content);
    } catch {
      return null;
    }
  }, [node.node_type, node.structured_content]);

  const canonicalManifestKey = canonicalContent
    ? `${manifestIdentity}:${node.revision}:${canonicalContent.manifest.manifest_revision}`
    : null;
  if (canonicalManifestKey !== canonicalManifestKeyRef.current) {
    canonicalManifestKeyRef.current = canonicalManifestKey;
    if (
      canonicalContent
      && !draftManifestRef.current
      && !stagedManifestRef.current
      && !hasPendingManifestCommit
    ) {
      confirmedManifestRef.current = canonicalContent.manifest;
    }
  }

  const content = useMemo(() => {
    if (!canonicalContent) return null;
    return draftManifest?.identity === manifestIdentity
      ? {
          ...canonicalContent,
          manifest: draftManifest.manifest,
          dirty: true,
        }
      : canonicalContent;
  }, [canonicalContent, draftManifest, manifestIdentity]);

  const currentManifest = useCallback(() => {
    const draft = draftManifestRef.current;
    if (draft?.identity === manifestIdentity) return draft.manifest;
    return confirmedManifestRef.current ?? canonicalContent?.manifest ?? null;
  }, [canonicalContent?.manifest, manifestIdentity]);

  const setLocalDraft = useCallback((manifest: EditingManifestV2 | null) => {
    const draft = manifest ? { identity: manifestIdentity, nodeId: node.node_id, manifest } : null;
    draftManifestRef.current = draft;
    setDraftManifest(draft);
  }, [manifestIdentity, node.node_id]);

  const inputs = useMemo(
    () => content ? buildEditingInputs(workflow, node.node_id, content) : { videos: [], bgm: null },
    [content, node.node_id, workflow],
  );

  const queueManifestCommit = useCallback((
    updateManifest: ManifestUpdater,
    optimisticManifest?: EditingManifestV2,
    baseManifestOverride?: EditingManifestV2,
  ) => {
    const baseManifest = baseManifestOverride ?? currentManifest();
    if (!canonicalContent || !baseManifest) return Promise.resolve();
    const manifest = optimisticManifest ?? updateManifest(baseManifest);
    stagedManifestRef.current = null;
    stagedBaselineManifestRef.current = null;
    stagedBaselineIsLocalDraftRef.current = false;
    stagedManifestUpdaterRef.current = null;
    setLocalDraft(manifest);
    setError(null);
    setPendingManifestCommit({ identity: manifestIdentity, pending: true });
    return enqueueManifestCommit({
      identity: manifestIdentity,
      nodeId: node.node_id,
      patchNode,
      baseManifest,
      updateManifest,
      authoringPayload: (nextManifest) => (
        replaceEditingManifest(canonicalContent, nextManifest) as unknown as Record<string, unknown>
      ),
      onSuccess: (confirmedManifest, hasNewerCommit) => {
        if (
          !mountedRef.current
          || activeManifestIdentityRef.current !== manifestIdentity
        ) return;
        confirmedManifestRef.current = confirmedManifest;
        if (
          draftManifestRef.current?.identity === manifestIdentity
          && draftManifestRef.current.manifest === manifest
          && !stagedManifestRef.current
          && !hasNewerCommit
        ) {
          setLocalDraft(null);
        }
      },
      onFailure: (saveError, confirmedManifest, hasNewerCommit) => {
        if (
          !mountedRef.current
          || activeManifestIdentityRef.current !== manifestIdentity
        ) return;
        setError(errorMessage(saveError, "Unable to update the composition."));
        if (
          draftManifestRef.current?.identity === manifestIdentity
          && draftManifestRef.current.manifest === manifest
          && !stagedManifestRef.current
          && !hasNewerCommit
        ) {
          confirmedManifestRef.current = confirmedManifest;
          setLocalDraft(confirmedManifest === canonicalContent.manifest ? null : confirmedManifest);
        }
      },
    });
  }, [canonicalContent, currentManifest, manifestIdentity, node.node_id, patchNode, setLocalDraft]);

  const stageManifestUpdate = useCallback((
    updateManifest: ManifestUpdater,
    optimisticManifest?: EditingManifestV2,
  ) => {
    const manifest = currentManifest();
    if (!manifest) return false;
    const next = optimisticManifest ?? updateManifest(manifest);
    if (next === manifest) return false;
    if (!stagedManifestRef.current) {
      stagedBaselineManifestRef.current = manifest;
      stagedBaselineIsLocalDraftRef.current = (
        draftManifestRef.current?.identity === manifestIdentity
      );
    }
    const previousUpdater = stagedManifestUpdaterRef.current;
    stagedManifestUpdaterRef.current = previousUpdater
      ? (baseManifest) => updateManifest(previousUpdater(baseManifest))
      : updateManifest;
    stagedManifestRef.current = next;
    setLocalDraft(next);
    setError(null);
    return true;
  }, [currentManifest, manifestIdentity, setLocalDraft]);

  const stageVideoUpdate = useCallback((
    referenceId: string,
    patch: Partial<EditingVideoEntryV2>,
  ) => {
    stageManifestUpdate(
      (baseManifest) => updateEditingVideoEntry(baseManifest, referenceId, patch),
    );
  }, [stageManifestUpdate]);

  const stageVideoOrder = useCallback((orderedReferenceIds: readonly string[]) => {
    stageManifestUpdate(
      (baseManifest) => reorderEditingVideoEntries(baseManifest, orderedReferenceIds),
    );
  }, [stageManifestUpdate]);

  const commitStagedManifest = useCallback(() => {
    const stagedManifest = stagedManifestRef.current;
    const stagedUpdater = stagedManifestUpdaterRef.current;
    if (!stagedManifest || !stagedUpdater) {
      return manifestCommitCoordinators.get(manifestIdentity)?.loop ?? Promise.resolve();
    }
    return queueManifestCommit(
      stagedUpdater,
      stagedManifest,
      stagedBaselineManifestRef.current ?? undefined,
    );
  }, [manifestIdentity, queueManifestCommit]);

  const discardStagedManifest = useCallback(() => {
    if (!stagedManifestRef.current) return;
    const stagedBaselineManifest = stagedBaselineManifestRef.current;
    const stagedBaselineIsLocalDraft = stagedBaselineIsLocalDraftRef.current;
    stagedManifestRef.current = null;
    stagedBaselineManifestRef.current = null;
    stagedBaselineIsLocalDraftRef.current = false;
    stagedManifestUpdaterRef.current = null;
    setLocalDraft(stagedBaselineIsLocalDraft ? stagedBaselineManifest : null);
  }, [setLocalDraft]);

  const moveVideo = useCallback((referenceId: string, offset: -1 | 1) => {
    const manifest = currentManifest();
    if (!manifest) return;
    const updateManifest: ManifestUpdater = (baseManifest) => (
      moveEditingVideoEntry(baseManifest, referenceId, offset)
    );
    const next = updateManifest(manifest);
    if (next !== manifest) void queueManifestCommit(updateManifest, next);
  }, [currentManifest, queueManifestCommit]);

  const updateVideo = useCallback((
    referenceId: string,
    patch: Partial<EditingVideoEntryV2>,
  ) => {
    const manifest = currentManifest();
    if (!manifest) return;
    const updateManifest: ManifestUpdater = (baseManifest) => (
      updateEditingVideoEntry(baseManifest, referenceId, patch)
    );
    const next = updateManifest(manifest);
    if (next !== manifest) void queueManifestCommit(updateManifest, next);
  }, [currentManifest, queueManifestCommit]);

  const setBgm = useCallback((patch: Partial<EditingBgmEntryV2>) => {
    const manifest = currentManifest();
    if (!manifest?.bgm) return;
    const updateManifest: ManifestUpdater = (baseManifest) => (
      baseManifest.bgm
        ? {
            ...baseManifest,
            bgm: {
              ...baseManifest.bgm,
              ...patch,
              fade_in_seconds: 0,
              fade_out_seconds: 0,
            },
          }
        : baseManifest
    );
    void queueManifestCommit(updateManifest, updateManifest(manifest));
  }, [currentManifest, queueManifestCommit]);

  const setBgmVolume = useCallback((volume: number) => {
    setBgm({ volume: Math.min(1, Math.max(0, volume)) });
  }, [setBgm]);

  const setOutput = useCallback((patch: Partial<EditingManifestV2["output"]>) => {
    const manifest = currentManifest();
    if (!manifest) return;
    const updateManifest: ManifestUpdater = (baseManifest) => ({
      ...baseManifest,
      output: { ...baseManifest.output, ...patch },
    });
    void queueManifestCommit(updateManifest, updateManifest(manifest));
  }, [currentManifest, queueManifestCommit]);

  const exportComposition = useCallback(async () => {
    if (
      !content
      || exporting
      || hasPendingManifestCommit
      || manifestCommitPending(manifestIdentity)
    ) return;
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
  }, [
    content,
    exporting,
    hasPendingManifestCommit,
    manifestIdentity,
    node.node_id,
    workflow.workflow_id,
  ]);

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
    saving: hasPendingManifestCommit,
    exporting,
    downloading,
    error,
    clearError: () => setError(null),
    stageVideoUpdate,
    commitStagedManifest,
    discardStagedManifest,
    hasPendingManifestCommit,
    moveVideo,
    stageVideoOrder,
    updateVideo,
    setBgm,
    setBgmVolume,
    setOutput,
    exportComposition,
    cancelExport,
    downloadExport,
  };
}
