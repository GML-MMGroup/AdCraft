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
  const keyboardMaskId = `${tooltipId}-keyboard`;
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
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <defs>
            <mask id={keyboardMaskId} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
              <rect width="24" height="24" fill="white" stroke="none" />
              <circle cx="18.5" cy="17.5" r="5.2" fill="black" stroke="none" />
            </mask>
          </defs>
          <g mask={`url(#${keyboardMaskId})`}>
            <rect x="2" y="5" width="19" height="13" rx="2" />
            <path d="M5.5 8.5h1m3 0h1m3 0h1m3 0h1M5.5 11.5h1m3 0h1m3 0h1m3 0h1M7.5 14.5h7" />
          </g>
          {checked ? (
            <path d="m15.5 17.5 2 2 4-4.5" />
          ) : (
            <g>
              <circle cx="18.5" cy="17.5" r="4" />
              <path d="m15.7 14.7 5.6 5.6" />
            </g>
          )}
        </svg>
      </button>
      <span id={tooltipId} role="tooltip" className="agent-node-workbench__audio-tooltip">
        {disabled ? t("Submitting, please wait") : checked ? t("Disable video subtitles") : t("Enable video subtitles")}
        {" · "}{t("White text, black outline, no background, standard size")}
      </span>
    </span>
  );
}
