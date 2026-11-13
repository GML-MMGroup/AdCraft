import { useId } from "react";
import { useTranslation } from "../../../i18n/useTranslation.ts";

export function VideoAudioToggle({
  checked,
  disabledReason,
  onChange,
}: {
  checked: boolean;
  disabledReason: string | null;
  onChange: (checked: boolean) => void;
}) {
  const t = useTranslation("en-US");
  const tooltipId = useId();
  const disabled = disabledReason !== null;
  return (
    <span className="agent-node-workbench__audio-toggle">
      <button
        type="button"
        aria-label={t("Generate audio")}
        aria-pressed={checked}
        aria-describedby={tooltipId}
        disabled={disabled}
        onClick={() => {
          if (!disabled) onChange(!checked);
        }}
      >
        <svg className="agent-node-workbench__audio-icon" width="20" height="20" viewBox="0 0 24 24"
          fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M11 5 6 9H3v6h3l5 4V5Z" />
          {checked
            ? <path d="M15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14" />
            : <path d="m16 9 5 6m0-6-5 6" />}
        </svg>
      </button>
      <span id={tooltipId} role="tooltip" className="agent-node-workbench__audio-tooltip">
        {disabledReason ?? (checked ? t("关闭视频音频生成") : t("开启视频音频生成"))}
      </span>
    </span>
  );
}
