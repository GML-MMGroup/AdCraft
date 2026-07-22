import { useEffect, useMemo, useState, type FormEvent } from "react";
import { v2Api } from "../api/v2Client.ts";
import { PageHeader } from "../components/Layout.tsx";
import {
  splitAssetLibraryTags,
  V2_ASSET_LIBRARY_CATEGORIES,
  v2AssetEntityDisplay,
  v2AssetEntityTypeForCategory,
  v2AssetPreviewUrl,
} from "../features/assets/v2AssetLibraryModel.ts";
import { useRecommendedCatalog } from "../features/assets/useRecommendedCatalog.ts";
import { useV2AssetLibrary } from "../features/assets/useV2AssetLibrary.ts";
import type { V2AssetLibraryCategory, V2AssetLibraryEntityDetail, V2AssetLibraryEntitySummary, V2AssetLibraryScope, V2AssetLibraryMember } from "../types-v2.ts";

type AssetPageScope = V2AssetLibraryScope;

function messageForError(caught: unknown, fallback: string) {
  return caught instanceof Error && caught.message ? caught.message : fallback;
}

export function AssetsPage() {
  const [scope, setScope] = useState<AssetPageScope>("my");
  const [category, setCategory] = useState<V2AssetLibraryCategory>("characters");
  const [search, setSearch] = useState("");
  const [trashOpen, setTrashOpen] = useState(false);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<V2AssetLibraryEntityDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [trashedEntities, setTrashedEntities] = useState<V2AssetLibraryEntitySummary[]>([]);
  const catalog = useRecommendedCatalog(scope === "recommended");
  const recommendedReady = scope !== "recommended" || catalog.status?.status === "ready";
  const library = useV2AssetLibrary({ scope, category, search, enabled: recommendedReady });
  const fetchAssetDetail = library.fetchDetail;

  const displayedEntities = useMemo(() => {
    if (scope !== "my" || !trashOpen) return library.entities.filter((entity) => entity.status !== "trashed");
    const serverTrash = library.entities.filter((entity) => entity.status === "trashed");
    const ids = new Set(serverTrash.map((entity) => entity.entity_id));
    return [...serverTrash, ...trashedEntities.filter((entity) => !ids.has(entity.entity_id))];
  }, [library.entities, scope, trashOpen, trashedEntities]);

  useEffect(() => {
    setTrashOpen(false);
    setSelectedEntityId(null);
    setSelectedDetail(null);
  }, [scope, category]);

  useEffect(() => {
    if (!selectedEntityId) return;
    let cancelled = false;
    setDetailLoading(true);
    setFeedback(null);
    void fetchAssetDetail(selectedEntityId)
      .then((detail) => { if (!cancelled) setSelectedDetail(detail); })
      .catch((caught) => { if (!cancelled) setFeedback(messageForError(caught, "Could not load asset details.")); })
      .finally(() => { if (!cancelled) setDetailLoading(false); });
    return () => { cancelled = true; };
  }, [fetchAssetDetail, selectedEntityId]);

  async function selectEntity(entity: V2AssetLibraryEntitySummary) {
    setSelectedEntityId(entity.entity_id);
  }

  async function saveRecommended(entity: V2AssetLibraryEntityDetail) {
    setFeedback(null);
    try {
      await v2Api.createAssetLibraryEntity({
        display_name: entity.display_name,
        entity_type: entity.entity_type,
        library_category: entity.library_category,
        description: entity.description ?? null,
        tags: entity.tags,
        source: { type: "recommended_entity", entity_id: entity.entity_id },
      });
      setFeedback(`${entity.display_name} was saved to My Assets.`);
    } catch (caught) {
      setFeedback(messageForError(caught, "Could not save this recommended asset."));
    }
  }

  async function updateDetail(request: { display_name?: string; description?: string | null; tags?: string[]; is_favorite?: boolean }) {
    if (!selectedDetail) return;
    setFeedback(null);
    try {
      const next = await v2Api.updateAssetLibraryEntity(selectedDetail.entity_id, request);
      setSelectedDetail(next);
      await library.refresh();
    } catch (caught) {
      setFeedback(messageForError(caught, "Could not update this asset."));
    }
  }

  async function trashSelected() {
    if (!selectedDetail) return;
    setFeedback(null);
    try {
      await v2Api.deleteAssetLibraryEntity(selectedDetail.entity_id);
      setTrashedEntities((current) => [{ ...selectedDetail, status: "trashed" }, ...current.filter((item) => item.entity_id !== selectedDetail.entity_id)]);
      setSelectedDetail((current) => current ? { ...current, status: "trashed" } : current);
      await library.refresh();
    } catch (caught) {
      setFeedback(messageForError(caught, "Could not move this asset to Trash."));
    }
  }

  async function restoreSelected() {
    if (!selectedDetail) return;
    setFeedback(null);
    try {
      const restored = await v2Api.restoreAssetLibraryEntity(selectedDetail.entity_id);
      setSelectedDetail(restored);
      setTrashedEntities((current) => current.filter((item) => item.entity_id !== restored.entity_id));
      await library.refresh();
    } catch (caught) {
      setFeedback(messageForError(caught, "Could not restore this asset."));
    }
  }

  return (
    <section className="v2-asset-library-page">
      <PageHeader title="Assets" subtitle="Reusable visual building blocks for every workflow." />
      <div className="v2-asset-library-controls">
        <div className="v2-asset-library-tabs" role="tablist" aria-label="Asset library scope">
          <button className={scope === "my" ? "is-active" : ""} type="button" role="tab" aria-selected={scope === "my"} onClick={() => setScope("my")}>My Assets</button>
          <button className={scope === "recommended" ? "is-active" : ""} type="button" role="tab" aria-selected={scope === "recommended"} onClick={() => setScope("recommended")}>Recommended Assets</button>
        </div>
        <div className="v2-asset-library-actions">
          <input aria-label="Search assets" value={search} placeholder="Search assets" onChange={(event) => setSearch(event.currentTarget.value)} />
          {scope === "my" ? <button className="small-action" type="button" onClick={() => setTrashOpen((value) => !value)}>{trashOpen ? "All assets" : "Trash"}</button> : null}
          {scope === "my" ? <button className="send-btn" type="button" onClick={() => setUploadOpen(true)}>Upload</button> : null}
        </div>
      </div>
      <div className="v2-asset-library-categories" role="tablist" aria-label="Asset category">
        {V2_ASSET_LIBRARY_CATEGORIES.map((item) => (
          <button key={item.id} className={category === item.id ? "is-active" : ""} type="button" role="tab" aria-selected={category === item.id} onClick={() => setCategory(item.id)}>{item.label}</button>
        ))}
      </div>
      {scope === "recommended" && catalog.status?.status !== "ready" ? (
        <CatalogInstallStatus status={catalog.status} error={catalog.error} onRetry={() => void catalog.install()} />
      ) : null}
      {feedback ? <p className="v2-asset-library-feedback" role="status">{feedback}</p> : null}
      <div className="v2-asset-library-layout">
        <div>
          {library.error ? <p className="asset-library-status is-error">{library.error}</p> : null}
          {library.loading ? <p className="asset-library-status">Loading assets...</p> : null}
          {!library.loading && !displayedEntities.length && (!catalog.status || catalog.status.status === "ready") ? <p className="asset-library-empty">No assets found.</p> : null}
          <div className="v2-asset-library-grid">
            {displayedEntities.map((entity) => (
              <AssetEntityCard key={entity.entity_id} entity={entity} selected={selectedEntityId === entity.entity_id} onSelect={() => void selectEntity(entity)} />
            ))}
          </div>
          {library.nextCursor && !trashOpen ? <button className="small-action v2-asset-library-load-more" type="button" disabled={library.loadingMore} onClick={() => void library.loadMore()}>{library.loadingMore ? "Loading..." : "Load more"}</button> : null}
        </div>
        <AssetDetailPanel
          detail={selectedDetail}
          loading={detailLoading}
          feedback={feedback}
          onClose={() => { setSelectedEntityId(null); setSelectedDetail(null); }}
          onSaveRecommended={() => selectedDetail && void saveRecommended(selectedDetail)}
          onUpdate={updateDetail}
          onTrash={() => void trashSelected()}
          onRestore={() => void restoreSelected()}
        />
      </div>
      {uploadOpen ? <AssetUploadDialog category={category} onClose={() => setUploadOpen(false)} onUploaded={async () => { setUploadOpen(false); await library.refresh(); }} /> : null}
    </section>
  );
}

