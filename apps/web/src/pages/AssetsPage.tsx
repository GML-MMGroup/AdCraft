import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api, mediaUrl } from "../api/client";
import { ASSET_LIBRARY_UPLOAD_EVENT, assetLibraryUploadOptionsForKind, isSupportedUploadFile, type AssetLibraryRefreshEventDetail } from "../api/workflowNormalizers";
import { mediaAssetOriginalPath, mediaAssetPreviewPath } from "../workflow/mediaPreview";
import { formatV2AssetLocator } from "../workflow-v2/assetLocators.ts";
import { PageHeader } from "../components/Layout";
import type {
  AssetLibraryEntityDetail,
  AssetLibraryEntitySummary,
  AssetLibraryEntityType,
  AssetLibraryGroupUploadKind,
  AssetLibraryUploadKind,
  AssetUploadBatchResponse,
  UploadedAsset,
} from "../types";

type AssetLibraryTab = AssetLibraryEntityType | "all";

const ASSET_LIBRARY_TABS: Array<{ id: AssetLibraryTab; label: string }> = [
  { id: "all", label: "All" },
  { id: "character", label: "Characters" },
  { id: "scene", label: "Scenes" },
  { id: "storyboard_shot", label: "Storyboard Shots" },
  { id: "video_clip", label: "Video Clips" },
  { id: "bgm", label: "BGM" },
  { id: "style_reference", label: "Styles" },
  { id: "uploaded_reference", label: "Uploads" },
];

const ASSET_LIBRARY_UPLOAD_KIND_OPTIONS: Array<{ value: AssetLibraryUploadKind; label: string }> = [
  { value: "", label: "Auto / Uploaded reference" },
  { value: "character", label: "Character reference" },
  { value: "scene", label: "Scene reference" },
  { value: "style_reference", label: "Style reference" },
  { value: "bgm", label: "BGM / Audio" },
  { value: "storyboard_image", label: "Storyboard image" },
  { value: "storyboard_video", label: "Storyboard video" },
];

const ASSET_LIBRARY_GROUP_UPLOAD_OPTIONS: Array<{ value: AssetLibraryGroupUploadKind; label: string }> = [
  { value: "character", label: "Character set" },
  { value: "scene", label: "Scene set" },
  { value: "storyboard_shot", label: "Storyboard shot" },
];

const ASSET_LIBRARY_GROUP_UPLOAD_SPECS: Record<AssetLibraryGroupUploadKind, { entityType: AssetLibraryEntityType; slots: Array<{ semanticType: string; label: string }> }> = {
  character: {
    entityType: "character",
    slots: [
      { semanticType: "character_main", label: "Main image" },
      { semanticType: "character_face_id", label: "Face image" },
      { semanticType: "character_three_view", label: "Three-view image" },
    ],
  },
  scene: {
    entityType: "scene",
    slots: [
      { semanticType: "scene_main", label: "Main image" },
      { semanticType: "scene_multi_view", label: "Multi-view image" },
    ],
  },
  storyboard_shot: {
    entityType: "storyboard_shot",
    slots: [
      { semanticType: "storyboard_image", label: "Storyboard image" },
      { semanticType: "storyboard_video", label: "Storyboard video" },
    ],
  },
};

const SEMANTIC_GROUP_ORDER = [
  "character_main",
  "character_face_id",
  "character_three_view",
  "character_concept",
  "scene_main",
  "scene_multi_view",
  "style_reference",
  "storyboard_image",
  "storyboard_video",
  "bgm",
  "uploaded_reference",
];

