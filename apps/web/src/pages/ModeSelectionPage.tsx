import { useEffect, useRef, useState } from "react";
import { useModeLaunch } from "../features/mode-selection/ModeLaunchContext";
import { useApp } from "../AppContextValue";
import { ModeChoicePanel, type ModeId } from "../features/mode-selection/ModeChoicePanel";
import { useLocale, localeText } from "../i18n/locale.tsx";
import "./mode-selection.css";


export function ModeSelectionPage() {
  const { startNewProject } = useApp();
  const launch = useModeLaunch();
  const { locale } = useLocale();
  const labels = locale === "zh-CN" ? localeText.zh.mode : localeText.en.mode;
  const [selectedMode, setSelectedMode] = useState<ModeId | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  async function chooseMode(mode: ModeId, keyboard = false) {
    if (pending.current) return;
    pending.current = true;
    setError(null);
    setSelectedMode(mode);
    try {
      const projectId = await startNewProject(mode);
      if (!mounted.current) return;
      if (!projectId) throw new Error("Project creation failed");
      launch?.begin(mode, projectId, keyboard);
    } catch {
      if (!mounted.current) return;
      pending.current = false;
      setSelectedMode(null);
      setError(labels.error);
    }
  }

  const statusLabel = selectedMode
    ? (selectedMode === "creation" ? labels.openingPersonal : labels.openingBrand)
    : labels.status;

  return (
    <main
      className={`mode-selection${launch?.revealing ? ` is-selecting is-selecting-${selectedMode}${launch.keyboard ? " is-keyboard-launch" : ""}` : ""}`}
      data-selected-mode={selectedMode ?? undefined}
      aria-busy={selectedMode !== null}
      onTransitionEnd={event => { if (event.target === event.currentTarget && event.propertyName === "opacity") launch?.finish(); }}
    >
      <header className="mode-selection-header">
        <span className="mode-selection-header__brand">ADCRAFT <span>/ NEW PROJECT</span></span>
        <span className="mode-selection-header__status" role="status"><i aria-hidden="true" /> {statusLabel}</span>
      </header>

      <section className="mode-choice-stage" aria-label={labels.stageLabel}>
        <div className="stage-surface" aria-hidden="true" />
        <div className="mode-choice-assembly">
          <ModeChoicePanel
            id="creation"
            eyebrow={labels.personalEyebrow}
            title={labels.personalTitle}
            description={labels.personalDescription}
            onChoose={chooseMode}
            paused={selectedMode !== null}
          />
          <ModeChoicePanel
            id="brand"
            eyebrow={labels.brandEyebrow}
            title={labels.brandTitle}
            description={labels.brandDescription}
            onChoose={chooseMode}
            paused={selectedMode !== null}
          />
        </div>
      </section>

      {error && <p className="mode-selection-error" role="alert">{error}</p>}
    </main>
  );
}