function CatalogInstallStatus({ status, error, onRetry }: { status: ReturnType<typeof useRecommendedCatalog>["status"]; error: string | null; onRetry: () => void }) {
  const working = status?.status === "downloading" || status?.status === "verifying" || status?.status === "installing";
  const progress = status?.progress_total ? `${status.progress_current ?? 0} / ${status.progress_total}` : null;
  return (
    <div className={`v2-catalog-status ${error || status?.status === "failed" ? "is-error" : ""}`}>
      <span>{error || status?.message || (working ? `Preparing recommended assets${progress ? ` · ${progress}` : ""}` : "Recommended assets are not installed.")}</span>
      {status?.status === "failed" || error ? <button className="small-action" type="button" onClick={onRetry}>Retry</button> : null}
    </div>
  );
}

function AssetEntityCard({ entity, selected, onSelect }: { entity: V2AssetLibraryEntitySummary; selected: boolean; onSelect: () => void }) {
  const previewUrl = v2AssetPreviewUrl(entity);
  return (
    <button className={`v2-asset-entity-card ${selected ? "is-selected" : ""}`} type="button" onClick={onSelect}>
      <AssetMedia url={previewUrl} mediaType={entity.preview_member?.media_type} label={entity.display_name} />
      <span className="v2-asset-entity-card-body">
        <strong>{entity.display_name}</strong>
        <small>{v2AssetEntityDisplay(entity)}</small>
        <span className="v2-asset-entity-tags">{entity.tags.slice(0, 3).map((tag) => <i key={tag}>{tag}</i>)}</span>
      </span>
    </button>
  );
}

