import { useEffect, useMemo, useRef, useState } from "react";

export interface TypewriterPlayback {
  cache: Map<string, string>;
  key: string;
}

// Keep the reading pace steady, regardless of reply length or buffered content.
const CHARACTERS_PER_SECOND = 24;
const MAX_FRAME_DELTA_MS = 100;
const segmenter = typeof Intl.Segmenter === "function"
  ? new Intl.Segmenter(undefined, { granularity: "grapheme" }) : null;

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useTypewriterText(target: string, {
  animate = true,
  playback,
}: { animate?: boolean; playback?: TypewriterPlayback } = {}): string {
  const { cache, key } = playback ?? {};
  const [shown, setShown] = useState(() => {
    if (!animate || prefersReducedMotion()) return target;
    const previous = key ? cache?.get(key) ?? "" : "";
    return target.startsWith(previous) ? previous : "";
  });
  const shownRef = useRef(shown);
  const characterBudgetRef = useRef(0);
  const lastFrameTimeRef = useRef<number | null>(null);
  const boundaries = useMemo(() => {
    if (segmenter) return Array.from(segmenter.segment(target), part => part.index + part.segment.length);
    let offset = 0;
    return Array.from(target, character => (offset += character.length));
  }, [target]);

  useEffect(() => {
    const publish = (text: string) => {
      shownRef.current = text;
      if (cache && key) cache.set(key, text);
      setShown(text);
    };
    if (!animate || prefersReducedMotion() || !target.startsWith(shownRef.current)) {
      characterBudgetRef.current = 0;
      lastFrameTimeRef.current = null;
      publish(target);
      return undefined;
    }
    if (cache && key) cache.set(key, shownRef.current);
    let index = boundaries.findIndex(boundary => boundary > shownRef.current.length);
    if (index === -1) {
      lastFrameTimeRef.current = null;
      return undefined;
    }
    lastFrameTimeRef.current ??= performance.now();
    let frame: number;
    const tick = (now: number) => {
      // A background tab or stalled frame must not release a large burst on resume.
      const elapsed = Math.min(MAX_FRAME_DELTA_MS, Math.max(0, now - lastFrameTimeRef.current!));
      characterBudgetRef.current += elapsed * CHARACTERS_PER_SECOND / 1_000;
      lastFrameTimeRef.current = now;
      const step = Math.floor(characterBudgetRef.current);
      if (step > 0) {
        characterBudgetRef.current -= step;
        index = Math.min(boundaries.length, index + step);
        publish(target.slice(0, boundaries[index - 1]));
      }
      if (index < boundaries.length) frame = requestAnimationFrame(tick);
      else {
        characterBudgetRef.current = 0;
        lastFrameTimeRef.current = null;
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [animate, boundaries, cache, key, target]);

  return !animate || !target.startsWith(shown) ? target : shown;
}
