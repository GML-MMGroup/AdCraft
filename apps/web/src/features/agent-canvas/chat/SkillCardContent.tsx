import { ConfirmIcon } from "../../../icons.tsx";
import type { VideoSkillPreviewV2 } from "../../../types-v2.ts";
import { SkillPreview } from "./SkillPreview.tsx";

export function SkillCardContent({ title, secondaryTitle, summary, preview, selected, activating = false, chinese = false, skeleton = false }: {
  title: string;
  secondaryTitle?: string;
  summary?: string;
  preview: VideoSkillPreviewV2 | null;
  selected: boolean;
  activating?: boolean;
  chinese?: boolean;
  skeleton?: boolean;
}) {
  return <>
    <span className="agent-chat__style-preview">
      <SkillPreview preview={preview} locale={chinese ? "zh-CN" : "en-US"} skeleton={skeleton} />
      {selected ? <span className="agent-chat__style-selected-mark" aria-label={chinese ? "已选择" : "Selected"}><ConfirmIcon /></span> : null}
      {activating ? <span className="agent-chat__style-applying" role="status">{chinese ? "正在应用…" : "Applying…"}</span> : null}
    </span>
    <span className="agent-chat__style-option-copy">
      <strong>{title}</strong>
      {secondaryTitle ? <span className="agent-chat__style-option-secondary-title">{secondaryTitle}</span> : null}
      {summary ? <small>{summary}</small> : null}
    </span>
  </>;
}
