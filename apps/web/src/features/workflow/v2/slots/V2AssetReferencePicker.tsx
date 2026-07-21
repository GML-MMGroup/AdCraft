import { useEffect, useMemo, useState, type FormEvent } from "react";
import { v2Api } from "../../../../api/v2Client.ts";
import {
  V2_ASSET_LIBRARY_CATEGORIES,
  v2AssetEntityTypeForCategory,
  v2AssetPreviewUrl,
} from "../../../assets/v2AssetLibraryModel.ts";
import { useRecommendedCatalog } from "../../../assets/useRecommendedCatalog.ts";
import { useV2AssetLibrary } from "../../../assets/useV2AssetLibrary.ts";
import type { V2AssetLibraryCategory, V2AssetLibraryEntityDetail, V2AssetLibraryEntitySummary } from "../../../../types-v2.ts";
import {
  buildV2ReferenceSelectionsRequest,
  hasV2ReferenceSelection,
  toggleV2ReferenceSelection,
  type V2ReferenceSelection,
} from "./v2ReferenceSelectionModel.ts";

type PickerTab = "upload" | "my" | "recommended";

type V2AssetReferencePickerProps = {
  workflowId: string;
  slotId: string;
  onAddReferences: (request: ReturnType<typeof buildV2ReferenceSelectionsRequest>) => Promise<boolean>;
  onClose: () => void;
};

function assetError(caught: unknown, fallback: string) {
  return caught instanceof Error && caught.message ? caught.message : fallback;
}

