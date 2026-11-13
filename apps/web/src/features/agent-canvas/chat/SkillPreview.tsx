import { useState } from "react";
import { useUiLocale } from "../../../i18n/locale.tsx";
import type { VideoSkillPreviewV2 } from "../../../types-v2.ts";
import { StableMediaPreview } from "../../../workflow/StableMediaPreview.tsx";

type SkillPreviewProps = {
  preview: VideoSkillPreviewV2 | null;
  locale?: string;
  skeleton?: boolean;
};

/** Render only the public preview projection returned by the Skill catalog. */
export function SkillPreview({ preview, locale, skeleton = false }: SkillPreviewProps) {
  const chinese = useUiLocale(locale).startsWith("zh");
  if (skeleton) return <SkeletonSkillPreview key={preview?.media_url ?? "none"} preview={preview} chinese={chinese} />;
  if (preview?.kind === "image" && preview.media_url) {
    return <StableMediaPreview src={preview.media_url} alt="" loading="lazy" decoding="async" />;
  }
  if (preview?.kind === "video" && preview.media_url) {
    return <video src={preview.media_url} muted playsInline preload="metadata" />;
  }
  return (
    <span className="agent-chat__style-preview-placeholder" data-preview="placeholder" aria-label={chinese ? "暂无预览" : "No preview available"}>
      <span className="agent-chat__style-preview-sprockets" aria-hidden="true">
        {Array.from({ length: 7 }, (_, index) => <i key={index} />)}
      </span>
      <span aria-hidden="true">{chinese ? "暂无预览" : "No preview"}</span>
    </span>
  );
}


function SkeletonSkillPreview({ preview, chinese }: { preview: VideoSkillPreviewV2 | null; chinese: boolean }) {
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const hasMedia = Boolean(preview?.media_url && preview.kind !== "none");
  return <>
    {!ready ? <span className="brand-skill-gallery__preview-skeleton" role="img"
      aria-label={hasMedia && !failed ? (chinese ? "正在加载预览" : "Loading preview") : (chinese ? "暂无预览" : "No preview available")}>
      <span aria-hidden="true" /><i aria-hidden="true" /><i aria-hidden="true" />
    </span> : null}
    {hasMedia && !failed && preview ? (preview.kind === "video"
      ? <video className="brand-skill-gallery__preview-media" style={{ opacity: ready ? 1 : 0 }} src={preview.media_url!}
          muted playsInline preload="metadata" onLoadedData={() => setReady(true)} onError={() => { setReady(false); setFailed(true); }} />
      : <StableMediaPreview className="brand-skill-gallery__preview-media" style={{ opacity: ready ? 1 : 0 }} src={preview.media_url!}
          alt="" loading="lazy" decoding="async" onLoad={() => setReady(true)} onError={() => { setReady(false); setFailed(true); }} />) : null}
  </>;
}
