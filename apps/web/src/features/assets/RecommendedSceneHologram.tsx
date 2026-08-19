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
    () => assets.find((asset) => asset.id === carousel.activeId) ?? assets[0] ?? null,
    [assets, carousel.activeId],
  );
  const outgoingAsset = useMemo(
    () => assets.find((asset) => asset.id === carousel.outgoingId) ?? null,
    [assets, carousel.outgoingId],
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
        outgoingImageUrl={outgoingAsset ? hologramUrl(outgoingAsset) : null}
        onNext={carousel.next}
        onOpen={onOpen}
        onPauseHover={(paused) => setPaused("hover", paused)}
        onPrevious={carousel.previous}
        transitionDirection={carousel.transitionDirection}
      />
      <div className="recommended-scenes-hologram__details">
        <div>
          <p className="recommended-scenes-hologram__eyebrow">Projected scene</p>
          <h2 className="recommended-scenes-hologram__name">{activeAsset.displayName}</h2>
        </div>
        <p className="recommended-scenes-hologram__hint">Open the projection to inspect its original reference grid.</p>
      </div>
    </section>
  );
}
