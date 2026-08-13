import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PageHeader } from "../components/Layout.tsx";
import { CanonicalAssetViewer } from "../features/assets/CanonicalAssetViewer.tsx";
import { useAgentCanvasAssets } from "../features/agent-canvas/assets/useAgentCanvasAssets.ts";
import type { AgentAssetBrowserItem } from "../features/agent-canvas/assets/assetSelection.ts";
import type { V2AssetLibraryCategory } from "../types-v2.ts";
import "./assets.css";

type AssetPageScope = "my" | "recommended";

const ASSET_CATEGORIES: Array<{ id: V2AssetLibraryCategory; label: string }> = [
  { id: "characters", label: "Characters" },
  { id: "scenes", label: "Scenes" },
  { id: "props", label: "Props" },
];

export function AssetsPage() {
  const [scope, setScope] = useState<AssetPageScope>("my");
  const [category, setCategory] = useState<V2AssetLibraryCategory>("characters");
  const [search, setSearch] = useState("");
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);
  const assetLibraryRef = useRef<HTMLElement | null>(null);
  const selectedCardRef = useRef<HTMLButtonElement | null>(null);
  const assetCardRefsRef = useRef(new Map<string, HTMLButtonElement>());
  const library = useAgentCanvasAssets({ scope, category, mediaType: "image", search });
  const displayedAssets = useMemo(
    () => library.loading ? [] : library.items,
    [library.items, library.loading],
  );
  const selectedAsset = useMemo(
    () => displayedAssets.find((asset) => asset.id === selectedAssetId) ?? null,
    [displayedAssets, selectedAssetId],
  );

  const restoreViewerFocus = useCallback(() => {
    if (selectedCardRef.current?.isConnected) {
      selectedCardRef.current.focus();
      return;
    }
    assetLibraryRef.current?.querySelector<HTMLButtonElement>('.v2-asset-library-tabs button[aria-selected="true"]')?.focus();
  }, []);

  const closePreview = useCallback(({ restoreFocus = true }: { restoreFocus?: boolean } = {}) => {
    if (restoreFocus) restoreViewerFocus();
    setSelectedAssetId(null);
  }, [restoreViewerFocus]);

  const navigateSelectedAsset = useCallback((direction: -1 | 1) => {
    if (!selectedAssetId || displayedAssets.length < 2) return;
    const currentIndex = displayedAssets.findIndex((asset) => asset.id === selectedAssetId);
    if (currentIndex < 0) return;
    const nextIndex = (currentIndex + direction + displayedAssets.length) % displayedAssets.length;
    const nextAsset = displayedAssets[nextIndex];
    if (!nextAsset) return;
    selectedCardRef.current = assetCardRefsRef.current.get(nextAsset.id) ?? null;
    setSelectedAssetId(nextAsset.id);
  }, [displayedAssets, selectedAssetId]);

  useEffect(() => {
    if (library.loading || !selectedAssetId || selectedAsset) return;
    closePreview({ restoreFocus: false });
  }, [closePreview, library.loading, selectedAsset, selectedAssetId]);

  function selectAsset(asset: AgentAssetBrowserItem, trigger: HTMLButtonElement) {
    selectedCardRef.current = trigger;
    setSelectedAssetId(asset.id);
  }

  function changeScope(nextScope: AssetPageScope) {
    if (nextScope === scope) return;
    closePreview({ restoreFocus: false });
    setScope(nextScope);
  }

  function changeCategory(nextCategory: V2AssetLibraryCategory) {
    if (nextCategory === category) return;
    closePreview({ restoreFocus: false });
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
        </div>
      </div>
      <div className="v2-asset-library-categories" role="tablist" aria-label="Asset category">
        {ASSET_CATEGORIES.map((item) => (
          <button key={item.id} className={category === item.id ? "is-active" : ""} type="button" role="tab" aria-selected={category === item.id} onClick={() => changeCategory(item.id)}>{item.label}</button>
        ))}
      </div>
      <div className="v2-asset-library-layout">
        <div>
          {library.error ? <p className="asset-library-status is-error">{library.error}</p> : null}
          {library.loading ? <p className="asset-library-status">Loading assets...</p> : null}
          {!library.loading && !library.error && !displayedAssets.length ? <p className="asset-library-empty">No assets found.</p> : null}
          <div className="v2-asset-library-grid">
            {displayedAssets.map((asset) => (
              <AssetCard
                key={asset.id}
                asset={asset}
                selected={selectedAssetId === asset.id}
                buttonRef={(button) => {
                  if (button) assetCardRefsRef.current.set(asset.id, button);
                  else assetCardRefsRef.current.delete(asset.id);
                }}
                onSelect={selectAsset}
              />
            ))}
          </div>
        </div>
      </div>
      {selectedAsset ? (
        <CanonicalAssetViewer
          item={selectedAsset}
          hasAssetNavigation={displayedAssets.length > 1}
          onPreviousAsset={() => navigateSelectedAsset(-1)}
          onNextAsset={() => navigateSelectedAsset(1)}
          onClose={closePreview}
        />
      ) : null}
    </section>
  );
}

function AssetCard({
  asset,
  selected,
  buttonRef,
  onSelect,
}: {
  asset: AgentAssetBrowserItem;
  selected: boolean;
  buttonRef: (button: HTMLButtonElement | null) => void;
  onSelect: (asset: AgentAssetBrowserItem, trigger: HTMLButtonElement) => void;
}) {
  return (
    <button ref={buttonRef} className={`v2-asset-entity-card v2-asset-discover-card ${selected ? "is-selected" : ""}`} type="button" aria-label={`Open asset ${asset.displayName}`} onClick={(event) => onSelect(asset, event.currentTarget)}>
      {asset.previewUrl
        ? <img className="v2-asset-media" src={asset.previewUrl} alt={asset.displayName} loading="lazy" decoding="async" />
        : <span className="v2-asset-media is-empty">{asset.displayName.slice(0, 1).toUpperCase()}</span>}
      <span className="v2-asset-entity-card-title">{asset.displayName}</span>
    </button>
  );
}
