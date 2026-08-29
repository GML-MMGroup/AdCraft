import type { VideoSkillPreviewV2 } from "../../../types-v2.ts";
import { StableMediaPreview } from "../../../workflow/StableMediaPreview.tsx";

type SkillPreviewProps = {
  preview: VideoSkillPreviewV2 | null;
};

/** Render only the public preview projection returned by the Skill catalog. */
export function SkillPreview({ preview }: SkillPreviewProps) {
  if (preview?.kind === "image" && preview.media_url) {
    return <StableMediaPreview src={preview.media_url} alt="" loading="lazy" decoding="async" />;
  }
  if (preview?.kind === "video" && preview.media_url) {
    return <video src={preview.media_url} muted playsInline preload="metadata" />;
  }
  return (
    <span className="agent-chat__style-preview-placeholder" data-preview="placeholder" aria-label="No preview available">
      <span className="agent-chat__style-preview-sprockets" aria-hidden="true">
        {Array.from({ length: 7 }, (_, index) => <i key={index} />)}
      </span>
      <span aria-hidden="true">No preview</span>
    </span>
  );
}
