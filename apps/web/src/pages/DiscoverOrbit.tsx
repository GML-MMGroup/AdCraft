import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent,
} from "react";

export type DiscoverOrbitItem = {
  title: string;
  image: string;
};

type DiscoverOrbitProps = {
  items: readonly DiscoverOrbitItem[];
  interactive: boolean;
  onSelect?: () => void;
};

type PointerDrag = {
  pointerId: number;
  startX: number;
  startTarget: number;
  lastX: number;
  lastTime: number;
  velocity: number;
};

const AUTO_SPEED = 0.055;
const DAMPING = 0.085;
const DRAG_THRESHOLD = 5;
const AUTO_RESUME_DELAY = 3200;
const DRAG_RESUME_DELAY = 4200;

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function initialIndex(total: number) {
  return Math.max(0, Math.floor((total - 1) / 2));
}

function useReducedMotion() {
  const [reduced, setReduced] = useState(() => (
    typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ));

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return reduced;
}

function distanceStyle(delta: number, index: number, now: number, spacing: number): CSSProperties {
  const distance = Math.abs(delta);
  const trackY = Math.sin(delta * 1.15) * Math.min(distance, 2.5) * 18 + distance * 5;
  const amplitude = 6 + Math.min(distance, 2.5) * 1.6;
  const floating = (
    Math.sin(now * 0.00062 + index * 1.37) * amplitude
    + Math.sin(now * 0.00021 + index * 0.73) * 2
  );
  const scale = Math.max(0.56, 1 - distance * 0.145);
  const blur = Math.min(13, Math.max(0, distance - 0.12) * 3.15);
  const opacity = Math.max(0.12, 1 - distance * 0.185);

  return {
    "--discover-track-x": `${delta * spacing}px`,
    "--discover-track-y": `${trackY + floating}px`,
    "--discover-track-scale": `${scale}`,
    "--discover-track-rotate": `${delta * -2.8}deg`,
    "--discover-track-blur": `${blur}px`,
    "--discover-track-opacity": `${opacity}`,
    "--discover-track-depth": `${Math.round((20 - Math.min(distance, 19)) * 10)}`,
  } as CSSProperties;
}

