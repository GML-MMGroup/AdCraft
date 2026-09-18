// THROWAWAY PROTOTYPE: validates the mode-launcher composition before production work.
import { useEffect, useMemo, useState } from "react";
import "./mode-launcher-prototype.css";

type ModeId = "creation" | "brand";
type VariantId = "cinema" | "archive" | "signal";

const variants: Array<{ id: VariantId; label: string; note: string }> = [
  { id: "cinema", label: "Cinema", note: "High-contrast film set" },
  { id: "archive", label: "Archive", note: "Warm brand dossier" },
  { id: "signal", label: "Signal", note: "Electric production desk" },
];

function readVariant(): VariantId {
  const requested = new URLSearchParams(window.location.search).get("variant");
  return variants.some((variant) => variant.id === requested) ? requested as VariantId : "cinema";
}

function CreationModeIcon() {
  return (
    <svg className="mode-choice-icon mode-choice-icon--creation" viewBox="0 0 128 128" aria-hidden="true">
      <path className="icon-idea-frame" d="M23 40V23h17M88 23h17v17M105 88v17H88M40 105H23V88" />
      <path className="icon-idea-trail" d="M32 84c11 4 21 2 29-7 7-8 10-18 15-27 4-8 10-12 20-12" />
      <path className="icon-idea-spark" d="m76 31 4 11 11 4-11 4-4 11-4-11-11-4 11-4 4-11Z" />
      <circle className="icon-idea-core" cx="61" cy="76" r="5" />
      <path className="icon-idea-ray" d="M34 66h10M85 76h10M63 92v9" />
    </svg>
  );
}

function BrandModeIcon() {
  return (
    <svg className="mode-choice-icon mode-choice-icon--brand" viewBox="0 0 128 128" aria-hidden="true">
      <rect className="icon-brand-grid" x="24" y="24" width="80" height="80" rx="12" />
      <path className="icon-brand-guides" d="M24 51h80M24 77h80M51 24v80M77 24v80" />
      <path className="icon-brand-mark" d="m64 41 18 13v20L64 87 46 74V54l18-13Z" />
      <path className="icon-brand-axis" d="M64 48v32M53 64h22" />
      <circle className="icon-brand-node" cx="32" cy="32" r="3" />
      <circle className="icon-brand-node" cx="96" cy="32" r="3" />
      <circle className="icon-brand-node" cx="32" cy="96" r="3" />
      <circle className="icon-brand-node" cx="96" cy="96" r="3" />
    </svg>
  );
}

function ClapperDivider() {
  const arrowPositions = Array.from({ length: 10 }, (_, index) => index * 52 + 18);

  return (
    <div className="clapper-divider" aria-hidden="true">
      <span className="clapper-divider__hinge" />
      <span className="clapper-divider__arm">
        <svg className="clapper-divider__blade" viewBox="0 0 56 520" preserveAspectRatio="none">
          <rect className="clapper-divider__blade-base" x="4" y="0" width="48" height="520" rx="2" />
          {arrowPositions.map((y) => (
            <path
              className="clapper-divider__arrow"
              key={y}
              d={`M 5 ${y} L 28 ${y + 20} L 51 ${y} L 51 ${y + 13} L 28 ${y + 33} L 5 ${y + 13} Z`}
            />
          ))}
          <path className="clapper-divider__blade-edge" d="M 4 0 V 520 M 52 0 V 520" />
        </svg>
      </span>
      <span className="clapper-divider__label">SLATE <b>01</b></span>
    </div>
  );
}

function ModeChoicePanel({
  id,
  eyebrow,
  title,
  description,
  detail,
  onChoose,
}: {
  id: ModeId;
  eyebrow: string;
  title: string;
  description: string;
  detail: string;
  onChoose: (mode: ModeId) => void;
}) {
  return (
    <button
      className={`mode-choice-panel mode-choice-panel--${id}`}
      type="button"
      data-mode={id}
      onClick={() => onChoose(id)}
    >
      <span className="mode-choice-panel__wash" aria-hidden="true" />
      <span className="mode-choice-panel__topline">
        <span className="mode-choice-panel__index">{id === "creation" ? "01" : "02"}</span>
        <span className="mode-choice-panel__eyebrow">{eyebrow}</span>
      </span>
      <span className="mode-choice-panel__body">
        <span className="mode-choice-panel__icon-wrap">
          {id === "creation" ? <CreationModeIcon /> : <BrandModeIcon />}
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

function VariantDock({ activeVariant, onChange }: { activeVariant: VariantId; onChange: (variant: VariantId) => void }) {
  return (
    <aside className="prototype-dock" aria-label="Prototype controls">
      <div className="prototype-dock__copy">
        <span className="prototype-dock__label">Prototype / composition study</span>
        <span className="prototype-dock__hint">Choose a mode to preview the one-way launch.</span>
      </div>
      <div className="prototype-dock__variants" role="group" aria-label="Visual variations">
        {variants.map((variant) => (
          <button
            className={`prototype-variant${activeVariant === variant.id ? " is-active" : ""}`}
            key={variant.id}
            type="button"
            onClick={() => onChange(variant.id)}
            title={variant.note}
          >
            <span className="prototype-variant__dot" aria-hidden="true" />
            {variant.label}
          </button>
        ))}
      </div>
    </aside>
  );
}

export function ModeLauncherPrototypePage() {
  const [activeVariant, setActiveVariant] = useState<VariantId>(readVariant);
  const [selectedMode, setSelectedMode] = useState<ModeId | null>(null);

  useEffect(() => {
    const nextUrl = `${window.location.pathname}?variant=${activeVariant}`;
    window.history.replaceState(null, "", nextUrl);
    setSelectedMode(null);
  }, [activeVariant]);

  const statusLabel = useMemo(() => {
    if (selectedMode === "creation") return "Opening personal creation";
    if (selectedMode === "brand") return "Opening brand professional";
    return "Awaiting a mode";
  }, [selectedMode]);

  function chooseMode(mode: ModeId) {
    // The launch is intentionally one-way. Variant controls are the only prototype reset.
    setSelectedMode((current) => current ?? mode);
  }

  return (
    <main
      className={`mode-launcher-prototype mode-launcher-prototype--${activeVariant}${selectedMode ? ` is-selecting is-selecting-${selectedMode}` : ""}`}
      data-selected-mode={selectedMode ?? undefined}
    >
      <header className="prototype-header">
        <span className="prototype-header__brand">ADCRAFT <span>/ NEW PROJECT</span></span>
        <span className="prototype-header__status"><i aria-hidden="true" /> {statusLabel}</span>
      </header>

      <section className="mode-choice-stage" aria-label="Choose a creation mode">
        <div className="stage-surface" aria-hidden="true" />
        <div className="mode-choice-assembly" key={activeVariant}>
          <ModeChoicePanel
            id="creation"
            eyebrow="Individual practice"
            title="个人创作"
            description="Start with your own point of view and turn a first idea into a moving frame."
            detail="For singular voices"
            onChoose={chooseMode}
          />
          <ModeChoicePanel
            id="brand"
            eyebrow="Brand system"
            title="品牌专业"
            description="Build inside a living identity with a guided system for every campaign decision."
            detail="For teams and systems"
            onChoose={chooseMode}
          />
          <ClapperDivider />
        </div>
        <p className="stage-caption">Select your working language <span>·</span> The slate opens with you</p>
      </section>

      <VariantDock
        activeVariant={activeVariant}
        onChange={setActiveVariant}
      />
    </main>
  );
}
