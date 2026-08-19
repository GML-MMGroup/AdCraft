import { useCallback, useEffect, useRef, useState } from "react";

interface HologramCarouselOptions {
  autoAdvanceMs?: number;
  preload?: (id: string) => void;
  reducedMotion?: boolean;
}

export type HologramTransitionDirection = "forward" | "backward";

const TRANSITION_DURATION_MS = 560;

function wrapIndex(index: number, length: number) {
  return ((index % length) + length) % length;
}

export function useHologramCarousel(
  items: string[],
  {
    autoAdvanceMs = 9_000,
    preload,
    reducedMotion = false,
  }: HologramCarouselOptions = {},
) {
  const [activeId, setActiveId] = useState<string | null>(items[0] ?? null);
  const [outgoingId, setOutgoingId] = useState<string | null>(null);
  const [transitionDirection, setTransitionDirection] = useState<HologramTransitionDirection | null>(null);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [pauseRevision, setPauseRevision] = useState(0);
  const pausedReasonsRef = useRef(new Set<string>());
  const transitionTimerRef = useRef<number | null>(null);
  const resolvedActiveId = activeId && items.includes(activeId) ? activeId : items[0] ?? null;

  useEffect(() => {
    if (!items.length) {
      setActiveId(null);
      setOutgoingId(null);
      setIsTransitioning(false);
      return;
    }
    if (activeId !== resolvedActiveId) {
      setActiveId(resolvedActiveId);
      setOutgoingId(null);
      setIsTransitioning(false);
      return;
    }
    if (outgoingId && !items.includes(outgoingId)) setOutgoingId(null);
  }, [activeId, items, outgoingId, resolvedActiveId]);

  const setPaused = useCallback((reason: string, paused: boolean) => {
    if (paused) {
      if (!pausedReasonsRef.current.has(reason)) {
        pausedReasonsRef.current.add(reason);
        setPauseRevision((revision) => revision + 1);
      }
      return;
    }
    if (pausedReasonsRef.current.delete(reason)) {
      setPauseRevision((revision) => revision + 1);
    }
  }, []);

  const selectIndex = useCallback((index: number, direction: HologramTransitionDirection) => {
    if (!items.length) return;
    const nextId = items[wrapIndex(index, items.length)];
    if (!nextId || nextId === resolvedActiveId) return;

    if (transitionTimerRef.current !== null) {
      window.clearTimeout(transitionTimerRef.current);
      transitionTimerRef.current = null;
    }

    if (reducedMotion || !resolvedActiveId) {
      setOutgoingId(null);
      setTransitionDirection(null);
      setIsTransitioning(false);
    } else {
      setOutgoingId(resolvedActiveId);
      setTransitionDirection(direction);
      setIsTransitioning(true);
      transitionTimerRef.current = window.setTimeout(() => {
        transitionTimerRef.current = null;
        setOutgoingId(null);
        setIsTransitioning(false);
      }, TRANSITION_DURATION_MS);
    }
    setActiveId(nextId);
  }, [items, reducedMotion, resolvedActiveId]);

  const currentIndex = Math.max(0, items.indexOf(resolvedActiveId ?? ""));
  const next = useCallback(() => selectIndex(currentIndex + 1, "forward"), [currentIndex, selectIndex]);
  const previous = useCallback(() => selectIndex(currentIndex - 1, "backward"), [currentIndex, selectIndex]);

  useEffect(() => {
    if (!preload || items.length < 2 || !resolvedActiveId) return;
    const index = items.indexOf(resolvedActiveId);
    preload(items[wrapIndex(index - 1, items.length)] ?? resolvedActiveId);
    preload(items[wrapIndex(index + 1, items.length)] ?? resolvedActiveId);
  }, [items, preload, resolvedActiveId]);

  useEffect(() => {
    if (items.length < 2 || pausedReasonsRef.current.size > 0) return undefined;
    const timer = window.setTimeout(() => selectIndex(currentIndex + 1, "forward"), autoAdvanceMs);
    return () => window.clearTimeout(timer);
  }, [autoAdvanceMs, currentIndex, items.length, pauseRevision, resolvedActiveId, selectIndex]);

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
    if (transitionTimerRef.current !== null) window.clearTimeout(transitionTimerRef.current);
  }, []);

  return {
    activeId: resolvedActiveId,
    activeIndex: currentIndex,
    outgoingId,
    transitionDirection,
    isTransitioning,
    next,
    previous,
    setPaused,
  };
}
