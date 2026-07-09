import type { PreviewLoadingType } from "../types.ts";

export function NodePreviewLoading({ type = "generic" }: { type?: PreviewLoadingType }) {
  return (
    <div className={`node-preview-loading is-${type}`} aria-label="Generating">
      <span />
      <span />
      <span />
    </div>
  );
}