export function V2AssetReferencePicker({ workflowId, slotId, onAddReferences, onClose }: V2AssetReferencePickerProps) {
  const [tab, setTab] = useState<PickerTab>("my");
  const [category, setCategory] = useState<V2AssetLibraryCategory>("characters");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<V2AssetLibraryEntityDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selections, setSelections] = useState<V2ReferenceSelection[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const catalog = useRecommendedCatalog(tab === "recommended");
  const recommendedReady = tab !== "recommended" || catalog.status?.status === "ready";
  const scope = tab === "recommended" ? "recommended" : "my";
  const library = useV2AssetLibrary({ scope, category, search, enabled: tab !== "upload" && recommendedReady });

  useEffect(() => {
    setExpanded(null);
  }, [tab, category]);

  const selectionCount = selections.length;
  const request = useMemo(() => buildV2ReferenceSelectionsRequest(selections, "visual_reference"), [selections]);

  async function openEntity(entity: V2AssetLibraryEntitySummary) {
    setDetailLoading(true);
    setMessage(null);
    try {
      setExpanded(await library.fetchDetail(entity.entity_id));
    } catch (caught) {
      setMessage(assetError(caught, "Could not load asset members."));
    } finally {
      setDetailLoading(false);
    }
  }

  function toggleEntity(entity: V2AssetLibraryEntitySummary) {
    setSelections((current) => toggleV2ReferenceSelection(current, { selection_type: "entity", entity_id: entity.entity_id }));
  }

  function toggleMember(assetId: string, versionId: string) {
    setSelections((current) => {
      const withoutEntity = expanded ? current.filter((selection) => selection.selection_type !== "entity" || selection.entity_id !== expanded.entity_id) : current;
      return toggleV2ReferenceSelection(withoutEntity, { selection_type: "asset_version", asset_id: assetId, version_id: versionId });
    });
  }

  async function attach() {
    if (!selections.length) return;
    setBusy(true);
    setMessage(null);
    try {
      const attached = await onAddReferences(request);
      if (attached) onClose();
    } catch (caught) {
      setMessage(assetError(caught, "Could not attach the selected references."));
    } finally {
      setBusy(false);
    }
  }

  async function uploadAndSelect(detail: V2AssetLibraryEntityDetail) {
    const members = detail.members.map((member) => ({ selection_type: "asset_version" as const, asset_id: member.asset_id, version_id: member.version_id }));
    setSelections((current) => [...current, ...members.filter((member) => !hasV2ReferenceSelection(current, member))]);
    setExpanded(detail);
    setTab("my");
  }

  return (
    <div className="v2-asset-picker-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="v2-asset-picker" role="dialog" aria-modal="true" aria-label="Select slot references" data-workflow-id={workflowId} data-slot-id={slotId}>
        <header className="v2-asset-picker-heading">
          <div className="v2-asset-picker-tabs" role="tablist" aria-label="Reference source">
            <button className={tab === "upload" ? "is-active" : ""} type="button" role="tab" aria-selected={tab === "upload"} onClick={() => setTab("upload")}>Upload</button>
            <button className={tab === "my" ? "is-active" : ""} type="button" role="tab" aria-selected={tab === "my"} onClick={() => setTab("my")}>My Assets</button>
            <button className={tab === "recommended" ? "is-active" : ""} type="button" role="tab" aria-selected={tab === "recommended"} onClick={() => setTab("recommended")}>Recommended Assets</button>
          </div>
          <button className="icon-btn" type="button" aria-label="Close reference picker" onClick={onClose}>×</button>
        </header>
        {tab === "upload" ? <ReferenceUpload category={category} onUploaded={(detail) => void uploadAndSelect(detail)} /> : (
          <>
            <div className="v2-asset-picker-filters">
              <div className="v2-asset-library-categories" role="tablist" aria-label="Reference category">
                {V2_ASSET_LIBRARY_CATEGORIES.map((item) => <button key={item.id} className={category === item.id ? "is-active" : ""} type="button" onClick={() => setCategory(item.id)}>{item.label}</button>)}
              </div>
              <input aria-label="Search asset references" value={search} placeholder="Search assets" onChange={(event) => setSearch(event.currentTarget.value)} />
            </div>
            {tab === "recommended" && catalog.status?.status !== "ready" ? <PickerCatalogStatus status={catalog.status?.status} message={catalog.error || catalog.status?.message || null} onRetry={() => void catalog.install()} /> : null}
            {library.error ? <p className="v2-asset-picker-message is-error">{library.error}</p> : null}
            <div className="v2-asset-picker-content">
              <div className="v2-asset-picker-entities">
                {library.loading ? <p>Loading assets...</p> : null}
                {!library.loading && !library.entities.length && recommendedReady ? <p>No assets found.</p> : null}
                {library.entities.map((entity) => {
                  const selection = { selection_type: "entity" as const, entity_id: entity.entity_id };
                  return (
                    <div className={`v2-asset-picker-entity ${hasV2ReferenceSelection(selections, selection) ? "is-selected" : ""}`} key={entity.entity_id}>
                      <button className="v2-asset-picker-entity-main" type="button" onClick={() => toggleEntity(entity)} aria-pressed={hasV2ReferenceSelection(selections, selection)}>
                        <PickerPreview entity={entity} />
                        <span><strong>{entity.display_name}</strong><small>{entity.member_count} members</small></span>
                      </button>
                      <button className="small-action" type="button" onClick={() => void openEntity(entity)}>Views</button>
                    </div>
                  );
                })}
                {library.nextCursor ? <button className="small-action" type="button" disabled={library.loadingMore} onClick={() => void library.loadMore()}>{library.loadingMore ? "Loading..." : "Load more"}</button> : null}
              </div>
              <div className="v2-asset-picker-members">
                {detailLoading ? <p>Loading members...</p> : null}
                {!detailLoading && !expanded ? <p>Select Views to choose an exact member version.</p> : null}
                {expanded ? <>
                  <header><strong>{expanded.display_name}</strong><small>{expanded.scope === "recommended" ? expanded.catalog_source?.license ?? "Recommended" : "My Asset"}</small></header>
                  {expanded.members.map((member) => {
                    const selection = { selection_type: "asset_version" as const, asset_id: member.asset_id, version_id: member.version_id };
                    return <button className={`v2-asset-picker-member ${hasV2ReferenceSelection(selections, selection) ? "is-selected" : ""}`} key={member.member_id} type="button" aria-pressed={hasV2ReferenceSelection(selections, selection)} onClick={() => toggleMember(member.asset_id, member.version_id)}><PickerMemberPreview member={member} /><span>{member.display_name || member.semantic_type}</span></button>;
                  })}
                </> : null}
              </div>
            </div>
          </>
        )}
        {message ? <p className="v2-asset-picker-message is-error">{message}</p> : null}
        <footer className="v2-asset-picker-footer"><span>{selectionCount ? `${selectionCount} selected` : "Select entities or exact members"}</span><div><button className="small-action" type="button" onClick={onClose}>Cancel</button><button className="send-btn" type="button" disabled={!selectionCount || busy} onClick={() => void attach()}>{busy ? "Adding..." : "Add references"}</button></div></footer>
      </section>
    </div>
  );
}

