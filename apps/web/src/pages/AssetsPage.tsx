import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { v2Api } from "../api/v2Client.ts";
import { PageHeader } from "../components/Layout.tsx";
import { CloseIcon } from "../icons.tsx";
import {
  splitAssetLibraryTags,
  V2_ASSET_LIBRARY_CATEGORIES,
  v2AssetEntityTypeForCategory,
  v2AssetPreviewUrl,
} from "../features/assets/v2AssetLibraryModel.ts";
import { useRecommendedCatalog } from "../features/assets/useRecommendedCatalog.ts";
import { useV2AssetLibrary } from "../features/assets/useV2AssetLibrary.ts";
import type { V2AssetLibraryCategory, V2AssetLibraryEntityDetail, V2AssetLibraryEntitySummary, V2AssetLibraryScope } from "../types-v2.ts";

type AssetPageScope = V2AssetLibraryScope;

const AssetEntityViewer = lazy(() => import("../features/assets/AssetEntityViewer.tsx"));

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
  const assetLibraryRef = useRef<HTMLElement | null>(null);
  const selectedCardRef = useRef<HTMLButtonElement | null>(null);
  const catalog = useRecommendedCatalog(scope === "recommended");
  const recommendedReady = scope !== "recommended" || catalog.status?.status === "ready";
  const library = useV2AssetLibrary({ scope, category, search, enabled: recommendedReady });
  const fetchAssetDetail = library.fetchDetail;

  const restoreViewerFocus = useCallback(() => {
    if (selectedCardRef.current?.isConnected) {
      selectedCardRef.current.focus();
      return;
    }
    assetLibraryRef.current?.querySelector<HTMLButtonElement>('.v2-asset-library-tabs button[aria-selected="true"]')?.focus();
  }, []);

  const closeDetail = useCallback(({ restoreFocus = true }: { restoreFocus?: boolean } = {}) => {
    if (restoreFocus) restoreViewerFocus();
    setSelectedEntityId(null);
    setSelectedDetail(null);
    setDetailLoading(false);
    setFeedback(null);
  }, [restoreViewerFocus]);

  const displayedEntities = useMemo(() => {
    if (library.loading) return [];
    const currentEntities = library.entities.filter(
      (entity) => entity.scope === scope && entity.library_category === category,
    );
    if (scope !== "my" || !trashOpen) return currentEntities.filter((entity) => entity.status !== "trashed");
    const serverTrash = currentEntities.filter((entity) => entity.status === "trashed");
    const ids = new Set(serverTrash.map((entity) => entity.entity_id));
    return [
      ...serverTrash,
      ...trashedEntities.filter(
        (entity) => entity.scope === scope
          && entity.library_category === category
          && !ids.has(entity.entity_id),
      ),
    ];
  }, [category, library.entities, library.loading, scope, trashOpen, trashedEntities]);

  useEffect(() => {
    if (!selectedEntityId) return;
    let cancelled = false;
    setDetailLoading(true);
    setSelectedDetail(null);
    setFeedback(null);
    void fetchAssetDetail(selectedEntityId)
      .then((detail) => { if (!cancelled) setSelectedDetail(detail); })
      .catch((caught) => {
        if (cancelled) return;
        restoreViewerFocus();
        setFeedback(messageForError(caught, "Could not load asset details."));
        setSelectedEntityId(null);
      })
      .finally(() => { if (!cancelled) setDetailLoading(false); });
    return () => { cancelled = true; };
  }, [fetchAssetDetail, restoreViewerFocus, selectedEntityId]);

  function selectEntity(entity: V2AssetLibraryEntitySummary, trigger: HTMLButtonElement) {
    if (selectedEntityId === entity.entity_id) return;
    selectedCardRef.current = trigger;
    setSelectedDetail(null);
    setDetailLoading(true);
    setSelectedEntityId(entity.entity_id);
  }

  function changeScope(nextScope: AssetPageScope) {
    if (nextScope === scope) return;
    setTrashOpen(false);
    closeDetail({ restoreFocus: false });
    setScope(nextScope);
  }

  function changeCategory(nextCategory: V2AssetLibraryCategory) {
    if (nextCategory === category) return;
    setTrashOpen(false);
    closeDetail({ restoreFocus: false });
    setCategory(nextCategory);
  }

  return (
    <section ref={assetLibraryRef} className="v2-asset-library-page">
      <PageHeader title="Assets" subtitle="Reusable visual building blocks for every workflow." />
      <div className="v2-asset-library-controls">
        <div className="v2-asset-library-tabs" role="tablist" aria-label="Asset library scope">
          <button className={scope === "my" ? "is-active" : ""} type="button" role="tab" aria-selected={scope === "my"} onClick={() => changeScope("my")}>My Assets</button>
          <button className={scope === "recommended" ? "is-active" : ""} type="button" role="tab" aria-selected={scope === "recommended"} onClick={() => changeScope("recommended")}>Recommended Assets</button>
        </div>
        <div className="v2-asset-library-actions">
          <input aria-label="Search assets" value={search} placeholder="Search assets" onChange={(event) => setSearch(event.currentTarget.value)} />
          {scope === "my" ? <button className="small-action" type="button" onClick={() => setTrashOpen((value) => !value)}>{trashOpen ? "All assets" : "Trash"}</button> : null}
          {scope === "my" ? <button className="send-btn" type="button" onClick={() => setUploadOpen(true)}>Upload</button> : null}
        </div>
      </div>
      <div className="v2-asset-library-categories" role="tablist" aria-label="Asset category">
        {V2_ASSET_LIBRARY_CATEGORIES.map((item) => (
          <button key={item.id} className={category === item.id ? "is-active" : ""} type="button" role="tab" aria-selected={category === item.id} onClick={() => changeCategory(item.id)}>{item.label}</button>
        ))}
      </div>
      {scope === "recommended" && catalog.status?.status !== "ready" ? (
        <CatalogInstallStatus status={catalog.status} error={catalog.error} onRetry={() => void catalog.refresh()} />
      ) : null}
      {feedback ? <p className="v2-asset-library-feedback" role="status">{feedback}</p> : null}
      <div className="v2-asset-library-layout">
        <div>
          {library.error ? <p className="asset-library-status is-error">{library.error}</p> : null}
          {library.loading ? <p className="asset-library-status">Loading assets...</p> : null}
          {!library.loading && !displayedEntities.length && (!catalog.status || catalog.status.status === "ready") ? <p className="asset-library-empty">No assets found.</p> : null}
          <div className="v2-asset-library-grid">
            {displayedEntities.map((entity) => (
              <AssetEntityCard key={entity.entity_id} entity={entity} selected={selectedEntityId === entity.entity_id} onSelect={(trigger) => selectEntity(entity, trigger)} />
            ))}
          </div>
          {library.nextCursor && !trashOpen ? <button className="small-action v2-asset-library-load-more" type="button" disabled={library.loadingMore} onClick={() => void library.loadMore()}>{library.loadingMore ? "Loading..." : "Load more"}</button> : null}
        </div>
      </div>
      {selectedEntityId ? (
        <Suspense fallback={<AssetEntityViewerFallback onClose={closeDetail} />}>
          <AssetEntityViewer
            detail={selectedDetail}
            loading={detailLoading}
            onClose={closeDetail}
          />
        </Suspense>
      ) : null}
      {uploadOpen ? <AssetUploadDialog category={category} onClose={() => setUploadOpen(false)} onUploaded={async () => { setUploadOpen(false); await library.refresh(); }} /> : null}
    </section>
  );
}

