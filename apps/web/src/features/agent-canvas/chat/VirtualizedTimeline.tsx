import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

export interface VirtualizedTimelineProps<T> {
  items: readonly T[];
  getKey: (item: T, index: number) => string;
  renderItem: (item: T, index: number) => ReactNode;
  initialVisibleCount?: number;
  preloadMargin?: string;
  estimatedItemHeight?: number;
}

/**
 * Keeps expensive historical message subtrees out of React until they are
 * near the scroll viewport. Once hydrated, an item stays mounted so message
 * interactions, measured heights, and canvas links remain stable.
 */
export function VirtualizedTimeline<T>({
  items,
  getKey,
  renderItem,
  initialVisibleCount = 8,
  preloadMargin = "800px",
  estimatedItemHeight = 160,
}: VirtualizedTimelineProps<T>) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const itemRefs = useRef(new Map<string, HTMLDivElement>());
  const [hydratedKeys, setHydratedKeys] = useState<Set<string>>(() => (
    new Set(items.slice(0, initialVisibleCount).map(getKey))
  ));

  useEffect(() => {
    const nextKeys = new Set(items.slice(0, initialVisibleCount).map(getKey));
    setHydratedKeys((current) => {
      const next = new Set(current);
      nextKeys.forEach((key) => next.add(key));
      return next;
    });
  }, [getKey, initialVisibleCount, items]);

  const registerItem = useCallback((key: string, element: HTMLDivElement | null) => {
    if (element) itemRefs.current.set(key, element);
    else itemRefs.current.delete(key);
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    const observed = [...itemRefs.current.values()];
    if (typeof IntersectionObserver === "undefined") {
      setHydratedKeys((current) => {
        const next = new Set(current);
        items.forEach((item, index) => next.add(getKey(item, index)));
        return next;
      });
      return undefined;
    }

    const observer = new IntersectionObserver((entries) => {
      const entering = entries
        .filter((entry) => entry.isIntersecting)
        .map((entry) => entry.target.getAttribute("data-timeline-key"))
        .filter((key): key is string => Boolean(key));
      if (!entering.length) return;
      setHydratedKeys((current) => {
        const next = new Set(current);
        entering.forEach((key) => next.add(key));
        return next;
      });
    }, {
      root: host.closest(".agent-chat__timeline"),
      rootMargin: preloadMargin,
    });
    observed.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, [getKey, items, preloadMargin]);

  return (
    <div ref={hostRef} className="agent-chat__timeline-virtualized">
      {items.map((item, index) => {
        const key = getKey(item, index);
        const hydrated = hydratedKeys.has(key);
        return (
          <div
            key={key}
            ref={(element) => registerItem(key, element)}
            className="agent-chat__timeline-virtualized-item"
            data-timeline-key={key}
            data-timeline-hydrated={hydrated ? "true" : "false"}
            style={{
              contentVisibility: "auto",
              containIntrinsicSize: `${estimatedItemHeight}px`,
              minHeight: hydrated ? undefined : `${estimatedItemHeight}px`,
            }}
          >
            {hydrated
              ? renderItem(item, index)
              : <div className="agent-chat__timeline-virtualized-placeholder" aria-hidden="true" />}
          </div>
        );
      })}
    </div>
  );
}
