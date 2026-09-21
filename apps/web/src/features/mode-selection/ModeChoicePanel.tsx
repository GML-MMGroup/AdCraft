import { ParticleIconStudy } from "../mode-icon-lab/ParticleIconStudy";

export type ModeId = "creation" | "brand";

export function ModeChoicePanel({
  id,
  eyebrow,
  title,
  description,
  detail,
  onChoose,
  paused,
}: {
  id: ModeId;
  eyebrow: string;
  title: string;
  description: string;
  detail: string;
  onChoose: (mode: ModeId) => void;
  paused: boolean;
}) {
  return (
    <button
      className={`mode-choice-panel mode-choice-panel--${id}`}
      type="button"
      data-mode={id}
      data-particle-hover
      disabled={paused}
      onClick={() => onChoose(id)}
    >
      <span className="mode-choice-panel__wash" aria-hidden="true" />
      <span className="mode-choice-panel__topline">
        <span className="mode-choice-panel__index">{id === "creation" ? "01" : "02"}</span>
        <span className="mode-choice-panel__eyebrow">{eyebrow}</span>
      </span>
      <span className="mode-choice-panel__body">
        <span className="mode-choice-panel__icon-wrap">
          <ParticleIconStudy shape={id === "creation" ? "butterfly" : "infinity"} paused={paused} hoverOnly accented className="mode-choice-particles" />
        </span>
        <span className="mode-choice-panel__title">{title}</span>
        <span className="mode-choice-panel__description">{description}</span>
      </span>
      <span className="mode-choice-panel__footer">
        <span>{detail}</span>
        <span className="mode-choice-panel__arrow" aria-hidden="true">↗</span>
      </span>
    </button>
  );
}
