import { useCallback, useEffect, useMemo } from "react";

import type { AgentAssetBrowserItem } from "../agent-canvas/assets/assetSelection.ts";
import { HologramStage } from "./HologramStage.tsx";
import { hologramSceneUrlForAsset } from "./recommendedSceneHologramCatalog.ts";
import { useHologramCarousel } from "./useHologramCarousel.ts";

interface RecommendedSceneHologramProps {
  assets: AgentAssetBrowserItem[];
  buttonRef: (assetId: string, button: HTMLButtonElement | null) => void;
  onOpen: (asset: AgentAssetBrowserItem, trigger: HTMLButtonElement) => void;
  viewerOpen: boolean;
}

function hologramUrl(asset: AgentAssetBrowserItem) {
  return hologramSceneUrlForAsset(asset.identity.entityId ?? asset.id)
    ?? asset.previewUrl
    ?? asset.mediaUrl
    ?? "";
}

/**
 * An asset browser surface: the selector changes the projected world, while the
 * central projection intentionally remains the sole control that opens the raw grid.
 */
export function RecommendedSceneHologram({ assets, buttonRef, onOpen, viewerOpen }: RecommendedSceneHologramProps) {
  const assetIds = useMemo(() => assets.map((asset) => asset.id), [assets]);
  const preload = useCallback((assetId: string) => {
    const asset = assets.find((candidate) => candidate.id === assetId);
    if (!asset) return;
    const image = new Image();
    image.src = hologramUrl(asset);
  }, [assets]);
  const reducedMotion = useMemo(
    () => typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    [],
  );
  const carousel = useHologramCarousel(assetIds, { preload, reducedMotion });
  const { setPaused } = carousel;
  const activeAsset = useMemo(
    () => assets.find((asset) => asset.id === carousel.displayedId) ?? assets[0] ?? null,
    [assets, carousel.displayedId],
  );

  useEffect(() => {
    setPaused("viewer", viewerOpen);
  }, [setPaused, viewerOpen]);

  if (!activeAsset) return null;

  return (
    <section className="recommended-scenes-hologram" data-testid="recommended-scenes-hologram" aria-label="Recommended scenes hologram gallery">
      <HologramStage
        asset={activeAsset}
        buttonRef={buttonRef}
        imageUrl={hologramUrl(activeAsset)}
        isTransitioning={carousel.isTransitioning}
        onNext={carousel.next}
        onOpen={onOpen}
        onPauseFocus={(paused) => setPaused("focus", paused)}
        onPauseHover={(paused) => setPaused("hover", paused)}
        onPrevious={carousel.previous}
      />
      <div className="recommended-scenes-hologram__details">
        <div>
          <p className="recommended-scenes-hologram__eyebrow">Projected scene</p>
          <h2 className="recommended-scenes-hologram__name">{activeAsset.displayName}</h2>
        </div>
        <p className="recommended-scenes-hologram__hint">Select a scene to project. Open the projection to inspect its original reference grid.</p>
      </div>
      <div className="recommended-scenes-hologram__selector" role="tablist" aria-label="Recommended scene selection">
        {assets.map((asset) => {
          const selected = asset.id === carousel.activeId;
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
              onBlur={() => setPaused("focus", false)}
              onClick={() => carousel.select(asset.id)}
              onFocus={() => setPaused("focus", true)}
              onMouseEnter={() => setPaused("hover", true)}
              onMouseLeave={() => setPaused("hover", false)}
              onKeyDown={(event) => {
                if (event.key === "ArrowLeft") {
                  event.preventDefault();
                  carousel.previous();
                }
                if (event.key === "ArrowRight") {
                  event.preventDefault();
                  carousel.next();
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
