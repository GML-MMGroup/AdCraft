import { useEffect, useRef, useState, type ChangeEvent } from "react";

import { createOperationKey } from "../../../api/operationKey.ts";
import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
  GuidedReferenceKindV1,
} from "../../../types-v2.ts";
import { StableMediaPreview } from "../../../workflow/StableMediaPreview.tsx";
import { useAgentCanvasAssets } from "../assets/useAgentCanvasAssets.ts";
import type { AgentAssetBrowserItem } from "../assets/assetSelection.ts";
import { DecisionDockFrame } from "./DecisionDockFrame.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";

export interface ReferenceSourceDecisionDockProps {
  interaction: GuidedInteractionV1;
  occurrenceLabel?: string | null;
  pending: boolean;
  issue: DecisionDockIssue | null;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}

type SelectedReference = {
  assetId: string;
  versionId: string | null;
  displayName: string;
  previewUrl: string;
  file?: File;
  uploadIdempotencyKey?: string;
};

function isSelectable(item: AgentAssetBrowserItem): boolean {
  return item.source === "project"
    && item.mediaType === "image"
    && item.status === "ready"
    && Boolean(item.identity.versionId);
}

function referenceLabel(referenceKind: GuidedReferenceKindV1): string {
  return referenceKind === "character_main" ? "Character reference" : "Scene reference";
}

export function ReferenceSourceDecisionDock({
  interaction,
  occurrenceLabel = null,
  pending,
  issue,
  onSubmit,
}: ReferenceSourceDecisionDockProps) {
  const content = interaction.content.content_kind === "reference_source"
    ? interaction.content
    : null;
  const assets = useAgentCanvasAssets({
    workflowId: interaction.workflow_id,
    scope: "project",
    mediaType: "image",
  });
  const [selected, setSelected] = useState<SelectedReference | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [localIssue, setLocalIssue] = useState<DecisionDockIssue | null>(null);
  const previewUrlsRef = useRef(new Set<string>());
  const transactionInFlightRef = useRef(false);

  useEffect(() => () => {
    if (typeof URL.revokeObjectURL !== "function") return;
    previewUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  if (!content) return null;

  const busy = pending || preparing || assets.uploading;
  const effectiveIssue = localIssue ?? issue;
  const submit = async (action: "use_reference" | "skip_reference") => {
    if (busy || transactionInFlightRef.current) return;
    if (action === "use_reference" && (!selected || !selected.versionId && !selected.file)) return;
    transactionInFlightRef.current = true;
    setPreparing(true);
    setLocalIssue(null);
    try {
      let exactAsset = selected;
      if (action === "use_reference" && selected?.file) {
        const [receipt] = await assets.uploadFilesWithReceipts(
          [selected.file],
          { semanticRole: content.reference_kind === "character_main" ? "character_main_reference" : "scene_main_reference" },
          [selected.uploadIdempotencyKey ?? createOperationKey("guided-reference-upload")],
        );
        if (!receipt?.asset.version_id) throw new Error("The uploaded reference did not return an immutable AssetVersion.");
        exactAsset = {
          assetId: receipt.asset.asset_id,
          versionId: receipt.asset.version_id,
          displayName: receipt.asset.display_name,
          previewUrl: receipt.asset.preview_url ?? receipt.asset.media_url ?? "",
        };
      }
      const request: GuidedInteractionSubmitRequestV1 = action === "use_reference"
        ? {
            submission_kind: "reference_source",
            expected_interaction_revision: interaction.revision,
            expected_session_revision: interaction.expected_session_revision,
            action,
            reference_kind: content.reference_kind,
            asset_id: exactAsset?.assetId,
            asset_version_id: exactAsset?.versionId,
          }
        : {
            submission_kind: "reference_source",
            expected_interaction_revision: interaction.revision,
            expected_session_revision: interaction.expected_session_revision,
            action,
            reference_kind: content.reference_kind,
          };
      await onSubmit(request);
    } catch (error) {
      setLocalIssue({
        summary: "The reference source could not be prepared.",
        detail: error instanceof Error ? error.message : "Unable to prepare the reference source.",
        fieldId: null,
        retryable: true,
      });
    } finally {
      transactionInFlightRef.current = false;
      setPreparing(false);
    }
  };

  const selectAsset = (item: AgentAssetBrowserItem) => {
    if (!isSelectable(item) || !item.identity.versionId) return;
    setSelected({
      assetId: item.identity.assetId,
      versionId: item.identity.versionId,
      displayName: item.displayName,
      previewUrl: item.previewUrl ?? item.mediaUrl ?? "",
    });
    setLocalIssue(null);
  };

  const selectFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file || !file.type.startsWith("image/")) return;
    const previewUrl = typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : "";
    if (previewUrl) previewUrlsRef.current.add(previewUrl);
    setSelected({
      assetId: "",
      versionId: null,
      displayName: file.name,
      previewUrl,
      file,
      uploadIdempotencyKey: createOperationKey("guided-reference-upload"),
    });
    setLocalIssue(null);
  };

  return (
    <DecisionDockFrame
      title={content.question}
      context={content.reference_kind === "character_main"
        ? `${occurrenceLabel ?? referenceLabel(content.reference_kind)} · Main`
        : "Scene · Main"}
      pending={pending || preparing}
      issue={effectiveIssue}
      showSubmitBar={false}
    >
      <div className="agent-chat__reference-source-picker">
        <div className="agent-chat__reference-source-assets" aria-label="Project reference images">
          {assets.loading ? <p role="status">Loading Project Assets</p> : null}
          {!assets.loading && assets.error ? (
            <div role="alert">
              <span>{assets.error}</span>
              <button type="button" disabled={busy} onClick={() => void assets.retry()}>Retry</button>
            </div>
          ) : null}
          {!assets.loading && !assets.error && assets.items.length === 0 ? <p>No Project images available</p> : null}
          {!assets.loading && !assets.error ? assets.items.map((item) => {
            const selectable = isSelectable(item);
            const selectedItem = selected?.assetId === item.identity.assetId && selected?.versionId === item.identity.versionId;
            return (
              <button
                key={item.id}
                type="button"
                className={selectedItem ? "is-selected" : undefined}
                aria-label={`Select ${item.displayName}`}
                aria-pressed={selectedItem}
                disabled={busy || !selectable}
                onClick={() => selectAsset(item)}
              >
                {item.previewUrl ? <StableMediaPreview src={item.previewUrl} alt="" /> : null}
                <span>{item.displayName}</span>
              </button>
            );
          }) : null}
        </div>
        <label>
          <span>Upload reference</span>
          <input aria-label="Upload reference" type="file" accept="image/*" disabled={busy} onChange={selectFile} />
        </label>
        {selected ? (
          <div className="agent-chat__reference-source-selected">
            {selected.previewUrl ? <StableMediaPreview src={selected.previewUrl} alt="" /> : null}
            <span>{selected.displayName}</span>
            <button type="button" disabled={busy} onClick={() => setSelected(null)}>Remove</button>
          </div>
        ) : null}
      </div>
      <div className="agent-chat__decision-dock-secondary-actions" aria-label="Reference source actions">
        <button type="button" disabled={busy || !selected} onClick={() => void submit("use_reference")}>
          {content.use_reference_label}
        </button>
        <button type="button" disabled={busy} onClick={() => void submit("skip_reference")}>
          {content.skip_reference_label}
        </button>
      </div>
    </DecisionDockFrame>
  );
}
