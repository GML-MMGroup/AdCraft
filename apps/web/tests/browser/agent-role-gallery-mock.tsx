import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import type { AgentRoleArtworkComponent } from "../../src/features/agent-canvas/chat/agent-role-animation/agentRoleAnimationRegistry.ts";
import type { AgentRoleMotionState } from "../../src/features/agent-canvas/chat/agent-role-animation/types.ts";
import BgmDirectorAnimation from "../../src/features/agent-canvas/chat/agent-role-animation/roles/BgmDirectorAnimation.tsx";
import CharacterDesignerAnimation from "../../src/features/agent-canvas/chat/agent-role-animation/roles/CharacterDesignerAnimation.tsx";
import ProductDesignerAnimation from "../../src/features/agent-canvas/chat/agent-role-animation/roles/ProductDesignerAnimation.tsx";
import PropDesignerAnimation from "../../src/features/agent-canvas/chat/agent-role-animation/roles/PropDesignerAnimation.tsx";
import QuickMediaAnimation from "../../src/features/agent-canvas/chat/agent-role-animation/roles/QuickMediaAnimation.tsx";
import SceneDesignerAnimation from "../../src/features/agent-canvas/chat/agent-role-animation/roles/SceneDesignerAnimation.tsx";
import ScriptWriterAnimation from "../../src/features/agent-canvas/chat/agent-role-animation/roles/ScriptWriterAnimation.tsx";
import StoryboardArtistAnimation from "../../src/features/agent-canvas/chat/agent-role-animation/roles/StoryboardArtistAnimation.tsx";
import VideoDirectorAnimation from "../../src/features/agent-canvas/chat/agent-role-animation/roles/VideoDirectorAnimation.tsx";
import WorldSettingAnimation from "../../src/features/agent-canvas/chat/agent-role-animation/roles/WorldSettingAnimation.tsx";

type GalleryRoleId =
  | "world"
  | "product"
  | "prop"
  | "character"
  | "scene"
  | "script"
  | "storyboard"
  | "video"
  | "bgm"
  | "quick";

interface GalleryRole {
  id: GalleryRoleId;
  label: string;
  description: string;
  component: AgentRoleArtworkComponent;
}

const ROLE_DEFINITIONS: readonly GalleryRole[] = [
  { id: "world", label: "World Setting", description: "Continental rotation", component: WorldSettingAnimation },
  { id: "product", label: "Product Designer", description: "Glass finish and camera flash", component: ProductDesignerAnimation },
  { id: "prop", label: "Prop Designer", description: "Blueprint guide construction", component: PropDesignerAnimation },
  { id: "character", label: "Character Designer", description: "Character study and refinement", component: CharacterDesignerAnimation },
  { id: "scene", label: "Scene Designer", description: "Scan-built environment", component: SceneDesignerAnimation },
  { id: "script", label: "Script Writer", description: "Line-by-line writing", component: ScriptWriterAnimation },
  { id: "storyboard", label: "Storyboard Artist", description: "Frame-by-frame staging", component: StoryboardArtistAnimation },
  { id: "video", label: "Video Director", description: "Reel timing and playback", component: VideoDirectorAnimation },
  { id: "bgm", label: "BGM Director", description: "A left-to-right note wave", component: BgmDirectorAnimation },
  { id: "quick", label: "Quick Media", description: "A responsive media trigger", component: QuickMediaAnimation },
] as const;

const STATE_LABELS: Record<AgentRoleMotionState, string> = {
  idle: "Idle",
  waiting: "Waiting",
  working: "Working",
};

const AUTO_PLAY_INTERVAL_MS = 6_000;

