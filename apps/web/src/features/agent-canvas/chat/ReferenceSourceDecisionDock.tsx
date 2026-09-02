import { useEffect, useRef, useState, type ChangeEvent } from "react";

import { createOperationKey } from "../../../api/operationKey.ts";
import type {
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
  GuidedReferenceCandidateScopeV2,
  GuidedReferenceCandidateV2,
  GuidedReferenceKindV1,
} from "../../../types-v2.ts";
import { StableMediaPreview } from "../../../workflow/StableMediaPreview.tsx";
import { useAgentCanvasAssets } from "../assets/useAgentCanvasAssets.ts";
import { DecisionDockFrame } from "./DecisionDockFrame.tsx";
import type { DecisionDockIssue } from "./decisionDockIssue.ts";
import { useGuidedReferenceCandidates } from "./useGuidedReferenceCandidates.ts";

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
  sourceScope: GuidedReferenceCandidateScopeV2;
  entityId: string | null;
  memberId: string | null;
  displayName: string;
  previewUrl: string;
  file?: File;
  uploadIdempotencyKey?: string;
};

function isSelectable(candidate: GuidedReferenceCandidateV2): boolean {
  return candidate.media_type === "image"
    && candidate.selectable
    && Boolean(candidate.asset_id && candidate.asset_version_id);
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
  const referenceKind = content?.reference_kind ?? "scene_main";
  const [sourceMode, setSourceMode] = useState<"upload" | "library">("upload");
  const [scope, setScope] = useState<GuidedReferenceCandidateScopeV2>("project");
  const [query, setQuery] = useState("");
  const uploadAssets = useAgentCanvasAssets({
    workflowId: interaction.workflow_id,
    scope: "project",
    mediaType: "image",
    enabled: false,
  });
  const candidates = useGuidedReferenceCandidates({
    workflowId: interaction.workflow_id,
    referenceKind,
    scope,
    query,
    enabled: Boolean(content) && sourceMode === "library",
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

  useEffect(() => {
    setSelected(null);
    setSourceMode("upload");
    setQuery("");
    setScope("project");
  }, [interaction.interaction_id]);

  if (!content) return null;

  const busy = pending || preparing || uploadAssets.uploading;
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
        const [receipt] = await uploadAssets.uploadFilesWithReceipts(
          [selected.file],
          { semanticRole: content.reference_kind === "character_main" ? "character_main_reference" : "scene_main_reference" },
          [selected.uploadIdempotencyKey ?? createOperationKey("guided-reference-upload")],
        );
        if (!receipt?.asset.version_id) throw new Error("The uploaded reference did not return an immutable AssetVersion.");
        exactAsset = {
          assetId: receipt.asset.asset_id,
          versionId: receipt.asset.version_id,
          sourceScope: "project",
          entityId: null,
          memberId: null,
          displayName: receipt.asset.display_name,
          previewUrl: receipt.asset.preview_url ?? receipt.asset.media_url ?? "",
        };
        setSelected(exactAsset);
      }
      const request: GuidedInteractionSubmitRequestV1 = action === "use_reference"
        ? {
            submission_kind: "reference_source",
            expected_interaction_revision: interaction.revision,
            expected_session_revision: interaction.expected_session_revision,
            action,
            reference_kind: content.reference_kind,
            source_scope: exactAsset?.sourceScope ?? "project",
            ...(exactAsset?.sourceScope === "project"
              ? {}
              : {
                  entity_id: exactAsset?.entityId,
                  member_id: exactAsset?.memberId,
                }),
            asset_id: exactAsset?.assetId,
            asset_version_id: exactAsset?.versionId,
          }
        : {
            submission_kind: "reference_source",
            expected_interaction_revision: interaction.revision,
            expected_session_revision: interaction.expected_session_revision,
            action,
            reference_kind: content.reference_kind,
            source_scope: "project",
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

  const selectCandidate = (candidate: GuidedReferenceCandidateV2) => {
    if (!isSelectable(candidate)) return;
    setSelected({
      assetId: candidate.asset_id,
      versionId: candidate.asset_version_id,
      sourceScope: scope,
      entityId: candidate.entity_id,
      memberId: candidate.member_id,
      displayName: candidate.display_name,
      previewUrl: candidate.preview_url,
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
      sourceScope: "project",
      entityId: null,
      memberId: null,
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
      <p className="agent-chat__reference-source-target">
        Target node · {content.target_node_id} · revision {content.target_node_revision}
      </p>
      <div className="agent-chat__reference-source-picker">
        <div className="agent-chat__reference-source-modes" role="tablist" aria-label="Reference source">
          <button type="button" role="tab" aria-selected={sourceMode === "upload"} onClick={() => setSourceMode("upload")}>
            Upload
          </button>
          <button type="button" role="tab" aria-selected={sourceMode === "library"} onClick={() => setSourceMode("library")}>
            Asset Library
          </button>
        </div>
        {sourceMode === "library" ? (
          <>
            <div className="agent-chat__reference-source-scopes" role="tablist" aria-label="Asset library scope">
              {(["project", "mine", "recommended"] as const).map((candidateScope) => (
                <button
                  key={candidateScope}
                  type="button"
                  role="tab"
                  aria-selected={scope === candidateScope}
                  disabled={busy}
                  onClick={() => {
                    setScope(candidateScope);
                    setSelected(null);
                  }}
                >
                  {candidateScope === "project" ? "Project" : candidateScope === "mine" ? "My Assets" : "Recommended"}
                </button>
              ))}
            </div>
            <input
              aria-label="Search reference assets"
              type="search"
              value={query}
              disabled={busy}
              placeholder="Search reference assets"
              onChange={(event) => setQuery(event.currentTarget.value)}
            />
            <div className="agent-chat__reference-source-assets" aria-label="Reference candidates">
              {candidates.loading ? <p role="status">Loading reference assets</p> : null}
              {!candidates.loading && candidates.error ? (
                <div role="alert">
                  <span>{candidates.error}</span>
                  <button type="button" disabled={busy} onClick={() => void candidates.retry()}>Retry</button>
                </div>
              ) : null}
              {!candidates.loading && !candidates.error && candidates.items.length === 0 ? <p>No reference assets available</p> : null}
              {!candidates.loading && !candidates.error ? candidates.items.map((candidate) => {
                const selectable = isSelectable(candidate);
                const selectedItem = selected?.assetId === candidate.asset_id
                  && selected?.versionId === candidate.asset_version_id;
                return (
                  <button
                    key={`${candidate.asset_id}:${candidate.asset_version_id}`}
                    type="button"
                    className={selectedItem ? "is-selected" : undefined}
                    aria-label={`Select ${candidate.display_name}`}
                    aria-pressed={selectedItem}
                    disabled={busy || !selectable}
                    onClick={() => selectCandidate(candidate)}
                  >
                    <StableMediaPreview src={candidate.preview_url} alt="" />
                    <span>{candidate.display_name}</span>
                  </button>
                );
              }) : null}
              {candidates.hasMore ? (
                <button type="button" disabled={busy || candidates.loadingMore} onClick={() => void candidates.loadMore()}>
                  {candidates.loadingMore ? "Loading" : "Load more"}
                </button>
              ) : null}
            </div>
          </>
        ) : (
          <>
            <label>
              <span>Upload reference</span>
              <input aria-label="Upload reference" type="file" accept="image/*" disabled={busy} onChange={selectFile} />
            </label>
            <p className="agent-chat__reference-source-limit">单张参考图不应超过 4 MB。</p>
          </>
        )}
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
