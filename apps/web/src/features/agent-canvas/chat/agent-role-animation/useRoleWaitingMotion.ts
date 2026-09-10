import { useEffect, type RefObject } from "react";

/** Waiting is state feedback, including when the full artwork has no waiting tracks. */
export function useRoleWaitingMotion(ref: RefObject<HTMLElement | null>, enabled: boolean) {
  useEffect(() => {
    const element = ref.current;
    if (!enabled || !element || typeof element.animate !== "function") return;
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    let animation: Animation | null = null;
    const update = () => {
      if (preference.matches) { animation?.cancel(); animation = null; return; }
      if (!animation && document.visibilityState !== "hidden") {
        animation = element.animate([{ opacity: 0.78 }, { opacity: 1 }, { opacity: 0.78 }], {
          duration: 1800, iterations: Infinity, easing: "cubic-bezier(0.77, 0, 0.175, 1)",
        });
        void animation.finished.catch(() => undefined);
      }
      if (document.visibilityState === "hidden") animation?.pause();
      else if (animation?.playState === "paused") animation.play();
    };
    preference.addEventListener("change", update);
    document.addEventListener("visibilitychange", update);
    update();
    return () => {
      preference.removeEventListener("change", update);
      document.removeEventListener("visibilitychange", update);
      animation?.cancel();
    };
  }, [enabled, ref]);
}
