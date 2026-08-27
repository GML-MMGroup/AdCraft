import { useMemo, useRef, useState } from "react";

import { createOperationKey } from "../../../api/operationKey.ts";
import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
} from "../../../types-v2.ts";
import { useAgentCanvasAssets } from "../assets/useAgentCanvasAssets.ts";
import { DecisionDockFrame } from "./DecisionDockFrame.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";

export interface ProductSourceDecisionDockProps {
  interaction: GuidedInteractionV1;
  pending: boolean;
  issue: DecisionDockIssue | null;
  onSubmit: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
}

type ProductChoice = "upload" | "generate";

function fileIdentity(file: File, index: number): string {
  return [file.name, file.size, file.type, file.lastModified, index].join(":");
}

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
  const [files, setFiles] = useState<File[]>([]);
  const [preparing, setPreparing] = useState(false);
  const [localIssue, setLocalIssue] = useState<DecisionDockIssue | null>(null);
  const uploadKeysRef = useRef(new Map<string, string>());

  const uploadKeys = useMemo(() => files.map((file, index) => {
    const identity = fileIdentity(file, index);
    const existing = uploadKeysRef.current.get(identity);
    if (existing) return existing;
    const created = createOperationKey("guided-product-upload");
    uploadKeysRef.current.set(identity, created);
    return created;
  }), [files]);

  if (!content) return null;

  const countValid = files.length >= content.min_asset_count
    && files.length <= content.max_asset_count;
  const canSubmit = interaction.allowed_actions.includes("select_source")
    && (choice === "generate" || countValid);
  const busy = pending || preparing || assets.uploading;
  const selectionSummary = content.input_kind === "main"
    ? `${files.length} of 1 image selected`
    : `${files.length} of ${content.min_asset_count}-${content.max_asset_count} images selected`;
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
      const receipts = await assets.uploadFilesWithReceipts(
        files,
        {
          semanticRole: content.input_kind === "main" ? "product_main" : "product_multiview",
          metadata: { input_kind: content.input_kind },
        },
        uploadKeys,
      );
      const assetVersions = receipts.map(({ asset }) => {
        if (!asset.version_id) {
          throw new Error("The uploaded Product source did not return an immutable AssetVersion.");
        }
        return { asset_id: asset.asset_id, version_id: asset.version_id };
      });
      const pendingHandoffIds = receipts
        .map((receipt) => receipt.pending_handoff_id)
        .filter((id): id is string => Boolean(id));
      if (pendingHandoffIds.length > 1) {
        throw new Error("The Product upload returned conflicting pending handoffs.");
      }
      await onSubmit({
        submission_kind: "product_source",
        expected_interaction_revision: interaction.revision,
        expected_session_revision: interaction.expected_session_revision,
        action: {
          input_kind: content.input_kind,
          choice: "upload",
          handoff_mode: "apply",
          asset_versions: assetVersions,
          pending_handoff_id: pendingHandoffIds[0] ?? null,
          expected_guidance_revision: content.expected_guidance_revision,
          question_id: content.question_id,
        },
      });
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Unable to upload the Product source.";
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

  return (
    <DecisionDockFrame
      title={interaction.title}
      context={interaction.context}
      pending={busy}
      issue={effectiveIssue}
      footerSummary={choice === "upload" ? selectionSummary : "The Agent will prepare a Product source"}
      submitLabel={choice === "upload" ? "Use uploaded Product" : "Generate Product"}
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
          <label className="agent-chat__product-source-upload">
            <span>{content.input_kind === "main" ? "Upload Product source" : "Upload Product sources"}</span>
            <input
              aria-label={content.input_kind === "main" ? "Upload Product source" : "Upload Product sources"}
              type="file"
              accept="image/*"
              multiple={content.input_kind === "multiview"}
              onChange={(event) => {
                const selected = Array.from(event.currentTarget.files ?? [])
                  .slice(0, content.max_asset_count);
                setFiles(selected);
                setLocalIssue(null);
              }}
            />
            <small>{selectionSummary}</small>
          </label>
        ) : null}
      </fieldset>
    </DecisionDockFrame>
  );
}