function CatalogInstallStatus({ status, error, onRetry }: { status: ReturnType<typeof useRecommendedCatalog>["status"]; error: string | null; onRetry: () => void }) {
  const working = status?.status === "indexing";
  return (
    <div className={`v2-catalog-status ${error || status?.status === "invalid" ? "is-error" : ""}`}>
      <span>{error || status?.message || (working ? "Indexing recommended assets..." : "Extract Recommended Assets to data/assets/catalogs/recommended/ and refresh.")}</span>
      {status?.status === "invalid" || status?.status === "catalog_missing" || error ? <button className="small-action" type="button" onClick={onRetry}>Refresh</button> : null}
    </div>
  );
}

function AssetEntityCard({ entity, selected, onSelect }: { entity: V2AssetLibraryEntitySummary; selected: boolean; onSelect: (trigger: HTMLButtonElement) => void }) {
  const previewUrl = v2AssetPreviewUrl(entity);
  return (
    <button className={`v2-asset-entity-card v2-asset-discover-card ${selected ? "is-selected" : ""}`} type="button" aria-label={`Open asset ${entity.display_name}`} onClick={(event) => onSelect(event.currentTarget)}>
      <AssetCardMedia url={previewUrl} mediaType={entity.preview_member?.media_type} label={entity.display_name} />
      <span className="v2-asset-entity-card-title">{entity.display_name}</span>
    </button>
  );
}

export function AssetEntityViewerFallback({ onClose }: { onClose: () => void }) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handleKeyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === "Tab") {
        event.preventDefault();
        closeButtonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", handleKeyboard);
    const focusFrame = requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => {
      cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyboard);
    };
  }, [onClose]);

  return createPortal(
    <div className="v2-asset-viewer-backdrop">
      <button className="v2-asset-viewer-dismiss" type="button" aria-label="Dismiss asset viewer" onClick={onClose} />
      <section className="v2-asset-viewer" role="dialog" aria-modal="true" aria-label="Asset viewer">
        <button className="v2-asset-viewer-close" ref={closeButtonRef} type="button" aria-label="Close asset viewer" title="Close" onClick={onClose}><CloseIcon /></button>
        <div className="v2-asset-viewer-stage is-loading">Loading asset viewer...</div>
      </section>
    </div>,
    document.body,
  );
}

function AssetCardMedia({ url, mediaType, label }: { url: string | null; mediaType?: string | null; label: string }) {
  if (!url) return <span className="v2-asset-media is-empty">{label.slice(0, 1).toUpperCase()}</span>;
  if (mediaType === "video") return <video className="v2-asset-media is-card" src={url} preload="metadata" muted playsInline />;
  if (mediaType === "audio") return <span className="v2-asset-media is-empty">Audio</span>;
  return <img className="v2-asset-media is-card" src={url} alt={label} loading="lazy" decoding="async" />;
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
