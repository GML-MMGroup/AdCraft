import { useId } from "react";
import { useTranslation } from "../../../i18n/useTranslation.ts";

export function VideoSubtitleToggle({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  const t = useTranslation("en-US");
  const tooltipId = useId();
  return (
    <span className="agent-node-workbench__audio-toggle">
      <button
        type="button"
        aria-label={t("Generate subtitles")}
        aria-pressed={checked}
        aria-describedby={tooltipId}
        disabled={disabled}
        onClick={() => onChange(!checked)}
      >
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="M6 12h4m3 0h5M6 15h7m3 0h2" strokeLinecap="round" />
        </svg>
      </button>
      <span id={tooltipId} role="tooltip" className="agent-node-workbench__audio-tooltip">
        {disabled ? t("Submitting, please wait") : checked ? t("Disable video subtitles") : t("Enable video subtitles")}
        {" · "}{t("White text, black outline, no background, standard size")}
      </span>
    </span>
  );
}
