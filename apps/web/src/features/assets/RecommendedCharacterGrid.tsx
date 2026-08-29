import type { AgentAssetBrowserItem } from "../agent-canvas/assets/assetSelection.ts";
import { StableMediaPreview } from "../../workflow/StableMediaPreview.tsx";

interface RecommendedCharacterGridProps {
  assets: AgentAssetBrowserItem[];
  selectedAssetId: string | null;
  loading: boolean;
  error: string | null;
  buttonRef: (assetId: string, button: HTMLButtonElement | null) => void;
  onSelect: (asset: AgentAssetBrowserItem, trigger: HTMLButtonElement) => void;
}

const SKELETON_COUNT = 4;

export function RecommendedCharacterGrid({
  assets,
  selectedAssetId,
  loading,
  error,
  buttonRef,
  onSelect,
}: RecommendedCharacterGridProps) {
  return (
    <section
      className="recommended-character-grid"
      data-testid="recommended-character-grid"
      aria-label="Recommended characters"
    >
      <header className="recommended-character-grid__header">
        <h2>Recommended characters</h2>
      </header>
      {loading ? (
        <div className="recommended-character-grid__cards" role="status" aria-label="Loading recommended characters">
          {Array.from({ length: SKELETON_COUNT }, (_, index) => (
            <div key={index} className="recommended-character-skeleton" data-testid="recommended-character-skeleton" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
          ))}
        </div>
      ) : error ? (
        <p className="recommended-character-grid__state is-error" role="alert">{error}</p>
      ) : assets.length ? (
        <div className="recommended-character-grid__cards">
          {assets.map((asset) => (
            <RecommendedCharacterCard
              key={asset.id}
              asset={asset}
              selected={selectedAssetId === asset.id}
              buttonRef={buttonRef}
              onSelect={onSelect}
            />
          ))}
        </div>
      ) : (
        <p className="recommended-character-grid__state">No recommended characters found.</p>
      )}
    </section>
  );
}

function RecommendedCharacterCard({
  asset,
  selected,
  buttonRef,
  onSelect,
}: {
  asset: AgentAssetBrowserItem;
  selected: boolean;
  buttonRef: (assetId: string, button: HTMLButtonElement | null) => void;
  onSelect: (asset: AgentAssetBrowserItem, trigger: HTMLButtonElement) => void;
}) {
  const previewUrl = asset.previewUrl ?? asset.mediaUrl;
  const tags = asset.tags.slice(0, 2);

  return (
    <button
      ref={(button) => buttonRef(asset.id, button)}
      className={`recommended-character-card${selected ? " is-selected" : ""}`}
      type="button"
      aria-label={`Open asset ${asset.displayName}`}
      aria-pressed={selected}
      data-asset-id={asset.id}
      onClick={(event) => onSelect(asset, event.currentTarget)}
    >
      <span className="recommended-character-card__media-frame">
        {previewUrl ? (
          <StableMediaPreview
            className="recommended-character-card__media"
            src={previewUrl}
            alt=""
            loading="lazy"
            decoding="async"
          />
        ) : (
          <span className="recommended-character-card__media is-empty" aria-hidden="true">
            {asset.displayName.slice(0, 1).toUpperCase()}
          </span>
        )}
      </span>
      <span className="recommended-character-card__meta">
        <strong>{asset.displayName}</strong>
        {tags.length ? (
          <span className="recommended-character-card__tags">
            {tags.map((tag) => <span className="recommended-character-card__tag" key={tag}>{tag}</span>)}
          </span>
        ) : null}
        {asset.status === "unavailable" ? <small>Preview unavailable</small> : null}
      </span>
    </button>
  );
}
