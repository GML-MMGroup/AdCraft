import { useEffect, useMemo, useState } from "react";

import type { AgentAssetBrowserItem } from "../agent-canvas/assets/assetSelection.ts";
import { HologramBeamCanvas } from "./HologramBeamCanvas.tsx";
import { HologramParticlesCanvas } from "./HologramParticlesCanvas.tsx";

const DEFAULT_HOLOGRAM_SCENE_URL = "/assets/hologram-scenes/scene-020.webp";

interface RecommendedSceneHologramProps {
  assets: AgentAssetBrowserItem[];
  buttonRef: (assetId: string, button: HTMLButtonElement | null) => void;
  onOpen: (asset: AgentAssetBrowserItem, trigger: HTMLButtonElement) => void;
}

function findActiveAsset(assets: AgentAssetBrowserItem[], activeId: string | null) {
  return assets.find((asset) => asset.id === activeId) ?? assets[0] ?? null;
}

function hologramSceneUrl(assetId: string) {
  const sceneId = assetId.match(/(?:^|:)recommended-v1-scene-(\d{3})$/)?.[1];
  return sceneId ? `/assets/hologram-scenes/scene-${sceneId}.webp` : DEFAULT_HOLOGRAM_SCENE_URL;
}

/**
 * An asset browser surface: the selector changes the projected world, while the
 * central projection intentionally remains the sole control that opens the raw grid.
 */
export function RecommendedSceneHologram({ assets, buttonRef, onOpen }: RecommendedSceneHologramProps) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const activeAsset = useMemo(() => findActiveAsset(assets, activeId), [activeId, assets]);

  useEffect(() => {
    if (!activeAsset || activeAsset.id === activeId) return;
    setActiveId(activeAsset.id);
  }, [activeAsset, activeId]);

  if (!activeAsset) return null;

  const currentIndex = assets.findIndex((asset) => asset.id === activeAsset.id);
  const selectRelativeScene = (offset: number) => {
    const nextIndex = (currentIndex + offset + assets.length) % assets.length;
    const nextAsset = assets[nextIndex];
    if (nextAsset) setActiveId(nextAsset.id);
  };

  return (
    <section className="recommended-scenes-hologram" data-testid="recommended-scenes-hologram" aria-label="Recommended scenes hologram gallery">
      <div className="recommended-scenes-hologram__stage" id={`recommended-scene-${activeAsset.id}`}>
        <HologramBeamCanvas />
        <button
          ref={(button) => buttonRef(activeAsset.id, button)}
          className="recommended-scenes-hologram__projection"
          type="button"
          aria-label={`Open original scene ${activeAsset.displayName}`}
          onClick={(event) => onOpen(activeAsset, event.currentTarget)}
        >
          <img className="recommended-scenes-hologram__scene" src={hologramSceneUrl(activeAsset.id)} alt="" decoding="async" />
          <span className="recommended-scenes-hologram__scanlines" aria-hidden="true" />
        </button>
        <HologramParticlesCanvas />
      </div>
      <div className="recommended-scenes-hologram__details">
        <div>
          <p className="recommended-scenes-hologram__eyebrow">Projected scene</p>
          <h2 className="recommended-scenes-hologram__name">{activeAsset.displayName}</h2>
        </div>
        <p className="recommended-scenes-hologram__hint">Select a scene to project. Open the projection to inspect its original reference grid.</p>
      </div>
      <div className="recommended-scenes-hologram__selector" role="tablist" aria-label="Recommended scene selection">
        {assets.map((asset) => {
          const selected = asset.id === activeAsset.id;
          return (
            <button
              key={asset.id}
              className={`recommended-scenes-hologram__option${selected ? " is-active" : ""}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-pressed={selected}
              aria-controls={`recommended-scene-${asset.id}`}
              aria-label={`Show hologram scene ${asset.displayName}`}
              data-hologram-scene-option
              onClick={() => setActiveId(asset.id)}
              onKeyDown={(event) => {
                if (event.key === "ArrowLeft") {
                  event.preventDefault();
                  selectRelativeScene(-1);
                }
                if (event.key === "ArrowRight") {
                  event.preventDefault();
                  selectRelativeScene(1);
                }
              }}
            >
              {asset.previewUrl ? <img src={asset.previewUrl} alt="" loading="lazy" decoding="async" /> : <span>{asset.displayName.slice(0, 1).toUpperCase()}</span>}
              <strong>{asset.displayName}</strong>
            </button>
          );
        })}
      </div>
    </section>
  );
}
