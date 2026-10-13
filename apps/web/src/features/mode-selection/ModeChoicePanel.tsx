import { ParticleIconStudy } from "../mode-icon-lab/ParticleIconStudy";

export type ModeId = "creation" | "brand";

export function ModeChoicePanel({
  id,
  eyebrow,
  title,
  description,
  onChoose,
  paused,
}: {
  id: ModeId;
  eyebrow: string;
  title: string;
  description: string;
  onChoose: (mode: ModeId, keyboard?: boolean) => void;
  paused: boolean;
}) {
  return (
    <button
      className={`mode-choice-panel mode-choice-panel--${id}`}
      type="button"
      data-mode={id}
      data-particle-hover
      disabled={paused}
      onClick={event => onChoose(id, event.detail === 0)}
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
    </button>
  );
}
