import { useEffect, useRef, useState } from "react";

import { createOperationKey } from "../../../api/operationKey.ts";
import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
} from "../../../types-v2.ts";
import { useAgentCanvasAssets } from "../assets/useAgentCanvasAssets.ts";
import { DecisionDockFrame } from "./DecisionDockFrame.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";
import { ProductSourceAssetPicker } from "./ProductSourceAssetPicker.tsx";
import {
  addProductSourceItem,
  createAssetVersionDraftItem,
  createLocalFileDraftItem,
  moveProductSourceItem,
  removeProductSourceItem,
  resolveProductSourceAssetVersions,
  validateProductSourceDraft,
  type ProductSourceDraftItem,
} from "./productSourceSelection.ts";
import type { AgentAssetBrowserItem } from "../assets/assetSelection.ts";

export interface ProductSourceDecisionDockProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  issue: DecisionDockIssue | null;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}

type ProductChoice = "upload" | "generate";

export function ProductSourceDecisionDock({
  interaction,
  pending,
  issue,
  onSubmit,
}: ProductSourceDecisionDockProps) {
  const content = interaction.content.content_kind === "product_source"
    ? interaction.content
    : null;
  const assets = useAgentCanvasAssets({
    workflowId: interaction.workflow_id,
    scope: "project",
    mediaType: "image",
  });
  const [choice, setChoice] = useState<ProductChoice>("upload");
  const [selected, setSelected] = useState<ProductSourceDraftItem[]>([]);
  const [preparing, setPreparing] = useState(false);
  const [localIssue, setLocalIssue] = useState<DecisionDockIssue | null>(null);
  const previewUrlsRef = useRef(new Set<string>());

  useEffect(() => () => {
    if (typeof URL.revokeObjectURL !== "function") return;
    previewUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  if (!content) return null;

  const validationIssue = validateProductSourceDraft(
    selected,
    content.input_kind,
    content.min_asset_count,
    content.max_asset_count,
  );
  const countValid = validationIssue === null;
  const canSubmit = interaction.allowed_actions.includes("select_source")
    && (choice === "generate" || countValid);
  const busy = pending || preparing || assets.uploading;
  const selectionSummary = content.input_kind === "main"
    ? `${selected.length} of 1 image selected`
    : `${selected.length} of ${content.min_asset_count}-${content.max_asset_count} images selected`;
  const effectiveIssue = localIssue ?? issue;

  const submit = async () => {
    if (!canSubmit || busy) return;
    setLocalIssue(null);
    if (choice === "generate") {
      await onSubmit({
        submission_kind: "product_source",
        expected_interaction_revision: interaction.revision,
        expected_session_revision: interaction.expected_session_revision,
        action: {
          input_kind: content.input_kind,
          choice: "generate",
          handoff_mode: "apply",
          asset_versions: [],
          pending_handoff_id: null,
          expected_guidance_revision: content.expected_guidance_revision,
          question_id: content.question_id,
        },
      });
      return;
    }

    setPreparing(true);
    try {
      const localItems = selected.filter((item) => item.kind === "local_file");
      const receipts = localItems.length
        ? await assets.uploadFilesWithReceipts(
            localItems.map((item) => item.file),
            {
              semanticRole: content.input_kind === "main" ? "product_main" : "product_multiview",
              metadata: { input_kind: content.input_kind },
            },
            localItems.map((item) => item.uploadIdempotencyKey),
          )
        : [];
      const uploadedByDraftKey = new Map(localItems.map((item, index) => {
        const receipt = receipts[index];
        const { asset } = receipt;
        if (!asset.version_id) {
          throw new Error("The uploaded Product source did not return an immutable AssetVersion.");
        }
        return [item.key, {
          assetId: asset.asset_id,
          versionId: asset.version_id,
          pendingHandoffId: receipt.pending_handoff_id,
        }] as const;
      }));
      const resolved = resolveProductSourceAssetVersions(selected, uploadedByDraftKey);
      await onSubmit({
        submission_kind: "product_source",
        expected_interaction_revision: interaction.revision,
        expected_session_revision: interaction.expected_session_revision,
        action: {
          input_kind: content.input_kind,
          choice: "upload",
          handoff_mode: "apply",
          asset_versions: resolved.assetVersions,
          pending_handoff_id: resolved.pendingHandoffId,
          expected_guidance_revision: content.expected_guidance_revision,
          question_id: content.question_id,
        },
      });
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Unable to prepare the Product source.";
      setLocalIssue({
        summary: "The Product source could not be prepared.",
        detail,
        fieldId: null,
      retryable: true,
      });
    } finally {
      setPreparing(false);
    }
  };

  const updateSelected = (operation: () => ProductSourceDraftItem[]) => {
    try {
      setSelected(operation());
      setLocalIssue(null);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Unable to select the Product source.";
      setLocalIssue({ summary: detail, detail: null, fieldId: null, retryable: true });
    }
  };

  const selectAsset = (item: AgentAssetBrowserItem) => {
    const versionId = item.identity.versionId;
    if (item.source !== "project" || item.mediaType !== "image" || item.status !== "ready" || !versionId) return;
    const draft = createAssetVersionDraftItem({
      assetId: item.identity.assetId,
      versionId,
      displayName: item.displayName,
      previewUrl: item.previewUrl,
    });
    updateSelected(() => addProductSourceItem(selected, draft, content.input_kind, content.max_asset_count));
  };

  const selectFiles = (files: File[]) => {
    updateSelected(() => files.reduce((next, file) => {
      const previewUrl = typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : "";
      if (previewUrl) previewUrlsRef.current.add(previewUrl);
      const draft = createLocalFileDraftItem(
        file,
        createOperationKey("guided-product-upload"),
        previewUrl,
      );
      return addProductSourceItem(next, draft, content.input_kind, content.max_asset_count);
    }, selected));
  };

  return (
    <DecisionDockFrame
      title={interaction.title}
      context={interaction.context}
      pending={busy}
      issue={effectiveIssue}
      footerSummary={choice === "upload" ? selectionSummary : "The Agent will prepare a Product source"}
      submitLabel={choice === "upload" ? "Use selected Product" : "Generate Product"}
      submitDisabled={!canSubmit}
      onSubmit={() => { void submit(); }}
    >
      <fieldset className="agent-chat__product-source" disabled={busy}>
        <legend>{content.prompt}</legend>
        <div className="agent-chat__product-source-choices">
          <label>
            <input
              type="radio"
              name={`${interaction.interaction_id}-source-choice`}
              checked={choice === "upload"}
              onChange={() => setChoice("upload")}
            />
            <span>Use uploaded Product source</span>
          </label>
          <label>
            <input
              type="radio"
              name={`${interaction.interaction_id}-source-choice`}
              aria-label="Generate Product source"
              checked={choice === "generate"}
              onChange={() => setChoice("generate")}
            />
            <span>Generate Product source</span>
          </label>
        </div>
        {choice === "upload" ? (
          <ProductSourceAssetPicker
            items={assets.items}
            selected={selected}
            inputKind={content.input_kind}
            maxAssetCount={content.max_asset_count}
            loading={assets.loading}
            error={assets.error}
            busy={busy}
            onRetry={() => { void assets.retry(); }}
            onSelectAsset={selectAsset}
            onSelectFiles={selectFiles}
            onMove={(key, direction) => setSelected((current) => moveProductSourceItem(current, key, direction))}
            onRemove={(key) => setSelected((current) => removeProductSourceItem(current, key))}
          />
        ) : null}
      </fieldset>
    </DecisionDockFrame>
  );
}
