import type { AgentAssetBrowserItem } from "../agent-canvas/assets/assetSelection.ts";
import { StableMediaPreview } from "../../workflow/StableMediaPreview.tsx";

type GalleryPlacement = "feature" | "support" | "flow";
type GallerySize = "feature" | "support" | "wide" | "medium" | "compact";

const FLOW_SIZES: GallerySize[] = ["wide", "medium", "compact", "compact", "wide", "medium"];

interface AssetContactSheetProps {
  assets: AgentAssetBrowserItem[];
  selectedAssetId: string | null;
  buttonRef: (assetId: string, button: HTMLButtonElement | null) => void;
  onSelect: (asset: AgentAssetBrowserItem, trigger: HTMLButtonElement) => void;
}

export function AssetContactSheet({
  assets,
  selectedAssetId,
  buttonRef,
  onSelect,
}: AssetContactSheetProps) {
  if (assets.length < 5) {
    return (
      <div className="asset-contact-sheet is-compact">
        {assets.map((asset, index) => (
          <AssetContactSheetCard
            key={asset.id}
            asset={asset}
            placement="flow"
            size={index === 0 ? "wide" : "medium"}
            selected={selectedAssetId === asset.id}
            buttonRef={buttonRef}
            onSelect={onSelect}
          />
        ))}
      </div>
    );
  }

  const [feature, ...remainingAssets] = assets;
  const supportAssets = remainingAssets.slice(0, 4);
  const flowAssets = remainingAssets.slice(4);

  return (
    <div className="asset-contact-sheet">
      {feature ? (
        <section className="asset-contact-sheet-lead" aria-label="Featured assets">
          <AssetContactSheetCard
            asset={feature}
            placement="feature"
            size="feature"
            selected={selectedAssetId === feature.id}
            buttonRef={buttonRef}
            onSelect={onSelect}
          />
          <div className="asset-contact-sheet-support">
            {supportAssets.map((asset) => (
              <AssetContactSheetCard
                key={asset.id}
                asset={asset}
                placement="support"
                size="support"
                selected={selectedAssetId === asset.id}
                buttonRef={buttonRef}
                onSelect={onSelect}
              />
            ))}
          </div>
        </section>
      ) : null}
      {flowAssets.length ? (
        <div className="asset-contact-sheet-flow" aria-label="More assets">
          {flowAssets.map((asset, index) => (
            <AssetContactSheetCard
              key={asset.id}
              asset={asset}
              placement="flow"
              size={FLOW_SIZES[index % FLOW_SIZES.length] ?? "medium"}
              selected={selectedAssetId === asset.id}
              buttonRef={buttonRef}
              onSelect={onSelect}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function AssetContactSheetCard({
  asset,
  placement,
  size,
  selected,
  buttonRef,
  onSelect,
}: {
  asset: AgentAssetBrowserItem;
  placement: GalleryPlacement;
  size: GallerySize;
  selected: boolean;
  buttonRef: (assetId: string, button: HTMLButtonElement | null) => void;
  onSelect: (asset: AgentAssetBrowserItem, trigger: HTMLButtonElement) => void;
}) {
  return (
    <button
      ref={(button) => buttonRef(asset.id, button)}
      className={`v2-asset-entity-card v2-asset-discover-card asset-contact-sheet-card ${selected ? "is-selected" : ""}`}
      type="button"
      aria-label={`Open asset ${asset.displayName}`}
      data-gallery-placement={placement}
      data-gallery-size={size}
      onClick={(event) => onSelect(asset, event.currentTarget)}
    >
      {asset.previewUrl
        ? <StableMediaPreview className="v2-asset-media" src={asset.previewUrl} alt={asset.displayName} loading="lazy" decoding="async" />
        : <span className="v2-asset-media is-empty">{asset.displayName.slice(0, 1).toUpperCase()}</span>}
      <span className="v2-asset-entity-card-title">{asset.displayName}</span>
    </button>
  );
}
