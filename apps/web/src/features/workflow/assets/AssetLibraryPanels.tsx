import { useEffect, useState } from "react";
import { api, mediaUrl } from "../../../api/client";
import { ASSET_LIBRARY_UPLOAD_EVENT } from "../../../api/workflowNormalizers";
import { assetReferenceFromLibraryEntity } from "../../../workflow/assetMentions.ts";
import { mediaAssetOriginalPath, mediaAssetPreviewPath } from "../../../workflow/mediaPreview.ts";
import { localRevisionEntityId, localRevisionSemanticType, localRevisionTargetField } from "../../../workflow/localRevision.ts";
import { LibraryReferenceChips } from "./LibraryReferenceChips.tsx";
import type { AssetLibraryEntitySummary, AssetLibraryEntityType, AssetLibraryReference, UploadedAsset } from "../../../types";
import type { AssetLibrarySaveTarget } from "./useAssetLibrarySaveDialog.ts";

function libraryEntitiesToReferences(
  entities: AssetLibraryEntitySummary[],
  patch: Partial<AssetLibraryReference> = {},
  options: { primaryReferenceIds?: Set<string> } = {},
): AssetLibraryReference[] {
  const primaryReferenceIds = options.primaryReferenceIds ?? new Set<string>();
  return entities.map((entity) =>
    assetReferenceFromLibraryEntity(entity, {
      ...patch,
      is_primary: primaryReferenceIds.has(entity.entity_id),
    }),
  );
}
export function AssetRevisionPanel({
  asset,
  revisionInstruction,
  libraryEntities,
  primaryReferenceIds,
  onChangeInstruction,
  onOpenLibrary,
  onRemoveLibrary,
  onTogglePrimary,
  onCancel,
  onSubmit,
}: {
  asset: UploadedAsset | null;
  revisionInstruction: string;
  libraryEntities: AssetLibraryEntitySummary[];
  primaryReferenceIds: Set<string>;
  onChangeInstruction: (value: string) => void;
  onOpenLibrary: () => void;
  onRemoveLibrary: (entityId: string) => void;
  onTogglePrimary: (entity: AssetLibraryEntitySummary) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  if (!asset) return null;
  const targetEntityId = localRevisionEntityId(asset);
  const revisionRequestPreview = {
    mode: "regenerate_asset",
    target_entity_id: targetEntityId,
    target_asset_id: asset.asset_id,
    semantic_type: localRevisionSemanticType(asset),
    target_field: localRevisionTargetField(asset),
    instruction: revisionInstruction.trim() || null,
    preserve_other_outputs: true,
    asset_references: libraryEntitiesToReferences(
      libraryEntities,
      {
        target_entity_id: targetEntityId,
      },
      { primaryReferenceIds },
    ),
    library_entity_ids: libraryEntities.map((entity) => entity.entity_id),
  };

  return (
    <form
      className="asset-revision-panel"
      data-revision-preview={JSON.stringify(revisionRequestPreview)}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <span>Local revision for {asset.filename}</span>
      <textarea value={revisionInstruction} placeholder="Describe only this asset or entity change..." onChange={(event) => onChangeInstruction(event.target.value)} />
      <div className="library-reference-row">
        <button className="pill-btn library-reference-trigger" type="button" onClick={onOpenLibrary}>
          Library reference
        </button>
        <LibraryReferenceChips
          entities={libraryEntities}
          primaryReferenceIds={primaryReferenceIds}
          onRemove={onRemoveLibrary}
          onTogglePrimary={onTogglePrimary}
        />
      </div>
      <div className="asset-revision-actions">
        <button className="small-action" type="button" onClick={onCancel}>
          Cancel
        </button>
        <button className="small-action" type="submit">
          Submit revision
        </button>
      </div>
    </form>
  );
}

export function AssetLibrarySaveModal({
  target,
  displayName,
  tags,
  feedback,
  saving,
  onChangeDisplayName,
  onChangeTags,
  onCancel,
  onSubmit,
}: {
  target: AssetLibrarySaveTarget | null;
  displayName: string;
  tags: string;
  feedback: string;
  saving: boolean;
  onChangeDisplayName: (value: string) => void;
  onChangeTags: (value: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  if (!target) return null;
  return (
    <form
      className="asset-library-save-modal"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="asset-library-save-heading">
        <span>Save to Asset Library</span>
        <button className="small-action" type="button" onClick={onCancel}>
          Close
        </button>
      </div>
      <div className="asset-library-save-meta">
        <span>{target.entityType}</span>
        <span>{target.node.title}</span>
        {target.sourceEntityId ? <span>{target.sourceEntityId}</span> : null}
      </div>
      <label className="node-config-field">
        <span>Display name</span>
        <input value={displayName} onChange={(event) => onChangeDisplayName(event.target.value)} />
      </label>
      <label className="node-config-field">
        <span>Tags</span>
        <input value={tags} placeholder="campaign, reusable" onChange={(event) => onChangeTags(event.target.value)} />
      </label>
      {feedback ? <span className="asset-library-save-feedback">{feedback}</span> : null}
      <div className="asset-library-save-actions">
        <button className="small-action" type="button" onClick={onCancel}>
          Cancel
        </button>
        <button className="send-btn" type="submit" disabled={saving}>
          {saving ? "Saving..." : "Save entity"}
        </button>
      </div>
    </form>
  );
}

export function AssetLibraryPicker({
  selectedEntities,
  lockedEntityType = null,
  selectionMode = "multi",
  onToggle,
  onClose,
}: {
  selectedEntities: AssetLibraryEntitySummary[];
  lockedEntityType?: AssetLibraryEntityType | null;
  selectionMode?: "multi" | "single";
  onToggle: (entity: AssetLibraryEntitySummary) => void;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<AssetLibraryEntityType | "all">("all");
  const [search, setSearch] = useState("");
  const [entities, setEntities] = useState<AssetLibraryEntitySummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [assetLibraryRefreshNonce, setAssetLibraryRefreshNonce] = useState(0);
  const selectedIds = new Set(selectedEntities.map((entity) => entity.entity_id));

  useEffect(() => {
    let cancelled = false;
    async function loadPickerEntities() {
      setLoading(true);
      setError("");
      try {
        const response = await api.listAssetLibraryEntities({
          entity_type: lockedEntityType ?? (activeTab === "all" ? undefined : activeTab),
          q: search,
        });
        if (cancelled) return;
        setEntities(response.entities ?? []);
      } catch (loadError) {
        if (cancelled) return;
        setEntities([]);
        setError(loadError instanceof Error ? loadError.message : "Asset Library picker failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadPickerEntities();
    return () => {
      cancelled = true;
    };
  }, [activeTab, lockedEntityType, search, assetLibraryRefreshNonce]);

  useEffect(() => {
    function handleAssetLibraryRefresh() {
      setAssetLibraryRefreshNonce((value) => value + 1);
    }

    window.addEventListener(ASSET_LIBRARY_UPLOAD_EVENT, handleAssetLibraryRefresh);
    return () => {
      window.removeEventListener(ASSET_LIBRARY_UPLOAD_EVENT, handleAssetLibraryRefresh);
    };
  }, []);

  return (
    <div className="asset-library-picker" role="dialog" aria-modal="true" aria-label="Asset Library picker">
      <div className="asset-library-picker-card">
        <div className="asset-library-picker-heading">
          <strong>Library reference</strong>
          <button className="small-action" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="asset-library-picker-controls">
          <select
            value={lockedEntityType ?? activeTab}
            disabled={Boolean(lockedEntityType)}
            onChange={(event) => setActiveTab(event.target.value as AssetLibraryEntityType | "all")}
          >
            <option value="all">All</option>
            <option value="character">Characters</option>
            <option value="scene">Scenes</option>
            <option value="storyboard_shot">Storyboard Shots</option>
            <option value="video_clip">Video Clips</option>
            <option value="bgm">BGM</option>
          </select>
          <input value={search} placeholder="Search library" onChange={(event) => setSearch(event.target.value)} />
        </div>
        {error ? <span className="asset-library-status is-error">{error}</span> : null}
        {loading ? <span className="asset-library-status">Loading library references...</span> : null}
        <div className="asset-library-picker-list">
          {!loading && !entities.length ? <span className="asset-library-empty">No library entities found.</span> : null}
          {entities.map((entity) => {
            const selected = selectedIds.has(entity.entity_id);
            return (
              <button
                key={entity.entity_id}
                className={`asset-library-picker-item ${selected ? "is-selected" : ""}`}
                type="button"
                aria-pressed={selectionMode === "multi" ? selected : undefined}
                onClick={() => onToggle(entity)}
              >
                <AssetLibraryPickerPreview entity={entity} />
                <span>
                  <strong>{entity.display_name}</strong>
                  <em>{entity.entity_type}{entity.semantic_type ? ` · ${entity.semantic_type}` : ""}</em>
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function AssetLibraryPickerPreview({ entity }: { entity: AssetLibraryEntitySummary }) {
  const previewPath = mediaAssetPreviewPath(entity.preview_asset) || mediaAssetOriginalPath(entity.preview_asset) || entity.preview_url || entity.thumbnail_url || "";
  if (!previewPath) return <span className="asset-library-picker-preview">{entity.display_name.slice(0, 1).toUpperCase()}</span>;
  return (
    <span className="asset-library-picker-preview">
      <img src={mediaUrl(previewPath)} alt={entity.display_name} loading="lazy" decoding="async" />
    </span>
  );
}