function PickerCatalogStatus({ status, message, onRetry }: { status?: string; message: string | null; onRetry: () => void }) {
  return <p className="v2-asset-picker-message">{message || (status === "failed" ? "Recommended catalog installation failed." : "Preparing recommended assets...")} {status === "failed" ? <button className="small-action" type="button" onClick={onRetry}>Retry</button> : null}</p>;
}

function ReferenceUpload({ category, onUploaded }: { category: V2AssetLibraryCategory; onUploaded: (detail: V2AssetLibraryEntityDetail) => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [semanticTypes, setSemanticTypes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!files.length) { setError("Choose one or more media files."); return; }
    setBusy(true); setError(null);
    try {
      const form = new FormData();
      files.forEach((file) => form.append("files[]", file));
      form.append("entity_type", v2AssetEntityTypeForCategory(category));
      form.append("library_category", category);
      semanticTypes.forEach((role) => form.append("semantic_types[]", role));
      if (name.trim()) form.append("display_name", name.trim());
      onUploaded(await v2Api.uploadAssetLibraryEntity(form));
    } catch (caught) { setError(assetError(caught, "Could not upload the reference files.")); }
    finally { setBusy(false); }
  }
  return <form className="v2-reference-upload" onSubmit={(event) => void submit(event)}><label><span>Files</span><input type="file" multiple accept="image/*,video/*" onChange={(event) => { const next = Array.from(event.currentTarget.files ?? []); setFiles(next); setSemanticTypes(next.map((file) => defaultSemanticType(category, file))); }} /></label><label><span>Name</span><input value={name} onChange={(event) => setName(event.currentTarget.value)} /></label>{files.map((file, index) => <label key={`${file.name}-${index}`}><span>{file.name}</span><input value={semanticTypes[index] ?? "reference"} onChange={(event) => setSemanticTypes((current) => current.map((role, roleIndex) => roleIndex === index ? event.currentTarget.value : role))} /></label>)}{error ? <p className="v2-asset-picker-message is-error">{error}</p> : null}<button className="send-btn" type="submit" disabled={busy}>{busy ? "Uploading..." : "Upload and select"}</button></form>;
}

function PickerPreview({ entity }: { entity: V2AssetLibraryEntitySummary }) { const url = v2AssetPreviewUrl(entity); return url ? <img src={url} alt="" loading="lazy" decoding="async" /> : <span>{entity.display_name.slice(0, 1).toUpperCase()}</span>; }
function PickerMemberPreview({ member }: { member: V2AssetLibraryEntityDetail["members"][number] }) { const url = v2AssetPreviewUrl(member); return url ? <img src={url} alt="" loading="lazy" decoding="async" /> : <span>{member.semantic_type.slice(0, 1).toUpperCase()}</span>; }
function defaultSemanticType(category: V2AssetLibraryCategory, file: File) { if (category === "characters") return "character_main"; if (category === "scenes") return file.type.startsWith("video/") ? "scene_video" : "scene_main"; return file.type.startsWith("video/") ? "product_video" : "product_main"; }