export function AssetsPage() {
  const [activeTab, setActiveTab] = useState<AssetLibraryTab>("all");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [entities, setEntities] = useState<AssetLibraryEntitySummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<AssetLibraryEntityDetail | null>(null);
  const [detailDraft, setDetailDraft] = useState({ display_name: "", description: "", tags: "", reuse_policy: "" });
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  const applySelectedDetail = useCallback((detail: AssetLibraryEntityDetail) => {
    setSelectedDetail(detail);
    setDetailDraft({
      display_name: detail.display_name ?? "",
      description: detail.description ?? "",
      tags: detail.tags.join(", "),
      reuse_policy: detail.reuse_policy ?? "",
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadAssetLibraryEntities() {
      setLoading(true);
      setError("");
      try {
        const response = await api.listAssetLibraryEntities({
          entity_type: activeTab === "all" ? undefined : activeTab,
          q: search,
          tag: tagFilter,
          include_archived: includeArchived,
        });
        if (cancelled) return;
        setEntities(response.entities ?? []);
      } catch (loadError) {
        if (cancelled) return;
        setEntities([]);
        setError(formatAssetLibraryPageError(loadError));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadAssetLibraryEntities();
    return () => {
      cancelled = true;
    };
  }, [activeTab, includeArchived, search, tagFilter]);

  useEffect(() => {
    if (!selectedEntityId) {
      setSelectedDetail(null);
      setDetailDraft({ display_name: "", description: "", tags: "", reuse_policy: "" });
      return;
    }

    const requestEntityId = selectedEntityId;
    let cancelled = false;
    async function loadAssetLibraryEntityDetail() {
      setDetailLoading(true);
      setDetailError("");
      try {
        const detail = await api.assetLibraryEntity(requestEntityId);
        if (cancelled) return;
        applySelectedDetail(detail);
      } catch (loadError) {
        if (cancelled) return;
        setSelectedDetail(null);
        setDetailError(formatAssetLibraryPageError(loadError));
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    }

    void loadAssetLibraryEntityDetail();
    return () => {
      cancelled = true;
    };
  }, [applySelectedDetail, selectedEntityId]);

  const visibleTags = useMemo(() => {
    const tags = new Set<string>();
    entities.forEach((asset) => asset.tags.forEach((tag) => tags.add(tag)));
    return Array.from(tags).sort((a, b) => a.localeCompare(b));
  }, [entities]);

  const refreshCurrentList = useCallback(async () => {
    const response = await api.listAssetLibraryEntities({
      entity_type: activeTab === "all" ? undefined : activeTab,
      q: search,
      tag: tagFilter,
      include_archived: includeArchived,
    });
    setEntities(response.entities ?? []);
  }, [activeTab, includeArchived, search, tagFilter]);

  const refreshAfterUpload = useCallback(async (asset?: AssetLibraryRefreshEventDetail | null, explicitEntityId?: string | null) => {
    await refreshCurrentList();
    const relatedEntityId = explicitEntityId ?? asset?.library_entity_id ?? asset?.library_entity?.entity_id ?? selectedEntityId;
    if (!relatedEntityId) return;
    const detail = await api.assetLibraryEntity(relatedEntityId);
    setSelectedEntityId(relatedEntityId);
    applySelectedDetail(detail);
  }, [applySelectedDetail, refreshCurrentList, selectedEntityId]);

  useEffect(() => {
    function handleExternalUpload(event: Event) {
      const asset = (event as CustomEvent<AssetLibraryRefreshEventDetail>).detail;
      void refreshAfterUpload(asset);
    }

    window.addEventListener(ASSET_LIBRARY_UPLOAD_EVENT, handleExternalUpload);
    return () => {
      window.removeEventListener(ASSET_LIBRARY_UPLOAD_EVENT, handleExternalUpload);
    };
  }, [refreshAfterUpload]);

  async function saveDetailPatch() {
    if (!selectedEntityId) return;
    try {
      const detail = await api.patchAssetLibraryEntity(selectedEntityId, {
        display_name: detailDraft.display_name,
        description: detailDraft.description,
        tags: splitTags(detailDraft.tags),
        reuse_policy: detailDraft.reuse_policy || null,
      });
      applySelectedDetail(detail);
      await refreshCurrentList();
      setDetailError("Saved.");
    } catch (patchError) {
      setDetailError(formatAssetLibraryPageError(patchError));
    }
  }

  async function toggleArchive() {
    if (!selectedEntityId || !selectedDetail) return;
    try {
      const detail = await api.patchAssetLibraryEntity(selectedEntityId, {
        is_archived: !selectedDetail.is_archived,
      });
      if (detail.is_archived) setIncludeArchived(true);
      applySelectedDetail(detail);
      await refreshCurrentList();
    } catch (patchError) {
      setDetailError(formatAssetLibraryPageError(patchError));
    }
  }

  return (
    <section className="content-wrap asset-library-page">
      <PageHeader title="Asset Library" subtitle="Manage reusable generated entities saved from workflows." />

      <div className="asset-library-toolbar">
        <div className="toolbar-row" role="tablist" aria-label="Asset library categories">
          {ASSET_LIBRARY_TABS.map((tab) => (
            <button key={tab.id} className={`filter-btn ${activeTab === tab.id ? "is-active" : ""}`} type="button" role="tab" aria-selected={activeTab === tab.id} onClick={() => setActiveTab(tab.id)}>
              {tab.label}
            </button>
          ))}
        </div>
        <div className="toolbar-row asset-library-filters">
          <input className="search-box" placeholder="Search library" value={search} onChange={(event) => setSearch(event.target.value)} />
          <input className="search-box" placeholder="Filter tag" list="asset-library-tags" value={tagFilter} onChange={(event) => setTagFilter(event.target.value)} />
          <datalist id="asset-library-tags">
            {visibleTags.map((tag) => (
              <option key={tag} value={tag} />
            ))}
          </datalist>
          <button className={`filter-btn ${includeArchived ? "is-active" : ""}`} type="button" onClick={() => setIncludeArchived((value) => !value)}>
            Archived
          </button>
        </div>
      </div>

      <AssetLibraryUploadForm onUploaded={(asset) => refreshAfterUpload(asset)} />
      <AssetLibraryGroupUploadForm onUploaded={(response) => refreshAfterUpload(response.assets[0] ?? null, response.library_entity_id ?? response.library_entity?.entity_id)} />

      {error ? <div className="asset-library-status is-error">{error}</div> : null}
      {loading ? <div className="asset-library-status">Loading asset library...</div> : null}

      <div className="asset-library-layout">
        <div className="asset-library-grid" aria-label="Asset library entities">
          {!loading && !entities.length ? <div className="asset-library-empty">No saved asset library entities.</div> : null}
          {entities.map((asset) => (
            <button
              key={asset.entity_id}
              className={`asset-library-card ${asset.is_archived ? "is-archived" : ""}`}
              data-asset-library-card={asset.entity_id}
              type="button"
              onClick={() => setSelectedEntityId(asset.entity_id)}
            >
              <AssetLibraryPreview asset={asset.preview_asset} fallbackUrl={asset.preview_url ?? asset.thumbnail_url ?? ""} label={asset.display_name} />
              <div className="asset-library-card-body">
                <div className="asset-library-card-title">
                  <h3>{asset.display_name}</h3>
                  {asset.is_archived ? <span>Archived</span> : null}
                </div>
                <p>{asset.entity_type}{asset.semantic_type ? ` · ${asset.semantic_type}` : ""}</p>
                <div className="asset-library-tags">
                  {asset.tags.map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>
                <div className="card-meta">
                  <span>{asset.asset_count} assets</span>
                  <span>{asset.source_node_id ?? "workflow entity"}</span>
                </div>
              </div>
            </button>
          ))}
        </div>

        <aside className="asset-library-detail-panel" aria-label="Asset library entity detail">
          {!selectedEntityId ? <div className="asset-library-empty">Select an entity to inspect assets and metadata.</div> : null}
          {detailLoading ? <div className="asset-library-status">Loading detail...</div> : null}
          {detailError ? <div className={`asset-library-status ${detailError === "Saved." ? "is-success" : "is-error"}`}>{detailError}</div> : null}
          {selectedDetail ? (
            <>
              <div className="asset-library-detail-heading">
                <div>
                  <span>{selectedDetail.entity_type}</span>
                  <h2>{selectedDetail.display_name}</h2>
                </div>
                <button className="small-action" type="button" onClick={() => void toggleArchive()}>
                  {selectedDetail.is_archived ? "Unarchive" : "Archive"}
                </button>
              </div>
              <div className="asset-library-detail-meta">
                <span>workflow {selectedDetail.source_workflow_id ?? "unknown"}</span>
                <span>node {selectedDetail.source_node_id ?? "unknown"}</span>
                <span>entity {selectedDetail.source_entity_id ?? selectedDetail.entity_id}</span>
              </div>
              <div className="asset-library-edit-grid">
                <label>
                  <span>Name</span>
                  <input value={detailDraft.display_name} onChange={(event) => setDetailDraft((draft) => ({ ...draft, display_name: event.target.value }))} />
                </label>
                <label>
                  <span>Tags</span>
                  <input value={detailDraft.tags} placeholder="tag-a, tag-b" onChange={(event) => setDetailDraft((draft) => ({ ...draft, tags: event.target.value }))} />
                </label>
                <label>
                  <span>Reuse policy</span>
                  <input value={detailDraft.reuse_policy} onChange={(event) => setDetailDraft((draft) => ({ ...draft, reuse_policy: event.target.value }))} />
                </label>
                <label className="asset-library-description-field">
                  <span>Description</span>
                  <textarea value={detailDraft.description} onChange={(event) => setDetailDraft((draft) => ({ ...draft, description: event.target.value }))} />
                </label>
              </div>
              <button className="send-btn asset-library-save-btn" type="button" onClick={() => void saveDetailPatch()}>
                Save details
              </button>
              <AssetLibraryGroupedAssets detail={selectedDetail} />
            </>
          ) : null}
        </aside>
      </div>
    </section>
  );
}

function AssetLibraryUploadForm({ onUploaded }: { onUploaded: (asset: UploadedAsset) => Promise<void> | void }) {
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadKind, setUploadKind] = useState<AssetLibraryUploadKind>("");
  const [uploadName, setUploadName] = useState("");
  const [uploadTags, setUploadTags] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState("");

  async function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setUploadStatus("");
    if (!uploadFile) {
      setUploadStatus("Choose a file before uploading.");
      return;
    }
    if (!isSupportedUploadFile(uploadFile)) {
      setUploadStatus("Unsupported file type. Upload image, video, audio, or document files.");
      return;
    }

    const uploadOptions = assetLibraryUploadOptionsForKind(uploadKind, {
      display_name: uploadName,
      tags: splitTags(uploadTags),
    });

    setUploading(true);
    try {
      const asset = await api.uploadAsset(uploadFile, uploadOptions);
      await api.listAssets();
      await onUploaded(asset);
      setUploadStatus(asset.library_entity_id || asset.library_entity ? "Uploaded to Asset Library." : "Uploaded. Asset Library link missing from backend response.");
      setUploadFile(null);
      setUploadName("");
      setUploadTags("");
    } catch (uploadError) {
      setUploadStatus(`${formatAssetLibraryPageError(uploadError)} Multi-file uploads show one request-level error.`);
    } finally {
      setUploading(false);
    }
  }

  return (
    <form className="asset-library-upload-form" onSubmit={(event) => void submitUpload(event)}>
      <div className="asset-library-upload-grid">
        <label>
          <span>File</span>
          <input
            type="file"
            accept="image/*,video/*,audio/*,.pdf,.txt,.md,.doc,.docx,application/pdf,text/plain,text/markdown,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <label>
          <span>Type</span>
          <select name="upload_kind" value={uploadKind} onChange={(event) => setUploadKind(event.target.value as AssetLibraryUploadKind)}>
            {ASSET_LIBRARY_UPLOAD_KIND_OPTIONS.map((option) => (
              <option key={option.value || "auto"} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Name</span>
          <input value={uploadName} placeholder={uploadFile?.name ?? "Optional name"} onChange={(event) => setUploadName(event.target.value)} />
        </label>
        <label>
          <span>Tags</span>
          <input value={uploadTags} placeholder="tag-a, tag-b" onChange={(event) => setUploadTags(event.target.value)} />
        </label>
      </div>
      <div className="asset-library-upload-actions">
        <button className="send-btn" type="submit" disabled={uploading}>
          {uploading ? "Uploading..." : "Upload to Library"}
        </button>
        {uploadStatus ? <span className={uploadStatus.startsWith("Uploaded") ? "is-success" : "is-error"}>{uploadStatus}</span> : null}
      </div>
    </form>
  );
}

function AssetLibraryGroupUploadForm({ onUploaded }: { onUploaded: (response: AssetUploadBatchResponse) => Promise<void> | void }) {
  const [groupKind, setGroupKind] = useState<AssetLibraryGroupUploadKind>("character");
  const [groupName, setGroupName] = useState("");
  const [groupTags, setGroupTags] = useState("");
  const [groupSlotFiles, setGroupSlotFiles] = useState<Record<string, File | null>>({});
  const [groupUploading, setGroupUploading] = useState(false);
  const [groupStatus, setGroupStatus] = useState("");
  const spec = ASSET_LIBRARY_GROUP_UPLOAD_SPECS[groupKind];

  async function submitGroupUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setGroupStatus("");
    const selectedEntries = spec.slots
      .map((slot) => ({ semanticType: slot.semanticType, file: groupSlotFiles[slot.semanticType] }))
      .filter((entry): entry is { semanticType: string; file: File } => Boolean(entry.file));
    if (selectedEntries.length < 2) {
      setGroupStatus("Choose at least two files for grouped upload.");
      return;
    }
    const unsupportedFiles = selectedEntries.filter((entry) => !isSupportedUploadFile(entry.file));
    if (unsupportedFiles.length) {
      setGroupStatus(`Unsupported file type. Upload image, video, audio, or document files: ${unsupportedFiles.map((entry) => entry.file.name).join(", ")}`);
      return;
    }

    const groupFiles = selectedEntries.map((entry) => entry.file);
    const groupOptions = {
      entity_type: spec.entityType,
      display_name: groupName,
      tags: splitTags(groupTags),
      assets_metadata: selectedEntries.map((entry) => ({
        filename: entry.file.name,
        semantic_type: entry.semanticType,
      })),
    };

    setGroupUploading(true);
    try {
      const response = await api.uploadAssetGroup(groupFiles, groupOptions);
      await api.listAssets();
      await onUploaded(response);
      setGroupStatus("Grouped upload saved to Asset Library.");
      setGroupSlotFiles({});
      setGroupName("");
      setGroupTags("");
    } catch (groupError) {
      setGroupStatus(`Grouped upload failed. No partial assets were saved. ${formatAssetLibraryPageError(groupError)}`);
    } finally {
      setGroupUploading(false);
    }
  }

  return (
    <details className="asset-library-group-upload">
      <summary>Advanced grouped upload</summary>
      <form className="asset-library-upload-form" onSubmit={(event) => void submitGroupUpload(event)}>
        <div className="asset-library-upload-grid is-grouped">
          <label>
            <span>Group type</span>
            <select value={groupKind} onChange={(event) => setGroupKind(event.target.value as AssetLibraryGroupUploadKind)}>
              {ASSET_LIBRARY_GROUP_UPLOAD_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Name</span>
            <input value={groupName} placeholder="Optional group name" onChange={(event) => setGroupName(event.target.value)} />
          </label>
          <label>
            <span>Tags</span>
            <input value={groupTags} placeholder="tag-a, tag-b" onChange={(event) => setGroupTags(event.target.value)} />
          </label>
        </div>
        <div className="asset-library-group-slots">
          {spec.slots.map((slot) => (
            <label key={slot.semanticType}>
              <span>{slot.label}</span>
              <input
                type="file"
                accept="image/*,video/*,audio/*,.pdf,.txt,.md,.doc,.docx,application/pdf,text/plain,text/markdown,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={(event) => setGroupSlotFiles((current) => ({ ...current, [slot.semanticType]: event.target.files?.[0] ?? null }))}
              />
              <em>{slot.semanticType}</em>
            </label>
          ))}
        </div>
        <div className="asset-library-upload-actions">
          <button className="send-btn" type="submit" disabled={groupUploading}>
            {groupUploading ? "Uploading group..." : "Create grouped entity"}
          </button>
          {groupStatus ? <span className={groupStatus.startsWith("Grouped upload saved") ? "is-success" : "is-error"}>{groupStatus}</span> : null}
        </div>
      </form>
    </details>
  );
}

function AssetLibraryGroupedAssets({ detail }: { detail: AssetLibraryEntityDetail }) {
  const grouped = groupAssetsBySemanticType(detail.assets);
  const orderedKeys = Object.keys(grouped).sort((a, b) => {
    const left = SEMANTIC_GROUP_ORDER.indexOf(a);
    const right = SEMANTIC_GROUP_ORDER.indexOf(b);
    if (left === -1 && right === -1) return a.localeCompare(b);
    if (left === -1) return 1;
    if (right === -1) return -1;
    return left - right;
  });

  if (!orderedKeys.length) return <div className="asset-library-empty">No assets returned for this entity.</div>;

  return (
    <div className="asset-library-asset-groups">
      {orderedKeys.map((semanticType) => (
        <section key={semanticType} className="asset-library-asset-group">
          <h3>{semanticType}</h3>
          <div className="asset-library-media-grid">
            {grouped[semanticType].map((asset) => (
              <AssetLibraryMediaTile key={asset.asset_id} asset={asset} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function AssetLibraryPreview({ asset, fallbackUrl, label }: { asset?: UploadedAsset | null; fallbackUrl: string; label: string }) {
  const previewPath = mediaAssetPreviewPath(asset) || mediaAssetOriginalPath(asset) || fallbackUrl;
  if (!previewPath) return <div className="asset-library-preview is-empty">{label.slice(0, 1).toUpperCase()}</div>;
  return (
    <div className="asset-library-preview">
      <img src={mediaUrl(previewPath)} alt={label} loading="lazy" decoding="async" />
    </div>
  );
}

function AssetLibraryMediaTile({ asset }: { asset: UploadedAsset }) {
  const previewPath = mediaAssetPreviewPath(asset) || mediaAssetOriginalPath(asset);
  const originalPath = mediaAssetOriginalPath(asset) || previewPath;
  const locator = formatV2AssetLocator({ asset_id: asset.asset_id, version_id: uploadedAssetVersionId(asset) });
  const copyReference = locator || asset.asset_id;
  return (
    <figure className={`asset-library-media-tile is-${asset.asset_type}`}>
      {asset.asset_type === "video" ? (
        <video src={mediaUrl(originalPath)} poster={previewPath ? mediaUrl(previewPath) : undefined} controls preload="metadata" />
      ) : asset.asset_type === "audio" ? (
        <audio src={mediaUrl(originalPath)} controls preload="metadata" />
      ) : previewPath ? (
        <img src={mediaUrl(previewPath)} alt={asset.filename} loading="lazy" decoding="async" />
      ) : (
        <div className="asset-library-preview is-empty">{asset.asset_type}</div>
      )}
      <figcaption>{asset.filename}</figcaption>
      <div className="asset-library-media-actions">
        {originalPath ? (
          <a href={mediaUrl(originalPath)} target="_blank" rel="noreferrer">
            Open original
          </a>
        ) : null}
        <button type="button" onClick={() => void navigator.clipboard?.writeText(copyReference)}>
          Copy reference
        </button>
      </div>
    </figure>
  );
}

function uploadedAssetVersionId(asset: UploadedAsset) {
  const rawVersionId = (asset as { version_id?: unknown }).version_id;
  if (typeof rawVersionId === "string" && rawVersionId.trim()) return rawVersionId;
  const metadataVersionId = asset.metadata?.version_id;
  if (typeof metadataVersionId === "string" && metadataVersionId.trim()) return metadataVersionId;
  const lineageVersionId = asset.lineage?.working_version_id;
  if (typeof lineageVersionId === "string" && lineageVersionId.trim()) return lineageVersionId;
  return null;
}

function groupAssetsBySemanticType(assets: UploadedAsset[]) {
  return assets.reduce<Record<string, UploadedAsset[]>>((groups, asset) => {
    const semanticType = asset.semantic_type || asset.asset_role || asset.asset_type || "asset";
    groups[semanticType] = [...(groups[semanticType] ?? []), asset];
    return groups;
  }, {});
}

function splitTags(value: string) {
  return value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function formatAssetLibraryPageError(error: unknown) {
  if (!error || typeof error !== "object") return "Asset library request failed.";
  const message = (error as Error).message;
  return message || "Asset library request failed.";
}
