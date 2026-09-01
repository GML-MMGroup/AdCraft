import type { ImgHTMLAttributes } from "react";

export type CanvasMediaPreviewProps = Omit<ImgHTMLAttributes<HTMLImageElement>, "src"> & {
  src: string;
};

/** Direct browser-cached rendition for canvas cards; never hydrates through Blob URLs. */
export function CanvasMediaPreview({
  src,
  draggable = false,
  loading = "lazy",
  decoding = "async",
  ...props
}: CanvasMediaPreviewProps) {
  return (
    <img
      {...props}
      src={src}
      draggable={draggable}
      loading={loading}
      decoding={decoding}
    />
  );
}
