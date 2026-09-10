import { useState } from "react";
import { createRoot } from "react-dom/client";

import "../../src/features/agent-canvas/chat/agent-canvas-chat.css";
import SceneDesignerAnimation from "../../src/features/agent-canvas/chat/agent-role-animation/roles/SceneDesignerAnimation.tsx";

interface AnimationSnapshot {
  cssTransitionCount: number;
  roleWaapiCount: number;
  totalAnimationCount: number;
  transitionDurationsMs: number[];
  transitionDuration: string;
  transitionProperty: string;
}

let toggleArtwork: (() => void) | null = null;

function probeRoot(): HTMLElement {
  const root = document.querySelector<HTMLElement>("[data-role-motion-probe]");
  if (!root) throw new Error("Role motion probe is not mounted");
  return root;
}

function snapshot(): AnimationSnapshot {
  const root = probeRoot();
  const asset = root.querySelector<HTMLElement>(".agent-chat__role-animation-static");
  if (!asset) throw new Error("Missing role animation asset");
  const animations = root.getAnimations({ subtree: true });
  const isCssTransition = (animation: Animation): boolean => (
    animation.constructor.name === "CSSTransition"
  );
  const isRoleWaapi = (animation: Animation): boolean => {
    const target = (animation.effect as KeyframeEffect | null)?.target;
    return target instanceof Element && target.closest("[data-agent-role]") !== null;
  };

  return {
    cssTransitionCount: animations.filter(isCssTransition).length,
    roleWaapiCount: animations.filter((animation) => (
      !isCssTransition(animation) && isRoleWaapi(animation)
    )).length,
    totalAnimationCount: animations.length,
    transitionDurationsMs: animations
      .filter(isCssTransition)
      .map((animation) => Number(animation.effect?.getTiming().duration)),
    transitionDuration: getComputedStyle(asset).transitionDuration,
    transitionProperty: getComputedStyle(asset).transitionProperty,
  };
}

async function swapAssets(): Promise<AnimationSnapshot> {
  void getComputedStyle(
    probeRoot().querySelector<HTMLElement>(".agent-chat__role-animation-static")!,
  ).opacity;
  toggleArtwork?.();
  await new Promise(requestAnimationFrame);
  await new Promise(requestAnimationFrame);
  return snapshot();
}

function App() {
  const [artworkVisible, setArtworkVisible] = useState(false);
  toggleArtwork = () => setArtworkVisible((visible) => !visible);

  return (
    <div className="agent-chat" data-role-motion-probe>
      <span className="agent-chat__role-animation-frame" aria-hidden="true">
        <img
          className={`agent-chat__role-animation-asset agent-chat__role-animation-static ${artworkVisible ? "is-hidden" : "is-visible"}`}
          src="/imgs/agent-role-icons/scene-designer-20260906-atlas-replica.svg"
          width="32"
          height="32"
          alt=""
        />
        <span
          className={`agent-chat__role-animation-asset agent-chat__role-animation-artwork ${artworkVisible ? "is-visible" : "is-hidden"}`}
        >
          <SceneDesignerAnimation motionState="working" />
        </span>
      </span>
    </div>
  );
}

Object.assign(window, {
  agentRoleReducedMotionProbe: {
    isReady: () => toggleArtwork !== null,
    snapshot,
    swapAssets,
  },
});

createRoot(document.getElementById("root")!).render(<App />);
