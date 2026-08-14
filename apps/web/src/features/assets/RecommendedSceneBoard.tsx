import type { AgentAssetBrowserItem } from "../agent-canvas/assets/assetSelection.ts";

interface RecommendedSceneBoardProps {
  assets: AgentAssetBrowserItem[];
  selectedAssetId: string | null;
  buttonRef: (assetId: string, button: HTMLButtonElement | null) => void;
  onSelect: (asset: AgentAssetBrowserItem, trigger: HTMLButtonElement) => void;
}

function sceneTags(asset: AgentAssetBrowserItem): string[] {
  return asset.tags
    .filter((tag) => !["scene", "scenes"].includes(tag.trim().toLocaleLowerCase()))
    .slice(0, 2);
}

export function RecommendedSceneBoard({
  assets,
  selectedAssetId,
  buttonRef,
  onSelect,
}: RecommendedSceneBoardProps) {
  return (
    <div className="asset-scene-board" aria-label="Recommended scenes">
      {assets.map((asset) => {
        const tags = sceneTags(asset);
        return (
          <button
            key={asset.id}
            ref={(button) => buttonRef(asset.id, button)}
            className={`v2-asset-entity-card asset-scene-board-card ${selectedAssetId === asset.id ? "is-selected" : ""}`}
            type="button"
            aria-label={`Open asset ${asset.displayName}`}
            data-scene-board-card
            onClick={(event) => onSelect(asset, event.currentTarget)}
          >
            <span className="asset-scene-board-media-frame">
              {asset.previewUrl
                ? <img className="asset-scene-board-media" src={asset.previewUrl} alt={asset.displayName} loading="lazy" decoding="async" />
                : <span className="asset-scene-board-media is-empty">{asset.displayName.slice(0, 1).toUpperCase()}</span>}
            </span>
            <span className="asset-scene-board-caption">
              <strong>{asset.displayName}</strong>
              <span className="asset-scene-board-tags">
                <i>Scene</i>
                {tags.map((tag, index) => <i key={`${tag}-${index}`}>{tag}</i>)}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
