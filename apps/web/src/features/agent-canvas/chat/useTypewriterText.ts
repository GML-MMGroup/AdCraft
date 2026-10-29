import { useEffect, useRef, useState } from "react";

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useTypewriterText(target: string, { animate = true }: { animate?: boolean } = {}): string {
  const [shown, setShown] = useState(() => animate && !prefersReducedMotion() ? "" : target);
  const shownRef = useRef(shown);
  const frameRef = useRef<number | null>(null);
  const targetRef = useRef(target);

  useEffect(() => {
    targetRef.current = target;
    const current = shownRef.current;
    const reduced = prefersReducedMotion();
    if (!animate || reduced || !target.startsWith(current)) {
      shownRef.current = target;
      setShown(target);
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
      return undefined;
    }
    if (target === current) return undefined;

    const tick = () => {
      const nextTarget = targetRef.current;
      const previous = shownRef.current;
      if (!nextTarget.startsWith(previous)) {
        shownRef.current = nextTarget;
        setShown(nextTarget);
        frameRef.current = null;
        return;
      }
      const backlog = nextTarget.length - previous.length;
      if (backlog <= 0) {
        frameRef.current = null;
        return;
      }
      const step = Math.max(1, Math.ceil(backlog / 24));
      const next = nextTarget.slice(0, previous.length + step);
      shownRef.current = next;
      setShown(next);
      frameRef.current = requestAnimationFrame(tick);
    };
    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    };
  }, [animate, target]);

  useEffect(() => () => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
  }, []);

  return shown;
}
