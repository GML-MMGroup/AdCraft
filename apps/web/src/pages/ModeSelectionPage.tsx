import { useEffect, useRef, useState } from "react";
import { useModeLaunch } from "../features/mode-selection/ModeLaunchContext";
import { useApp } from "../AppContextValue";
import { ModeChoicePanel, type ModeId } from "../features/mode-selection/ModeChoicePanel";
import "./mode-selection.css";


export function ModeSelectionPage() {
  const { startNewProject } = useApp();
  const launch = useModeLaunch();
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
      setError("Unable to create your project. Please choose a mode to try again.");
    }
  }

  const statusLabel = selectedMode
    ? `Opening ${selectedMode === "creation" ? "personal creation" : "brand professional"}…`
    : "Choose your creation mode";

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

      <section className="mode-choice-stage" aria-label="Choose a creation mode">
        <div className="stage-surface" aria-hidden="true" />
        <div className="mode-choice-assembly">
          <ModeChoicePanel
            id="creation"
            eyebrow="Individual practice"
            title="Personal Creation"
            description="Start with your own point of view and turn a first idea into a moving frame."
            onChoose={chooseMode}
            paused={selectedMode !== null}
          />
          <ModeChoicePanel
            id="brand"
            eyebrow="Brand system"
            title="Brand Professional"
            description="Build inside a living identity with a guided system for every campaign decision."
            onChoose={chooseMode}
            paused={selectedMode !== null}
          />
        </div>
      </section>

      {error && <p className="mode-selection-error" role="alert">{error}</p>}
    </main>
  );
}