function AssetDetailPanel({
  detail,
  loading,
  feedback,
  onClose,
  onSaveRecommended,
  onUpdate,
  onTrash,
  onRestore,
}: {
  detail: V2AssetLibraryEntityDetail | null;
  loading: boolean;
  feedback: string | null;
  onClose: () => void;
  onSaveRecommended: () => void;
  onUpdate: (request: { display_name?: string; description?: string | null; tags?: string[]; is_favorite?: boolean }) => Promise<void>;
  onTrash: () => void;
  onRestore: () => void;
}) {
  const [draft, setDraft] = useState({ displayName: "", description: "", tags: "" });
  useEffect(() => {
    setDraft({ displayName: detail?.display_name ?? "", description: detail?.description ?? "", tags: detail?.tags.join(", ") ?? "" });
  }, [detail]);
  if (!detail && !loading) return <aside className="v2-asset-detail-panel is-empty">Select an asset to view its members.</aside>;
  if (loading || !detail) return <aside className="v2-asset-detail-panel">Loading asset details...</aside>;
  const isRecommended = detail.scope === "recommended";
  const trashed = detail.status === "trashed";
  return (
    <aside className="v2-asset-detail-panel">
      <div className="v2-asset-detail-heading">
        <div><small>{detail.library_category}</small><h2>{detail.display_name}</h2></div>
        <button className="icon-btn" type="button" aria-label="Close asset details" onClick={onClose}>×</button>
      </div>
      <div className="v2-asset-member-grid">
        {detail.members.map((member) => <AssetMember key={member.member_id} member={member} />)}
      </div>
      {detail.description ? <p className="v2-asset-detail-description">{detail.description}</p> : null}
      {isRecommended ? (
        <>
          <dl className="v2-asset-provenance">
            <div><dt>Source</dt><dd>{detail.catalog_source_url ?? "Catalog"}</dd></div>
            <div><dt>License</dt><dd>{detail.license_id ?? "Not specified"}</dd></div>
            <div><dt>Attribution</dt><dd>{detail.attribution ?? "Not specified"}</dd></div>
          </dl>
          <button className="send-btn" type="button" onClick={onSaveRecommended}>Save to My Assets</button>
        </>
      ) : (
        <form className="v2-asset-detail-form" onSubmit={(event) => { event.preventDefault(); void onUpdate({ display_name: draft.displayName.trim(), description: draft.description.trim() || null, tags: splitAssetLibraryTags(draft.tags) }); }}>
          <label><span>Name</span><input value={draft.displayName} onChange={(event) => setDraft((value) => ({ ...value, displayName: event.currentTarget.value }))} /></label>
          <label><span>Description</span><textarea value={draft.description} onChange={(event) => setDraft((value) => ({ ...value, description: event.currentTarget.value }))} /></label>
          <label><span>Tags</span><input value={draft.tags} onChange={(event) => setDraft((value) => ({ ...value, tags: event.currentTarget.value }))} /></label>
          <div className="v2-asset-detail-actions">
            <button className="small-action" type="button" aria-pressed={detail.is_favorite} onClick={() => void onUpdate({ is_favorite: !detail.is_favorite })}>{detail.is_favorite ? "Unfavorite" : "Favorite"}</button>
            <button className="small-action" type="submit">Save</button>
            {trashed ? <button className="small-action" type="button" onClick={onRestore}>Restore</button> : <button className="small-action is-danger" type="button" onClick={onTrash}>Move to Trash</button>}
          </div>
        </form>
      )}
      {feedback ? <p className="v2-asset-library-feedback">{feedback}</p> : null}
    </aside>
  );
}

