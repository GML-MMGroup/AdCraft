import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../../../i18n/useTranslation.ts";
import { productSourceCopy } from "./productSourceCopy.ts";

import { createOperationKey } from "../../../api/operationKey.ts";
import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
  GuidedReferenceCandidateV2,
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
  type SourceLibraryIdentity,
} from "./productSourceSelection.ts";
import type { AgentAssetBrowserItem } from "../assets/assetSelection.ts";
import type { ProductMainHandoff } from "./productSourceHandoff.ts";

export interface ProductSourceDecisionDockProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  issue: DecisionDockIssue | null;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
  pendingProductMainHandoff?: ProductMainHandoff | null;
  onClearProductMainHandoff?: () => void;
  onProjectsRefresh?: () => Promise<boolean> | void;
}

type ProductChoice = "upload" | "generate";

export function ProductSourceDecisionDock({
  interaction,
  pending,
  issue,
  onSubmit,
  pendingProductMainHandoff = null,
  onClearProductMainHandoff,
  onProjectsRefresh,
}: ProductSourceDecisionDockProps) {
  const t = useTranslation("en-US");
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
  const transactionInFlightRef = useRef(false);

  useEffect(() => {
    if (
      content?.input_kind !== "main"
      || !pendingProductMainHandoff
      || pendingProductMainHandoff.workflowId !== interaction.workflow_id
    ) return;
    setSelected((current) => current.length ? current : [createAssetVersionDraftItem({
      assetId: pendingProductMainHandoff.assetId,
      versionId: pendingProductMainHandoff.versionId,
      displayName: pendingProductMainHandoff.displayName,
      previewUrl: pendingProductMainHandoff.previewUrl,
      pendingHandoffId: pendingProductMainHandoff.pendingHandoffId,
    })]);
  }, [content?.input_kind, interaction.workflow_id, pendingProductMainHandoff]);

  useEffect(() => () => {
    if (typeof URL.revokeObjectURL !== "function") return;
    previewUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  if (!content) return null;
  const sourceRole = content.source_role ?? "product";
  const genericSource = sourceRole !== "product";
  const sourceScope = genericSource ? { source_role: sourceRole, occurrence_id: content.occurrence_id ?? null } : {};

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
  const selectionSummary = content.max_asset_count === null
    ? t("{count} images selected", { count: selected.length })
    : content.input_kind === "main"
    ? t("{count} of 1 image selected", { count: selected.length })
    : t("{count} of {min}-{max} images selected", {
        count: selected.length, min: content.min_asset_count, max: content.max_asset_count,
      });
  const effectiveIssue = localIssue ?? issue;

  const submit = async () => {
    if (!canSubmit || busy || transactionInFlightRef.current) return;
    transactionInFlightRef.current = true;
    setPreparing(true);
    setLocalIssue(null);
    try {
      if (choice === "generate") {
        const accepted = await onSubmit({
          submission_kind: "product_source",
          expected_interaction_revision: interaction.revision,
          expected_session_revision: interaction.expected_session_revision,
          action: {
            ...sourceScope,
            input_kind: content.input_kind,
            choice: "generate",
            handoff_mode: "apply",
            asset_versions: [],
            pending_handoff_id: null,
            expected_guidance_revision: content.expected_guidance_revision,
            question_id: content.question_id,
          },
        });
        if (accepted) {
          onClearProductMainHandoff?.();
          await assets.retry();
        }
        return;
      }
      const localItems = selected.filter((item) => item.kind === "local_file");
      const receipts = localItems.length
        ? await assets.uploadFilesWithReceipts(
            localItems.map((item) => item.file),
            {
              semanticRole: sourceRole === "character" ? "character_three_view" : sourceRole === "scene" ? "scene_multi_view_grid" : content.input_kind === "main" ? "product_main" : "product_multiview",
              metadata: { input_kind: content.input_kind, ...sourceScope },
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
      const accepted = await onSubmit({
        submission_kind: "product_source",
        expected_interaction_revision: interaction.revision,
        expected_session_revision: interaction.expected_session_revision,
        action: {
          ...sourceScope,
          input_kind: content.input_kind,
          choice: "upload",
          handoff_mode: "apply",
          asset_versions: resolved.assetVersions,
          pending_handoff_id: resolved.pendingHandoffId,
          expected_guidance_revision: content.expected_guidance_revision,
          question_id: content.question_id,
        },
      });
      if (accepted) {
        onClearProductMainHandoff?.();
        await assets.retry();
        await onProjectsRefresh?.();
      }
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Unable to prepare the Product source.";
      setLocalIssue({
        summary: "The Product source could not be prepared.",
        detail,
        fieldId: null,
      retryable: true,
      });
    } finally {
      transactionInFlightRef.current = false;
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
      pendingHandoffId: null,
    });
    if (
      pendingProductMainHandoff
      && (pendingProductMainHandoff.assetId !== draft.assetId
        || pendingProductMainHandoff.versionId !== draft.versionId)
    ) onClearProductMainHandoff?.();
    updateSelected(() => addProductSourceItem(selected, draft, content.input_kind, content.max_asset_count));
  };

  const selectLibraryAsset = (candidate: GuidedReferenceCandidateV2, catalog: SourceLibraryIdentity) => {
    const draft = createAssetVersionDraftItem({
      assetId: candidate.asset_id,
      versionId: candidate.asset_version_id,
      displayName: candidate.display_name,
      previewUrl: candidate.preview_url,
      catalog,
    });
    updateSelected(() => addProductSourceItem(selected, draft, content.input_kind, content.max_asset_count));
  };

  const selectFiles = (files: File[]) => {
    onClearProductMainHandoff?.();
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
      title={content.source_label ? `${productSourceCopy(interaction.title, t)} · ${content.source_label}` : productSourceCopy(interaction.title, t)}
      context={productSourceCopy(interaction.context, t)}
      pending={busy}
      issue={effectiveIssue ? {
        ...effectiveIssue,
        summary: productSourceCopy(effectiveIssue.summary, t, genericSource),
        detail: effectiveIssue.detail ? productSourceCopy(effectiveIssue.detail, t, genericSource) : null,
      } : null}
      footerSummary={choice === "upload" ? selectionSummary : t(genericSource ? "The Agent will design and generate this asset" : "The Agent will prepare a Product source")}
      submitLabel={t(genericSource ? (choice === "upload" ? "Use selected images" : "Let the Agent design") : (choice === "upload" ? "Use selected Product" : "Generate Product"))}
      submitDisabled={!canSubmit}
      onSubmit={() => { void submit(); }}
    >
      <fieldset className="agent-chat__product-source" disabled={busy}>
        <legend>{productSourceCopy(content.prompt, t)}</legend>
        {genericSource ? <p>{t("One image is used as-is; multiple images are combined in the selected order.")}</p> : null}
        <div className="agent-chat__product-source-choices">
          <label>
            <input
              type="radio"
              name={`${interaction.interaction_id}-source-choice`}
              checked={choice === "upload"}
              onChange={() => setChoice("upload")}
            />
            <span>{t(genericSource ? "Use existing images" : "Use uploaded Product source")}</span>
          </label>
          <label>
            <input
              type="radio"
              name={`${interaction.interaction_id}-source-choice`}
              aria-label={t(genericSource ? "Agent design and generation" : "Generate Product source")}
              checked={choice === "generate"}
              onChange={() => setChoice("generate")}
            />
            <span>{t(genericSource ? "Agent design and generation" : "Generate Product source")}</span>
          </label>
        </div>
        {choice === "upload" ? (
          <ProductSourceAssetPicker
            genericSource={genericSource}
            sourceLibrary={genericSource ? {
              workflowId: interaction.workflow_id,
              sourceRole,
              onSelect: selectLibraryAsset,
            } : undefined}
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
