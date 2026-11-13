import { useState, type ReactNode } from "react";
import type { GuidedReferenceCandidateScopeV2, GuidedReferenceCandidateV2 } from "../../../types-v2.ts";
import { useTranslation } from "../../../i18n/useTranslation.ts";
import { StableMediaPreview } from "../../../workflow/StableMediaPreview.tsx";
import { guidedInteractionCopy } from "./guidedInteractionCopy.ts";
import type { ProductSourceDraftItem, SourceLibraryIdentity } from "./productSourceSelection.ts";
import { useGuidedReferenceCandidates } from "./useGuidedReferenceCandidates.ts";

export interface SourceImageLibraryOptions {
  workflowId: string;
  sourceRole: "character" | "scene";
  onSelect: (candidate: GuidedReferenceCandidateV2, catalog: SourceLibraryIdentity) => void;
}

export function SourceImageLibraryPicker({
  workflowId, sourceRole, onSelect, selected, busy, projectContent,
}: SourceImageLibraryOptions & {
  selected: ProductSourceDraftItem[];
  busy: boolean;
  projectContent: ReactNode;
}) {
  const t = useTranslation("en-US");
  const [scope, setScope] = useState<GuidedReferenceCandidateScopeV2>("project");
  const [query, setQuery] = useState("");
  const candidates = useGuidedReferenceCandidates({
    workflowId, referenceKind: sourceRole === "character" ? "character_main" : "scene_main",
    scope, query, enabled: scope !== "project",
  });
  return <>
    <div className="agent-chat__reference-source-scopes" role="tablist" aria-label={t("Asset library scope")}>
      {(["project", "mine", "recommended"] as const).map((item) => (
        <button key={item} type="button" role="tab" aria-selected={scope === item} disabled={busy}
          onClick={() => { setScope(item); setQuery(""); }}>
          {t(item === "project" ? "Project" : item === "mine" ? "My Assets" : "Recommended")}
        </button>
      ))}
    </div>
    {scope === "project" ? projectContent : <>
      <input type="search" aria-label={t("Search reference assets")} placeholder={t("Search reference assets")}
        value={query} disabled={busy} onChange={(event) => setQuery(event.currentTarget.value)} />
      <div className="agent-chat__reference-source-assets" aria-label={t("Reference candidates")}>
        {candidates.loading ? <p role="status">{t("Loading reference assets")}</p> : null}
        {!candidates.loading && candidates.error ? <div role="alert">
          <span>{guidedInteractionCopy(candidates.error, t)}</span>
          <button type="button" disabled={busy} onClick={() => void candidates.retry()}>{t("Retry")}</button>
        </div> : null}
        {!candidates.loading && !candidates.error && candidates.items.length === 0 ? <p>{t("No reference assets available")}</p> : null}
        {!candidates.loading && !candidates.error ? candidates.items.map((candidate) => {
          const isSelected = selected.some((item) => item.kind === "asset_version"
            && item.assetId === candidate.asset_id && item.versionId === candidate.asset_version_id);
          const selectable = candidate.selectable && candidate.media_type === "image"
            && Boolean(candidate.asset_id && candidate.asset_version_id && candidate.entity_id && candidate.member_id);
          return <button key={`${candidate.entity_id}:${candidate.member_id}`} type="button"
            className={isSelected ? "is-selected" : undefined} aria-label={t("Select {name}", { name: candidate.display_name })}
            aria-pressed={isSelected} disabled={busy || !selectable}
            onClick={() => {
              if (selectable && candidate.entity_id && candidate.member_id) onSelect(candidate, {
                source_scope: scope, entity_id: candidate.entity_id, member_id: candidate.member_id,
              });
            }}>
            <StableMediaPreview src={candidate.preview_url} alt="" />
            <span>{candidate.display_name}</span>
          </button>;
        }) : null}
        {candidates.hasMore ? <button type="button" disabled={busy || candidates.loadingMore}
          onClick={() => void candidates.loadMore()}>{t(candidates.loadingMore ? "Loading" : "Load more")}</button> : null}
      </div>
    </>}
  </>;
}