function AssetMember({ member }: { member: V2AssetLibraryMember }) {
  return <figure className="v2-asset-member"><AssetMedia url={v2AssetPreviewUrl(member)} mediaType={member.media_type} label={member.display_name || member.semantic_type} /><figcaption>{member.semantic_type}</figcaption></figure>;
}

function AssetMedia({ url, mediaType, label }: { url: string | null; mediaType?: string | null; label: string }) {
  if (!url) return <span className="v2-asset-media is-empty">{label.slice(0, 1).toUpperCase()}</span>;
  if (mediaType === "video") return <video className="v2-asset-media" src={url} preload="metadata" muted playsInline controls />;
  if (mediaType === "audio") return <audio className="v2-asset-audio" src={url} controls preload="metadata" />;
  return <img className="v2-asset-media" src={url} alt={label} loading="lazy" decoding="async" />;
}

function AssetUploadDialog({ category, onClose, onUploaded }: { category: V2AssetLibraryCategory; onClose: () => void; onUploaded: () => Promise<void> }) {
  const [files, setFiles] = useState<File[]>([]);
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [semanticTypes, setSemanticTypes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function changeFiles(nextFiles: FileList | null) {
    const next = Array.from(nextFiles ?? []);
    setFiles(next);
    setSemanticTypes((current) => next.map((file, index) => current[index] || defaultSemanticType(category, file)));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!files.length) { setError("Choose one or more media files."); return; }
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      files.forEach((file) => form.append("files[]", file));
      form.append("entity_type", v2AssetEntityTypeForCategory(category));
      form.append("library_category", category);
      semanticTypes.forEach((semanticType) => form.append("semantic_types[]", semanticType));
      if (displayName.trim()) form.append("display_name", displayName.trim());
      if (description.trim()) form.append("description", description.trim());
      splitAssetLibraryTags(tags).forEach((tag) => form.append("tags[]", tag));
      await v2Api.uploadAssetLibraryEntity(form);
      await onUploaded();
    } catch (caught) {
      setError(messageForError(caught, "Upload failed. Your selected files and metadata are still available to edit."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="v2-asset-dialog-backdrop" role="presentation">
      <form className="v2-asset-upload-dialog" onSubmit={(event) => void submit(event)}>
        <div className="v2-asset-detail-heading"><h2>Upload Assets</h2><button className="icon-btn" type="button" aria-label="Close upload" onClick={onClose}>×</button></div>
        <label><span>Files</span><input type="file" multiple accept="image/*,video/*,audio/*" onChange={(event) => changeFiles(event.currentTarget.files)} /></label>
        <label><span>Name</span><input value={displayName} onChange={(event) => setDisplayName(event.currentTarget.value)} /></label>
        <label><span>Description</span><textarea value={description} onChange={(event) => setDescription(event.currentTarget.value)} /></label>
        <label><span>Tags</span><input value={tags} placeholder="campaign, reusable" onChange={(event) => setTags(event.currentTarget.value)} /></label>
        {files.length ? <div className="v2-asset-upload-members">{files.map((file, index) => <label key={`${file.name}-${index}`}><span>{file.name}</span><input value={semanticTypes[index] ?? "reference"} onChange={(event) => setSemanticTypes((current) => current.map((value, itemIndex) => itemIndex === index ? event.currentTarget.value : value))} /></label>)}</div> : null}
        {error ? <p className="v2-asset-library-feedback is-error">{error}</p> : null}
        <div className="v2-asset-detail-actions"><button className="small-action" type="button" onClick={onClose}>Cancel</button><button className="send-btn" type="submit" disabled={busy}>{busy ? "Uploading..." : "Upload"}</button></div>
      </form>
    </div>
  );
}

function defaultSemanticType(category: V2AssetLibraryCategory, file: File) {
  if (category === "characters") return "character_main";
  if (category === "scenes") return file.type.startsWith("video/") ? "scene_video" : "scene_main";
  return file.type.startsWith("video/") ? "product_video" : "product_main";
}
