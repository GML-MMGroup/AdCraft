import { useId } from "react";
import ambientMusicIcon from "./arcticons--ambient-music-mod.svg";
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
        <span
          className="agent-node-workbench__audio-icon"
          aria-hidden="true"
          style={{ maskImage: `url("${ambientMusicIcon}")`, WebkitMaskImage: `url("${ambientMusicIcon}")` }}
        />
      </button>
      <span id={tooltipId} role="tooltip" className="agent-node-workbench__audio-tooltip">
        {disabledReason ?? (checked ? t("关闭视频音频生成") : t("开启视频音频生成"))}
      </span>
    </span>
  );
}
