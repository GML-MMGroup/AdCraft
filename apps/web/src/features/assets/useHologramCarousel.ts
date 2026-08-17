import { useCallback, useEffect, useRef, useState } from "react";

interface HologramCarouselOptions {
  autoAdvanceMs?: number;
  interactionResumeMs?: number;
  preload?: (id: string) => void;
  reducedMotion?: boolean;
}

function wrapIndex(index: number, length: number) {
  return ((index % length) + length) % length;
}

export function useHologramCarousel(
  items: string[],
  {
    autoAdvanceMs = 9_000,
    interactionResumeMs = 3_200,
    preload,
    reducedMotion = false,
  }: HologramCarouselOptions = {},
) {
  const [activeId, setActiveId] = useState<string | null>(items[0] ?? null);
  const [displayedId, setDisplayedId] = useState<string | null>(items[0] ?? null);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [pauseRevision, setPauseRevision] = useState(0);
  const pausedReasonsRef = useRef(new Set<string>());
  const resumeTimersRef = useRef(new Map<string, number>());
  const transitionTimerRef = useRef<number | null>(null);
  const transitionSettleTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!items.length) {
      setActiveId(null);
      setDisplayedId(null);
      return;
    }
    if (!activeId || !items.includes(activeId)) {
      setActiveId(items[0] ?? null);
      setDisplayedId(items[0] ?? null);
      return;
    }
    if (!displayedId || !items.includes(displayedId)) setDisplayedId(activeId);
  }, [activeId, displayedId, items]);

  const setPaused = useCallback((reason: string, paused: boolean) => {
    const existingTimer = resumeTimersRef.current.get(reason);
    if (existingTimer !== undefined) {
      window.clearTimeout(existingTimer);
      resumeTimersRef.current.delete(reason);
    }

    if (paused) {
      if (!pausedReasonsRef.current.has(reason)) {
        pausedReasonsRef.current.add(reason);
        setPauseRevision((revision) => revision + 1);
      }
      return;
    }

    const timer = window.setTimeout(() => {
      resumeTimersRef.current.delete(reason);
      if (pausedReasonsRef.current.delete(reason)) {
        setPauseRevision((revision) => revision + 1);
      }
    }, interactionResumeMs);
    resumeTimersRef.current.set(reason, timer);
  }, [interactionResumeMs]);

  const selectIndex = useCallback((index: number, userInitiated = true) => {
    if (!items.length) return;
    const nextId = items[wrapIndex(index, items.length)];
    if (!nextId || nextId === activeId) return;

    if (userInitiated) {
      pausedReasonsRef.current.add("interaction");
      setPauseRevision((revision) => revision + 1);
      const existingTimer = resumeTimersRef.current.get("interaction");
      if (existingTimer !== undefined) window.clearTimeout(existingTimer);
      const timer = window.setTimeout(() => {
        resumeTimersRef.current.delete("interaction");
        if (pausedReasonsRef.current.delete("interaction")) {
          setPauseRevision((revision) => revision + 1);
        }
      }, interactionResumeMs);
      resumeTimersRef.current.set("interaction", timer);
    }

    if (reducedMotion) {
      setDisplayedId(nextId);
    } else {
      setIsTransitioning(true);
      if (transitionTimerRef.current !== null) window.clearTimeout(transitionTimerRef.current);
      if (transitionSettleTimerRef.current !== null) window.clearTimeout(transitionSettleTimerRef.current);
      transitionTimerRef.current = window.setTimeout(() => {
        transitionTimerRef.current = null;
        setDisplayedId(nextId);
        transitionSettleTimerRef.current = window.setTimeout(() => {
          transitionSettleTimerRef.current = null;
          setIsTransitioning(false);
        }, 20);
      }, 160);
    }
    setActiveId(nextId);
  }, [activeId, interactionResumeMs, items, reducedMotion]);

  const currentIndex = Math.max(0, items.indexOf(activeId ?? ""));
  const next = useCallback(() => selectIndex(currentIndex + 1), [currentIndex, selectIndex]);
  const previous = useCallback(() => selectIndex(currentIndex - 1), [currentIndex, selectIndex]);
  const select = useCallback((id: string) => {
    const index = items.indexOf(id);
    if (index >= 0) selectIndex(index);
  }, [items, selectIndex]);

  useEffect(() => {
    if (!preload || items.length < 2 || !activeId) return;
    const index = items.indexOf(activeId);
    preload(items[wrapIndex(index - 1, items.length)] ?? activeId);
    preload(items[wrapIndex(index + 1, items.length)] ?? activeId);
  }, [activeId, items, preload]);

  useEffect(() => {
    if (reducedMotion || items.length < 2 || pausedReasonsRef.current.size > 0) return undefined;
    const timer = window.setTimeout(() => selectIndex(currentIndex + 1, false), autoAdvanceMs);
    return () => window.clearTimeout(timer);
  }, [activeId, autoAdvanceMs, currentIndex, items.length, pauseRevision, reducedMotion, selectIndex]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.hidden) {
        if (!pausedReasonsRef.current.has("visibility")) {
          pausedReasonsRef.current.add("visibility");
          setPauseRevision((revision) => revision + 1);
        }
        return;
      }
      if (pausedReasonsRef.current.delete("visibility")) {
        setPauseRevision((revision) => revision + 1);
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, []);

  useEffect(() => () => {
    for (const timer of resumeTimersRef.current.values()) window.clearTimeout(timer);
    if (transitionTimerRef.current !== null) window.clearTimeout(transitionTimerRef.current);
    if (transitionSettleTimerRef.current !== null) window.clearTimeout(transitionSettleTimerRef.current);
  }, []);

  return {
    activeId,
    activeIndex: currentIndex,
    displayedId,
    isTransitioning,
    next,
    previous,
    select,
    setPaused,
  };
}
