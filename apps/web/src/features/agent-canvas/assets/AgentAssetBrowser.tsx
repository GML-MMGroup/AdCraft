import {
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from "react";

import {
  AssetsIcon,
  ImageIcon,
  MuteIcon,
  PlusIcon,
  UploadIcon,
  VideoIcon,
} from "../../../icons.tsx";
import type {
  AgentAssetBrowserItem,
  AgentAssetMediaFilter,
  AgentAssetReferenceSelection,
  AgentAssetScope,
  AgentAssetSourceNodeSelection,
} from "./assetSelection.ts";
import {
  toReferenceSelection,
  toSourceNodeSelection,
} from "./assetSelection.ts";
import { useAgentCanvasAssets } from "./useAgentCanvasAssets.ts";
import "./AgentAssetBrowser.css";

export type {
  AgentAssetReferenceSelection,
  AgentAssetSourceNodeSelection,
} from "./assetSelection.ts";

export interface AgentAssetBrowserProps {
  workflowId: string;
  category?: string | null;
  uploadSemanticRole?: string | null;
  uploadMetadata?: Record<string, unknown>;
  onAddReferences: (
    selections: AgentAssetReferenceSelection[],
  ) => Promise<void> | void;
  onCreateReadySourceNode: (
    selection: AgentAssetSourceNodeSelection,
  ) => Promise<void> | void;
  onUploadComplete?: () => Promise<void> | void;
}

const SCOPES: Array<{ value: AgentAssetScope; label: string }> = [
  { value: "project", label: "Project Assets" },
  { value: "my", label: "My Assets" },
  { value: "recommended", label: "Recommended" },
];

const MEDIA_FILTERS: Array<{ value: AgentAssetMediaFilter; label: string }> = [
  { value: "all", label: "All media" },
  { value: "image", label: "Images" },
  { value: "video", label: "Videos" },
  { value: "audio", label: "Audio" },
];

function AssetTypeIcon({ mediaType }: Pick<AgentAssetBrowserItem, "mediaType">) {
  if (mediaType === "image") return <ImageIcon aria-hidden="true" />;
  if (mediaType === "video") return <VideoIcon aria-hidden="true" />;
  return <MuteIcon aria-hidden="true" />;
}

function AssetPreview({ item }: { item: AgentAssetBrowserItem }) {
  if (item.mediaType === "image" && item.previewUrl) {
    return (
      <img
        className="agent-asset-card__media"
        src={item.previewUrl}
        alt=""
        loading="lazy"
      />
    );
  }
  if (item.mediaType === "video" && item.mediaUrl) {
    return (
      <video
        className="agent-asset-card__media"
        src={item.mediaUrl}
        muted
        playsInline
        preload="metadata"
        aria-label={`${item.displayName} preview`}
      />
    );
  }
  return (
    <div className="agent-asset-card__placeholder" aria-hidden="true">
      <AssetTypeIcon mediaType={item.mediaType} />
    </div>
  );
}

function emptyLabel(scope: AgentAssetScope, hasQuery: boolean): string {
  if (hasQuery) return "No matching assets";
  if (scope === "project") return "No project assets yet";
  if (scope === "my") return "No saved images";
  return "No recommended images";
}

export function AgentAssetBrowser({
  workflowId,
  category = null,
  uploadSemanticRole = null,
  uploadMetadata,
  onAddReferences,
  onCreateReadySourceNode,
  onUploadComplete,
}: AgentAssetBrowserProps) {
  const [scope, setScope] = useState<AgentAssetScope>("project");
  const [mediaType, setMediaType] = useState<AgentAssetMediaFilter>("all");
  const [search, setSearch] = useState("");
  const [selectedReferencesById, setSelectedReferencesById] =
    useState<Map<string, AgentAssetReferenceSelection>>(() => new Map());
  const [addingReferences, setAddingReferences] = useState(false);
  const [pendingSourceIds, setPendingSourceIds] = useState<Set<string>>(() => new Set());
  const [actionError, setActionError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const {
    items,
    loading,
    error,
    uploading,
    uploadError,
    retry,
    uploadFiles,
  } = useAgentCanvasAssets({
    workflowId,
    scope,
    category,
    mediaType: scope === "project" ? mediaType : "image",
    search,
  });

  const selectedReferences = useMemo(
    () => [...selectedReferencesById.values()],
    [selectedReferencesById],
  );

  const selectScope = (nextScope: AgentAssetScope) => {
    if (nextScope === scope) return;
    setScope(nextScope);
    setSearch("");
    setMediaType(nextScope === "project" ? "all" : "image");
    setSelectedReferencesById(new Map());
    setActionError(null);
  };

  const toggleReference = (item: AgentAssetBrowserItem) => {
    if (item.mediaType !== "image" || item.status !== "ready") return;
    const selection = toReferenceSelection(item);
    if (!selection) return;
    setSelectedReferencesById((current) => {
      const next = new Map(current);
      if (next.has(item.id)) next.delete(item.id);
      else next.set(item.id, selection);
      return next;
    });
  };

  const addReferences = async () => {
    if (selectedReferences.length === 0 || addingReferences) return;
    setAddingReferences(true);
    setActionError(null);
    try {
      await onAddReferences(selectedReferences);
      setSelectedReferencesById(new Map());
    } catch (referenceError) {
      setActionError(
        referenceError instanceof Error
          ? referenceError.message
          : "Unable to add references.",
      );
    } finally {
      setAddingReferences(false);
    }
  };

  const createSourceNode = async (item: AgentAssetBrowserItem) => {
    const selection = toSourceNodeSelection(item);
    if (!selection || pendingSourceIds.has(item.id)) return;
    setPendingSourceIds((current) => new Set(current).add(item.id));
    setActionError(null);
    try {
      await onCreateReadySourceNode(selection);
    } catch (sourceError) {
      setActionError(
        sourceError instanceof Error
          ? sourceError.message
          : "Unable to create a source node.",
      );
    } finally {
      setPendingSourceIds((current) => {
        const next = new Set(current);
        next.delete(item.id);
        return next;
      });
    }
  };

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = event.currentTarget.files;
    event.currentTarget.value = "";
    if (!files?.length) return;
    try {
      await uploadFiles(files, {
        semanticRole: uploadSemanticRole,
        metadata: uploadMetadata,
      });
      await onUploadComplete?.();
    } catch {
      // The hook exposes the bounded upload error next to the control.
    }
  };

  return (
    <section className="agent-asset-browser" aria-label="Agent Canvas assets">
      <header className="agent-asset-browser__header">
        <div className="agent-asset-browser__title">
          <AssetsIcon aria-hidden="true" />
          <div>
            <h2>Assets</h2>
            <p>Attach references or place ready media on the canvas.</p>
          </div>
        </div>
        {scope === "project" ? (
          <label className={`agent-asset-browser__upload${uploading ? " is-busy" : ""}`}>
            <UploadIcon aria-hidden="true" />
            <span>{uploading ? "Uploading" : "Upload"}</span>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*,video/*,audio/*"
              multiple
              aria-label="Upload project media"
              disabled={uploading}
              onChange={handleUpload}
            />
          </label>
        ) : null}
      </header>

      <div className="agent-asset-browser__controls">
        <div className="agent-asset-browser__tabs" role="tablist" aria-label="Asset source">
          {SCOPES.map((option) => (
            <button
              key={option.value}
              type="button"
              role="tab"
              aria-selected={scope === option.value}
              className={scope === option.value ? "is-active" : ""}
              onClick={() => selectScope(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <input
          className="agent-asset-browser__search"
          type="search"
          value={search}
          aria-label="Search assets"
          placeholder="Search assets"
          onChange={(event) => setSearch(event.currentTarget.value)}
        />
      </div>

      <div className="agent-asset-browser__filters" aria-label="Media type filters">
        {scope === "project" ? MEDIA_FILTERS.map((filter) => (
          <button
            key={filter.value}
            type="button"
            className={mediaType === filter.value ? "is-active" : ""}
            aria-pressed={mediaType === filter.value}
            onClick={() => setMediaType(filter.value)}
          >
            {filter.label}
          </button>
        )) : (
          <span className="agent-asset-browser__image-only">
            <ImageIcon aria-hidden="true" />
            Images only
          </span>
        )}
      </div>

      {uploadError ? <p className="agent-asset-browser__error" role="alert">{uploadError}</p> : null}
      {actionError ? <p className="agent-asset-browser__error" role="alert">{actionError}</p> : null}

      <div className="agent-asset-browser__body">
        {loading ? (
          <div className="agent-asset-browser__state" role="status">
            <span className="agent-asset-browser__spinner" aria-hidden="true" />
            Loading assets
          </div>
        ) : error ? (
          <div className="agent-asset-browser__state agent-asset-browser__state--error" role="alert">
            <p>{error}</p>
            <button type="button" aria-label="Retry loading assets" onClick={() => void retry()}>
              Retry
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="agent-asset-browser__state">
            <AssetTypeIcon mediaType={scope === "project" && mediaType !== "all" ? mediaType : "image"} />
            <p>{emptyLabel(scope, Boolean(search.trim()))}</p>
            {scope === "project" && !search.trim() ? (
              <button type="button" onClick={() => fileInputRef.current?.click()}>
                <UploadIcon aria-hidden="true" />
                Upload media
              </button>
            ) : null}
          </div>
        ) : (
          <div className="agent-asset-browser__grid">
            {items.map((item) => {
              const selected = selectedReferencesById.has(item.id);
              const sourceSelection = toSourceNodeSelection(item);
              return (
                <article
                  key={item.id}
                  className={`agent-asset-card${selected ? " is-selected" : ""}`}
                  data-testid={`agent-asset-${item.id}`}
                  data-media-type={item.mediaType}
                >
                  <div className="agent-asset-card__preview">
                    <AssetPreview item={item} />
                    <span className="agent-asset-card__type" title={item.mediaType}>
                      <AssetTypeIcon mediaType={item.mediaType} />
                    </span>
                    {item.mediaType === "image" ? (
                      <label className="agent-asset-card__select">
                        <input
                          type="checkbox"
                          checked={selected}
                          disabled={item.status !== "ready"}
                          aria-label={`Select ${item.displayName}`}
                          onChange={() => toggleReference(item)}
                        />
                        <span aria-hidden="true" />
                      </label>
                    ) : null}
                  </div>
                  <div className="agent-asset-card__meta">
                    <strong title={item.displayName}>{item.displayName}</strong>
                    <span>{item.status === "ready" ? item.mediaType : "Unavailable"}</span>
                  </div>
                  {sourceSelection ? (
                    <button
                      type="button"
                      className="agent-asset-card__source-action"
                      disabled={item.status !== "ready" || pendingSourceIds.has(item.id)}
                      aria-label={`Create Ready ${item.mediaType} node from ${item.displayName}`}
                      onClick={() => void createSourceNode(item)}
                    >
                      <PlusIcon aria-hidden="true" />
                      {pendingSourceIds.has(item.id) ? "Adding" : `Add ${item.mediaType} node`}
                    </button>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
      </div>

      <footer className="agent-asset-browser__footer">
        <span>
          {selectedReferences.length
            ? `${selectedReferences.length} image${selectedReferences.length === 1 ? "" : "s"} selected`
            : "Select compatible images to attach"}
        </span>
        <button
          type="button"
          className="agent-asset-browser__add"
          disabled={selectedReferences.length === 0 || addingReferences}
          onClick={() => void addReferences()}
        >
          <PlusIcon aria-hidden="true" />
          {addingReferences
            ? "Adding references"
            : `Add ${selectedReferences.length || ""} reference${selectedReferences.length === 1 ? "" : "s"}`}
        </button>
      </footer>
    </section>
  );
}
