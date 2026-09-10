import { useState, type ImgHTMLAttributes } from "react";

import { StableMediaPreview } from "../../../workflow/StableMediaPreview.tsx";

export type CanvasMediaPreviewProps = Omit<ImgHTMLAttributes<HTMLImageElement>, "src"> & {
  src: string;
  revealToken?: string | null;
};

/** Cache-aware rendition for canvas cards with version-safe remount continuity. */
export function CanvasMediaPreview({
  src,
  draggable = false,
  loading = "eager",
  decoding = "async",
  sizes = "360px",
  revealToken = null,
  className,
  onLoad,
  ...props
}: CanvasMediaPreviewProps) {
  const revealKey = revealToken ? `${revealToken}:${src}` : null;
  const [loadedRevealKey, setLoadedRevealKey] = useState<string | null>(null);
  const awaitingReveal = revealKey !== null && loadedRevealKey !== revealKey;
  const generationRevealed = revealKey !== null && loadedRevealKey === revealKey;

  return (
    <StableMediaPreview
      {...props}
      src={src}
      className={[
        className,
        awaitingReveal ? "agent-canvas-node__media--awaiting-generation-reveal" : "",
        generationRevealed ? "agent-canvas-node__media--generation-revealed" : "",
      ].filter(Boolean).join(" ")}
      draggable={draggable}
      loading={loading}
      decoding={decoding}
      sizes={sizes}
      onLoad={(event) => {
        if (revealKey) setLoadedRevealKey(revealKey);
        onLoad?.(event);
      }}
    />
  );
}
