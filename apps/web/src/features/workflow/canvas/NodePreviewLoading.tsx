import type { PreviewLoadingType } from "../types.ts";

const loadingBarCount: Record<PreviewLoadingType, number> = {
  text: 3,
  image: 4,
  audio: 5,
  video: 3,
  generic: 0,
};

export function NodePreviewLoading({ type = "generic" }: { type?: PreviewLoadingType }) {
  return (
    <span className={`workflow-card-preview-loading is-${type}`} role="status" aria-label="Generating" data-loading-type={type}>
      <span className="workflow-card-preview-loading-sheen" aria-hidden="true" />
      <span className="workflow-card-preview-loading-core" aria-hidden="true">
        {Array.from({ length: loadingBarCount[type] }).map((_, index) => <i key={index} />)}
      </span>
      <span className="workflow-card-preview-loading-label">Generating</span>
    </span>
  );
}