export function DiscoverOrbit({ items, interactive, onSelect }: DiscoverOrbitProps) {
  const reducedMotion = useReducedMotion();
  const firstIndex = initialIndex(items.length);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef<Array<HTMLElement | null>>([]);
  const targetRef = useRef(firstIndex);
  const currentRef = useRef(firstIndex);
  const activeIndexRef = useRef(firstIndex);
  const autoDirectionRef = useRef(1);
  const pauseAutoUntilRef = useRef(0);
  const inertiaRef = useRef(0);
  const snapAtRef = useRef<number | null>(null);
  const dragRef = useRef<PointerDrag | null>(null);
  const didDragRef = useRef(false);
  const hoveringRef = useRef(false);
  const [activeIndex, setActiveIndex] = useState(firstIndex);
  const [isInteracting, setIsInteracting] = useState(false);

  const maxIndex = Math.max(0, items.length - 1);

  const pauseAuto = (duration = AUTO_RESUME_DELAY) => {
    pauseAutoUntilRef.current = performance.now() + duration;
  };

  const setActive = (index: number) => {
    const nextIndex = clamp(index, 0, maxIndex);
    activeIndexRef.current = nextIndex;
    setActiveIndex(nextIndex);
  };

  const moveTo = (nextTarget: number, pauseDuration = AUTO_RESUME_DELAY) => {
    targetRef.current = clamp(nextTarget, 0, maxIndex);
    inertiaRef.current = 0;
    snapAtRef.current = performance.now() + 160;
    pauseAuto(pauseDuration);
    setActive(Math.round(targetRef.current));
  };

  const spacingFor = () => {
    const width = rootRef.current?.clientWidth ?? 1200;
    return clamp(width * 0.205, 225, 330);
  };

  const syncCards = (now: number) => {
    const spacing = spacingFor();
    cardRefs.current.forEach((card, index) => {
      if (!card) return;
      const styles = distanceStyle(index - currentRef.current, index, now, spacing);
      Object.entries(styles).forEach(([name, value]) => card.style.setProperty(name, String(value)));
    });
  };

  useLayoutEffect(() => {
    targetRef.current = clamp(targetRef.current, 0, maxIndex);
    currentRef.current = clamp(currentRef.current, 0, maxIndex);
    const nextActiveIndex = clamp(activeIndexRef.current, 0, maxIndex);
    activeIndexRef.current = nextActiveIndex;
    setActiveIndex(nextActiveIndex);
    syncCards(performance.now());
    // The references intentionally contain the latest geometry and card elements.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items.length, maxIndex]);

  useEffect(() => {
    if (!interactive || reducedMotion || items.length < 2) {
      syncCards(performance.now());
      return undefined;
    }

    let frameId = 0;
    let lastTime = performance.now();
    const render = (now: number) => {
      if (document.hidden) {
        lastTime = now;
        frameId = requestAnimationFrame(render);
        return;
      }
      const deltaTime = Math.min((now - lastTime) / 1000, 0.05);
      lastTime = now;
      const dragging = dragRef.current !== null;

      if (!dragging && inertiaRef.current !== 0) {
        targetRef.current = clamp(targetRef.current + inertiaRef.current * deltaTime, 0, maxIndex);
        inertiaRef.current *= Math.pow(0.88, deltaTime * 60);
        if (Math.abs(inertiaRef.current) < 0.025) inertiaRef.current = 0;
      }

      if (!dragging && snapAtRef.current !== null && now >= snapAtRef.current) {
        targetRef.current = Math.round(targetRef.current);
        inertiaRef.current = 0;
        snapAtRef.current = null;
      }

      const canAutoMove = (
        !dragging
        && !hoveringRef.current
        && !document.hidden
        && now >= pauseAutoUntilRef.current
        && inertiaRef.current === 0
        && snapAtRef.current === null
      );
      if (canAutoMove) {
        targetRef.current += autoDirectionRef.current * AUTO_SPEED * deltaTime;
        if (targetRef.current >= maxIndex) {
          targetRef.current = maxIndex;
          autoDirectionRef.current = -1;
          pauseAutoUntilRef.current = now + 1100;
        } else if (targetRef.current <= 0) {
          targetRef.current = 0;
          autoDirectionRef.current = 1;
          pauseAutoUntilRef.current = now + 1100;
        }
      }

      const smoothing = 1 - Math.pow(1 - DAMPING, deltaTime * 60);
      currentRef.current += (targetRef.current - currentRef.current) * smoothing;
      syncCards(now);

      if (Math.abs(targetRef.current - currentRef.current) < 0.02) {
        const closestIndex = Math.round(currentRef.current);
        if (closestIndex !== activeIndexRef.current) {
          activeIndexRef.current = closestIndex;
          setActiveIndex(closestIndex);
        }
      }

      frameId = requestAnimationFrame(render);
    };

    frameId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(frameId);
    // The loop deliberately owns a mutable animation model outside React renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactive, items.length, maxIndex, reducedMotion]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || !interactive) return undefined;

    const onPointerDown = (event: globalThis.PointerEvent) => {
      if (event.button !== 0) return;
      root.setPointerCapture(event.pointerId);
      dragRef.current = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startTarget: targetRef.current,
        lastX: event.clientX,
        lastTime: performance.now(),
        velocity: 0,
      };
      didDragRef.current = false;
      inertiaRef.current = 0;
      snapAtRef.current = null;
      pauseAuto(DRAG_RESUME_DELAY);
      setIsInteracting(true);
    };

    const onPointerMove = (event: globalThis.PointerEvent) => {
      const drag = dragRef.current;
      if (!drag || drag.pointerId !== event.pointerId) return;
      const now = performance.now();
      const deltaX = event.clientX - drag.startX;
      if (Math.abs(deltaX) > DRAG_THRESHOLD) didDragRef.current = true;
      targetRef.current = clamp(drag.startTarget - deltaX / spacingFor(), 0, maxIndex);
      drag.velocity = (event.clientX - drag.lastX) / Math.max(8, now - drag.lastTime);
      drag.lastX = event.clientX;
      drag.lastTime = now;
      setActive(Math.round(targetRef.current));
    };

    const finishDrag = (event: globalThis.PointerEvent, cancelled = false) => {
      const drag = dragRef.current;
      if (!drag || drag.pointerId !== event.pointerId) return;
      if (root.hasPointerCapture(event.pointerId)) root.releasePointerCapture(event.pointerId);
      dragRef.current = null;
      setIsInteracting(false);
      if (!cancelled && didDragRef.current) {
        inertiaRef.current = clamp((-drag.velocity / spacingFor()) * 1000, -4, 4);
        snapAtRef.current = performance.now() + 260;
      } else {
        targetRef.current = Math.round(targetRef.current);
        snapAtRef.current = null;
      }
      pauseAuto(DRAG_RESUME_DELAY);
    };

    const onWheel = (event: WheelEvent) => {
      if (reducedMotion) return;
      const amount = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
      if (amount === 0) return;
      event.preventDefault();
      moveTo(targetRef.current + amount * 0.0027);
    };

    const onPointerCancel = (event: globalThis.PointerEvent) => finishDrag(event, true);
    root.addEventListener("pointerdown", onPointerDown);
    root.addEventListener("pointermove", onPointerMove);
    root.addEventListener("pointerup", finishDrag);
    root.addEventListener("pointercancel", onPointerCancel);
    root.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      root.removeEventListener("pointerdown", onPointerDown);
      root.removeEventListener("pointermove", onPointerMove);
      root.removeEventListener("pointerup", finishDrag);
      root.removeEventListener("pointercancel", onPointerCancel);
      root.removeEventListener("wheel", onWheel);
    };
    // Event listeners intentionally bind once to the mutable interaction model.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactive, maxIndex, reducedMotion]);

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (!interactive) return;
    if (event.key === "ArrowRight") {
      event.preventDefault();
      moveTo(Math.round(targetRef.current) + 1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      moveTo(Math.round(targetRef.current) - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      moveTo(0);
    } else if (event.key === "End") {
      event.preventDefault();
      moveTo(maxIndex);
    }
  };

  const handleCardClick = (index: number, event: MouseEvent<HTMLElement>) => {
    if (!interactive) return;
    if (didDragRef.current) {
      event.preventDefault();
      didDragRef.current = false;
      return;
    }
    const isCentered = index === activeIndexRef.current && Math.abs(targetRef.current - currentRef.current) < 0.08;
    if (isCentered) {
      onSelect?.();
      return;
    }
    moveTo(index);
  };

  const handleCardFocus = (index: number) => {
    if (!interactive) return;
    moveTo(index);
  };

  const setHovering = (value: boolean) => {
    if (!interactive) return;
    hoveringRef.current = value;
    setIsInteracting(value || dragRef.current !== null);
    if (value) pauseAuto();
  };

  const rootClassName = [
    "discover-orbit",
    interactive ? "discover-orbit--interactive" : "discover-orbit--static",
    reducedMotion ? "discover-orbit--reduced-motion" : "",
  ].filter(Boolean).join(" ");

  return (
    <div
      ref={rootRef}
      className={rootClassName}
      role="region"
      aria-label="Discover inspiration gallery"
      aria-roledescription={interactive ? "carousel" : undefined}
      data-active-index={activeIndex}
      data-paused={isInteracting}
      data-reveal-item
      style={{ "--home-reveal-delay": "170ms" } as CSSProperties}
    >
      <div className="discover-orbit__track">
        {items.map((item, index) => {
          const isActive = index === activeIndex;
          const commonProps = {
            ref: (node: HTMLElement | null) => { cardRefs.current[index] = node; },
            className: `discover-orbit__card ${isActive ? "is-active" : ""}`,
            "data-index": index,
            "aria-current": isActive ? "true" as const : "false" as const,
          };

          return interactive ? (
            <button
              {...commonProps}
              key={item.title}
              type="button"
              aria-label={item.title}
              onClick={(event) => handleCardClick(index, event)}
              onFocus={() => handleCardFocus(index)}
              onKeyDown={handleKeyDown}
              onPointerEnter={() => setHovering(true)}
              onPointerLeave={() => setHovering(false)}
            >
              <DiscoverTrackCard item={item} />
            </button>
          ) : (
            <article {...commonProps} key={item.title} aria-label={item.title}>
              <DiscoverTrackCard item={item} />
            </article>
          );
        })}
      </div>
    </div>
  );
}

function DiscoverTrackCard({ item }: { item: DiscoverOrbitItem }) {
  return (
    <span className="discover-orbit__card-frame">
      <img className="discover-orbit__image" src={item.image} alt="" loading="lazy" decoding="async" />
      <span className="discover-orbit__glass" aria-hidden="true" />
      <span className="discover-orbit__title" data-home-typography-region="cardTitle">{item.title}</span>
    </span>
  );
}
