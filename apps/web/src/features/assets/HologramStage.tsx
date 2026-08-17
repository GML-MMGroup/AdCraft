import { useRef } from "react";

import { ChevronLeftIcon, ChevronRightIcon } from "../../icons.tsx";
import type { AgentAssetBrowserItem } from "../agent-canvas/assets/assetSelection.ts";
import { HologramParticlesCanvas } from "./HologramParticlesCanvas.tsx";
import type { HologramTransitionDirection } from "./useHologramCarousel.ts";

interface HologramStageProps {
  asset: AgentAssetBrowserItem;
  buttonRef: (assetId: string, button: HTMLButtonElement | null) => void;
  imageUrl: string;
  isTransitioning: boolean;
  outgoingImageUrl: string | null;
  onNext: () => void;
  onOpen: (asset: AgentAssetBrowserItem, trigger: HTMLButtonElement) => void;
  onPauseHover: (paused: boolean) => void;
  onPrevious: () => void;
  transitionDirection: HologramTransitionDirection | null;
}

const SWIPE_THRESHOLD = 44;

export function HologramStage({
  asset,
  buttonRef,
  imageUrl,
  isTransitioning,
  outgoingImageUrl,
  onNext,
  onOpen,
  onPauseHover,
  onPrevious,
  transitionDirection,
}: HologramStageProps) {
  const pointerStartXRef = useRef<number | null>(null);
  const suppressOpenRef = useRef(false);

  return (
    <div className="recommended-scenes-hologram__stage" id={`recommended-scene-${asset.id}`}>
      <button
        className="recommended-scenes-hologram__nav is-previous"
        type="button"
        aria-label="Previous hologram scene"
        title="Previous hologram scene"
        onClick={onPrevious}
      >
        <ChevronLeftIcon />
      </button>
      <div className="recommended-scenes-hologram__projection-wrap">
        <button
          ref={(button) => buttonRef(asset.id, button)}
          className="recommended-scenes-hologram__projection"
          type="button"
          aria-label={`Open original scene ${asset.displayName}`}
          onClick={(event) => {
            if (suppressOpenRef.current) {
              suppressOpenRef.current = false;
              return;
            }
            onOpen(asset, event.currentTarget);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") {
              event.preventDefault();
              onPrevious();
            }
            if (event.key === "ArrowRight") {
              event.preventDefault();
              onNext();
            }
          }}
          onMouseEnter={() => onPauseHover(true)}
          onMouseLeave={() => onPauseHover(false)}
          onPointerDown={(event) => {
            pointerStartXRef.current = event.clientX;
            suppressOpenRef.current = false;
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerCancel={() => {
            pointerStartXRef.current = null;
            suppressOpenRef.current = false;
          }}
          onPointerUp={(event) => {
            const startX = pointerStartXRef.current;
            pointerStartXRef.current = null;
            if (startX === null) return;
            const distance = event.clientX - startX;
            if (Math.abs(distance) < SWIPE_THRESHOLD) return;
            suppressOpenRef.current = true;
            if (distance < 0) onNext();
            else onPrevious();
          }}
          onWheel={(event) => {
            if (Math.abs(event.deltaX) <= Math.abs(event.deltaY) || Math.abs(event.deltaX) < 18) return;
            event.preventDefault();
            if (event.deltaX > 0) onNext();
            else onPrevious();
          }}
        >
          <span className="recommended-scenes-hologram__glow" aria-hidden="true" />
          {isTransitioning && outgoingImageUrl && transitionDirection ? (
            <img
              key={`outgoing-${outgoingImageUrl}`}
              className={`recommended-scenes-hologram__scene is-outgoing is-${transitionDirection}`}
              src={outgoingImageUrl}
              alt=""
              decoding="async"
            />
          ) : null}
          <img
            key={asset.id}
            className={`recommended-scenes-hologram__scene${isTransitioning && transitionDirection ? ` is-incoming is-${transitionDirection}` : ""}`}
            src={imageUrl}
            alt=""
            decoding="async"
          />
          <span className="recommended-scenes-hologram__scanlines" aria-hidden="true" />
        </button>
        <HologramParticlesCanvas />
      </div>
      <button
        className="recommended-scenes-hologram__nav is-next"
        type="button"
        aria-label="Next hologram scene"
        title="Next hologram scene"
        onClick={onNext}
      >
        <ChevronRightIcon />
      </button>
    </div>
  );
}
