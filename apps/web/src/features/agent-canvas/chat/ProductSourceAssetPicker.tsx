import { useMemo, useState, type ChangeEvent } from "react";

import {
  ChevronDownIcon,
  ChevronUpIcon,
  CloseIcon,
  ImageIcon,
  UploadIcon,
} from "../../../icons.tsx";
import type { AgentAssetBrowserItem } from "../assets/assetSelection.ts";
import type { ProductSourceDraftItem } from "./productSourceSelection.ts";

export interface ProductSourceAssetPickerProps {
  items: AgentAssetBrowserItem[];
  selected: ProductSourceDraftItem[];
  inputKind: "main" | "multiview";
  maxAssetCount: number;
  loading: boolean;
  error: string | null;
  busy: boolean;
  onRetry: () => void;
  onSelectAsset: (item: AgentAssetBrowserItem) => void;
  onSelectFiles: (files: File[]) => void;
  onMove: (key: string, direction: -1 | 1) => void;
  onRemove: (key: string) => void;
}

function assetSelectable(item: AgentAssetBrowserItem): boolean {
  return item.source === "project"
    && item.mediaType === "image"
    && item.status === "ready"
    && Boolean(item.identity.versionId);
}

export function ProductSourceAssetPicker({
  items,
  selected,
  inputKind,
  maxAssetCount,
  loading,
  error,
  busy,
  onRetry,
  onSelectAsset,
  onSelectFiles,
  onMove,
  onRemove,
}: ProductSourceAssetPickerProps) {
  const [search, setSearch] = useState("");
  const visibleItems = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return items.filter((item) => (
      item.mediaType === "image"
      && (!query || item.displayName.toLocaleLowerCase().includes(query))
    ));
  }, [items, search]);

  const handleFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.currentTarget.files ?? []).slice(0, maxAssetCount);
    event.currentTarget.value = "";
    if (files.length) onSelectFiles(files);
  };

  return (
    <div className="agent-chat__product-source-picker">
      <div className="agent-chat__product-source-picker-header">
        <span>Project Assets</span>
        <input
          type="search"
          value={search}
          placeholder="Search images"
          aria-label="Search Product source images"
          disabled={busy}
          onChange={(event) => setSearch(event.currentTarget.value)}
        />
      </div>

      <div className="agent-chat__product-source-assets" aria-label="Project Product source images">
        {loading ? <p role="status">Loading Project Assets</p> : null}
        {!loading && error ? (
          <div className="agent-chat__product-source-assets-state" role="alert">
            <span>{error}</span>
            <button type="button" disabled={busy} onClick={onRetry}>Retry</button>
          </div>
        ) : null}
        {!loading && !error && visibleItems.length === 0 ? (
          <p>No Project images available</p>
        ) : null}
        {!loading && !error ? visibleItems.map((item) => {
          const selectable = assetSelectable(item);
          const selectedItem = selected.some((candidate) => (
            candidate.kind === "asset_version"
            && candidate.assetId === item.identity.assetId
            && candidate.versionId === item.identity.versionId
          ));
          return (
            <button
              key={item.id}
              type="button"
              className={`agent-chat__product-source-asset${selectedItem ? " is-selected" : ""}`}
              aria-label={`Select ${item.displayName}`}
              aria-pressed={selectedItem}
              disabled={busy || !selectable}
              onClick={() => onSelectAsset(item)}
            >
              <span className="agent-chat__product-source-asset-preview">
                {item.previewUrl ? <img src={item.previewUrl} alt="" /> : <ImageIcon aria-hidden="true" />}
              </span>
              <span title={item.displayName}>{item.displayName}</span>
            </button>
          );
        }) : null}
      </div>

      <label className="agent-chat__product-source-upload">
        <UploadIcon aria-hidden="true" />
        <span>{inputKind === "main" ? "Upload Product source" : "Upload Product sources"}</span>
        <input
          aria-label={inputKind === "main" ? "Upload Product source" : "Upload Product sources"}
          type="file"
          accept="image/*"
          multiple={inputKind === "multiview"}
          disabled={busy}
          onChange={handleFiles}
        />
      </label>

      {selected.length ? (
        <ol className="agent-chat__product-source-selected" aria-label="Selected Product source order">
          {selected.map((item, index) => (
            <li key={item.key}>
              <span className="agent-chat__product-source-selected-order">{index + 1}</span>
              <span className="agent-chat__product-source-selected-preview">
                {item.previewUrl ? <img src={item.previewUrl} alt="" /> : <ImageIcon aria-hidden="true" />}
              </span>
              <span className="agent-chat__product-source-selected-name" title={item.displayName}>
                {item.displayName}
              </span>
              {inputKind === "multiview" ? (
                <span className="agent-chat__product-source-selected-actions">
                  <button
                    type="button"
                    aria-label={`Move ${item.displayName} up`}
                    title="Move up"
                    disabled={busy || index === 0}
                    onClick={() => onMove(item.key, -1)}
                  >
                    <ChevronUpIcon aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    aria-label={`Move ${item.displayName} down`}
                    title="Move down"
                    disabled={busy || index === selected.length - 1}
                    onClick={() => onMove(item.key, 1)}
                  >
                    <ChevronDownIcon aria-hidden="true" />
                  </button>
                </span>
              ) : null}
              <button
                type="button"
                aria-label={`Remove ${item.displayName}`}
                title="Remove"
                disabled={busy}
                onClick={() => onRemove(item.key)}
              >
                <CloseIcon aria-hidden="true" />
              </button>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}