function Gallery() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [motionState, setMotionState] = useState<AgentRoleMotionState>("working");
  const [autoPlay, setAutoPlay] = useState(true);

  useEffect(() => {
    if (!autoPlay || motionState === "idle" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return undefined;
    }

    const interval = window.setInterval(() => {
      setActiveIndex((current) => (current + 1) % ROLE_DEFINITIONS.length);
    }, AUTO_PLAY_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [autoPlay, motionState]);

  const activeRole = ROLE_DEFINITIONS[activeIndex]!;

  return (
    <main className="gallery-shell">
      <header className="gallery-header">
        <div>
          <p className="gallery-eyebrow">AdCraft · Runtime artwork</p>
          <h1>Agent Role Animation Gallery</h1>
          <p className="gallery-intro">
            当前仅激活一个真实角色动画。点击卡片可锁定角色，再切换运行状态观察入场、循环与收尾。
          </p>
        </div>

        <div className="gallery-current" aria-live="polite">
          <span className="gallery-current__dot" aria-hidden="true" />
          <span>{activeRole.label}</span>
          <strong data-testid="gallery-motion-state">{STATE_LABELS[motionState]}</strong>
        </div>
      </header>

      <section className="gallery-toolbar" aria-label="Animation controls">
        <div className="gallery-segmented" aria-label="Motion state">
          {(["working", "waiting", "idle"] as const).map((state) => (
            <button
              key={state}
              type="button"
              className={motionState === state ? "is-selected" : undefined}
              aria-pressed={motionState === state}
              onClick={() => setMotionState(state)}
            >
              {STATE_LABELS[state]}
            </button>
          ))}
        </div>

        <button
          type="button"
          className={`gallery-autoplay${autoPlay ? " is-selected" : ""}`}
          aria-pressed={autoPlay}
          onClick={() => setAutoPlay((current) => !current)}
        >
          <span className="gallery-autoplay__icon" aria-hidden="true">{autoPlay ? "Ⅱ" : "▶"}</span>
          {autoPlay ? "Pause rotation" : "Resume rotation"}
        </button>
      </section>

      <section className="gallery-grid" aria-label="Agent roles">
        {ROLE_DEFINITIONS.map((role, index) => {
          const RoleArtwork = role.component;
          const isActive = index === activeIndex;
          const roleMotionState = isActive ? motionState : "idle";

          return (
            <button
              key={role.id}
              type="button"
              className={`gallery-card${isActive ? " is-active" : ""}`}
              data-gallery-role={role.id}
              data-active={isActive}
              aria-label={role.label}
              aria-pressed={isActive}
              onClick={() => {
                setActiveIndex(index);
                setAutoPlay(false);
              }}
            >
              <span className="gallery-artwork" aria-hidden="true">
                <RoleArtwork motionState={roleMotionState} />
              </span>
              <span className="gallery-card__copy">
                <strong>{role.label}</strong>
                <small>{role.description}</small>
              </span>
              <span className="gallery-card__state" aria-hidden="true">
                {isActive ? STATE_LABELS[motionState] : "Idle"}
              </span>
            </button>
          );
        })}
      </section>
    </main>
  );
}

const style = document.createElement("style");
style.textContent = `
  :root {
    color: #f4f7ff;
    background: #080b12;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-synthesis: none;
  }

  * { box-sizing: border-box; }

  body {
    min-width: 320px;
    min-height: 100vh;
    margin: 0;
    background:
      radial-gradient(circle at 15% -10%, rgba(84, 117, 233, 0.20), transparent 35%),
      radial-gradient(circle at 86% 4%, rgba(97, 215, 255, 0.10), transparent 28%),
      #080b12;
  }

  button { font: inherit; }

  .gallery-shell {
    width: min(1280px, calc(100% - 40px));
    margin: 0 auto;
    padding: 56px 0 72px;
  }

  .gallery-header {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 32px;
    margin-bottom: 28px;
  }

  .gallery-eyebrow {
    margin: 0 0 9px;
    color: #7fa4ff;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.13em;
    text-transform: uppercase;
  }

  h1 {
    margin: 0;
    font-size: clamp(30px, 4vw, 48px);
    font-weight: 620;
    letter-spacing: -0.045em;
    line-height: 1.05;
  }

  .gallery-intro {
    max-width: 650px;
    margin: 14px 0 0;
    color: #939bad;
    font-size: 14px;
    line-height: 1.65;
  }

  .gallery-current {
    display: grid;
    grid-template-columns: auto auto;
    align-items: center;
    gap: 3px 9px;
    min-width: 184px;
    padding: 13px 16px;
    border: 1px solid rgba(135, 158, 221, 0.20);
    border-radius: 14px;
    background: rgba(20, 25, 38, 0.72);
    box-shadow: 0 18px 48px rgba(0, 0, 0, 0.22);
    backdrop-filter: blur(16px);
  }

  .gallery-current__dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #78a1ff;
    box-shadow: 0 0 14px rgba(120, 161, 255, 0.9);
  }

  .gallery-current > span:nth-child(2) {
    color: #eef3ff;
    font-size: 13px;
    font-weight: 650;
  }

  .gallery-current strong {
    grid-column: 2;
    color: #7d879b;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .gallery-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 20px;
    padding: 8px;
    border: 1px solid rgba(139, 156, 201, 0.14);
    border-radius: 14px;
    background: rgba(17, 21, 31, 0.82);
  }

  .gallery-segmented {
    display: flex;
    gap: 3px;
  }

  .gallery-segmented button,
  .gallery-autoplay {
    min-height: 36px;
    border: 0;
    border-radius: 9px;
    color: #8992a4;
    background: transparent;
    cursor: pointer;
  }

  .gallery-segmented button {
    padding: 0 16px;
    font-size: 12px;
    font-weight: 650;
  }

  .gallery-segmented button.is-selected {
    color: #f8faff;
    background: #293249;
    box-shadow: inset 0 0 0 1px rgba(154, 177, 238, 0.13);
  }

  .gallery-autoplay {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    font-size: 12px;
  }

  .gallery-autoplay.is-selected { color: #b8c9f4; }

  .gallery-autoplay__icon {
    width: 18px;
    color: #7fa4ff;
    font-size: 10px;
    font-weight: 800;
    text-align: center;
  }

  .gallery-grid {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 12px;
  }

  .gallery-card {
    position: relative;
    display: flex;
    min-width: 0;
    flex-direction: column;
    align-items: stretch;
    overflow: hidden;
    padding: 0;
    border: 1px solid rgba(132, 146, 181, 0.14);
    border-radius: 18px;
    color: inherit;
    background: rgba(18, 22, 33, 0.86);
    box-shadow: 0 20px 52px rgba(0, 0, 0, 0.18);
    cursor: pointer;
    text-align: left;
  }

  .gallery-card::after {
    position: absolute;
    inset: 0;
    border: 1px solid transparent;
    border-radius: inherit;
    content: "";
    pointer-events: none;
  }

  .gallery-card.is-active {
    border-color: rgba(116, 153, 255, 0.48);
    background: linear-gradient(180deg, rgba(33, 42, 65, 0.97), rgba(17, 22, 33, 0.96));
    box-shadow: 0 24px 68px rgba(18, 40, 96, 0.28);
  }

  .gallery-card.is-active::after {
    border-color: rgba(145, 174, 255, 0.12);
  }

  .gallery-artwork {
    display: grid;
    width: 100%;
    aspect-ratio: 1;
    place-items: center;
    padding: 24px;
    border-bottom: 1px solid rgba(135, 151, 187, 0.10);
    background:
      radial-gradient(circle at 50% 44%, rgba(69, 85, 126, 0.24), transparent 55%),
      rgba(8, 11, 18, 0.38);
  }

  .gallery-artwork > svg {
    display: block;
    width: 100%;
    height: 100%;
    overflow: visible;
  }

  .gallery-card__copy {
    display: flex;
    min-height: 82px;
    flex-direction: column;
    gap: 5px;
    padding: 16px 17px 18px;
  }

  .gallery-card__copy strong {
    overflow: hidden;
    color: #edf2ff;
    font-size: 13px;
    font-weight: 650;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .gallery-card__copy small {
    overflow: hidden;
    color: #747e91;
    font-size: 11px;
    line-height: 1.45;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .gallery-card__state {
    position: absolute;
    top: 11px;
    right: 11px;
    padding: 4px 7px;
    border: 1px solid rgba(135, 156, 209, 0.14);
    border-radius: 999px;
    color: #697386;
    background: rgba(8, 11, 18, 0.72);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    backdrop-filter: blur(7px);
  }

  .gallery-card.is-active .gallery-card__state {
    border-color: rgba(128, 162, 255, 0.26);
    color: #a9c0ff;
  }

  button:focus-visible {
    outline: 2px solid #8eacff;
    outline-offset: 3px;
  }

  @media (hover: hover) and (pointer: fine) {
    .gallery-card:not(.is-active):hover {
      border-color: rgba(139, 164, 226, 0.28);
      background: rgba(24, 29, 42, 0.96);
    }

    .gallery-segmented button:hover,
    .gallery-autoplay:hover { color: #d9e2f8; }
  }

  @media (max-width: 980px) {
    .gallery-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  }

  @media (max-width: 640px) {
    .gallery-shell { width: min(100% - 24px, 480px); padding-top: 28px; }
    .gallery-header { align-items: stretch; flex-direction: column; gap: 20px; }
    .gallery-current { width: 100%; }
    .gallery-toolbar { align-items: stretch; flex-direction: column; }
    .gallery-segmented { display: grid; grid-template-columns: repeat(3, 1fr); }
    .gallery-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .gallery-artwork { padding: 18px; }
    .gallery-card__copy { min-height: 72px; padding: 13px; }
  }

  @media (prefers-reduced-motion: reduce) {
    .gallery-card,
    .gallery-segmented button,
    .gallery-autoplay { transition: none !important; }
  }
`;
document.head.append(style);

createRoot(document.getElementById("root")!).render(<Gallery />);
