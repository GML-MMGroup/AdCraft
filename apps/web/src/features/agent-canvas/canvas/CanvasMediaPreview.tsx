import type { ImgHTMLAttributes } from "react";

import { cachedCanvasPreviewUrl } from "./canvasPreviewCache.ts";

export type CanvasMediaPreviewProps = Omit<ImgHTMLAttributes<HTMLImageElement>, "src"> & {
  src: string;
};

/** Direct browser-cached rendition for canvas cards; never hydrates through Blob URLs. */
export function CanvasMediaPreview({
  src,
  draggable = false,
  loading = "eager",
  decoding = "async",
  sizes = "360px",
  ...props
}: CanvasMediaPreviewProps) {
  return (
    <img
      {...props}
      src={cachedCanvasPreviewUrl(src) ?? src}
      draggable={draggable}
      loading={loading}
      decoding={decoding}
      sizes={sizes}
    />
  );
}
