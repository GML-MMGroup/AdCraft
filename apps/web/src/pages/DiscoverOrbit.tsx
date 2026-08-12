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

type TrackId = "upper" | "lower";

type PointerDrag = {
  pointerId: number;
  startX: number;
  startTarget: number;
  lastX: number;
  lastTime: number;
  velocity: number;
};

type TrackConfig = {
  id: TrackId;
  direction: 1 | -1;
  phase: number;
};

const TRACKS: readonly TrackConfig[] = [
  { id: "upper", direction: 1, phase: -3 },
  { id: "lower", direction: -1, phase: -2 },
];
const AUTO_SPEED = 0.055;
const DAMPING = 0.085;
const DRAG_THRESHOLD = 5;
const AUTO_RESUME_DELAY = 3200;
const DRAG_RESUME_DELAY = 4200;

function wrapDelta(value: number, length: number) {
  if (length <= 1) return 0;
  return ((value + length / 2) % length + length) % length - length / 2;
}

function wrapIndex(index: number, length: number) {
  return ((index % length) + length) % length;
}

function nearestIndex(current: number, phase: number, direction: 1 | -1, length: number) {
  let closest = 0;
  let smallestDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < length; index += 1) {
    const delta = wrapDelta(index + direction * current + phase, length);
    if (Math.abs(delta) < smallestDistance) {
      closest = index;
      smallestDistance = Math.abs(delta);
    }
  }
  return closest;
}

function targetForCard(index: number, track: TrackConfig, current: number, length: number) {
  const offset = wrapDelta(index + track.direction * current + track.phase, length);
  return current - offset * track.direction;
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

function distanceStyle(
  delta: number,
  cardIndex: number,
  now: number,
  spacing: number,
  track: TrackConfig,
): CSSProperties {
  const distance = Math.abs(delta);
  const arc = Math.sin(delta * 1.15) * Math.min(distance, 2.5) * 14 + distance * 3;
  const amplitude = 5 + Math.min(distance, 2.5) * 1.35;
  const floating = (
    Math.sin(now * 0.00062 + cardIndex * 1.37 + track.phase) * amplitude
    + Math.sin(now * 0.00021 + cardIndex * 0.73 + track.phase) * 1.5
  );
  const scale = Math.max(0.56, 1 - distance * 0.145);
  const blur = Math.min(13, Math.max(0, distance - 0.12) * 3.15);
  const opacity = Math.max(0.12, 1 - distance * 0.185);

  return {
    "--discover-track-x": `${delta * spacing}px`,
    "--discover-track-y": `${arc + floating}px`,
    "--discover-track-scale": `${scale}`,
    "--discover-track-rotate": `${delta * -2.8}deg`,
    "--discover-track-blur": `${blur}px`,
    "--discover-track-opacity": `${opacity}`,
    "--discover-track-depth": `${Math.round((20 - Math.min(distance, 19)) * 10)}`,
  } as CSSProperties;
}

export function DiscoverOrbit({ items, interactive, onSelect }: DiscoverOrbitProps) {
  const reducedMotion = useReducedMotion();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef<Record<TrackId, Array<HTMLElement | null>>>({ upper: [], lower: [] });
  const targetRef = useRef(0);
  const currentRef = useRef(0);
  const activeIndexesRef = useRef<Record<TrackId, number>>({ upper: 0, lower: 0 });
  const pauseAutoUntilRef = useRef(0);
  const inertiaRef = useRef(0);
  const snapAtRef = useRef<number | null>(null);
  const dragRef = useRef<PointerDrag | null>(null);
  const didDragRef = useRef(false);
  const hoveringRef = useRef(false);
  const [activeIndexes, setActiveIndexes] = useState<Record<TrackId, number>>({ upper: 0, lower: 0 });
  const [isInteracting, setIsInteracting] = useState(false);
  const total = items.length;

  const pauseAuto = (duration = AUTO_RESUME_DELAY) => {
    pauseAutoUntilRef.current = performance.now() + duration;
  };

  const syncActiveIndexes = (current: number) => {
    const next = Object.fromEntries(TRACKS.map((track) => [
      track.id,
      nearestIndex(current, track.phase, track.direction, total),
    ])) as Record<TrackId, number>;
    if (next.upper === activeIndexesRef.current.upper && next.lower === activeIndexesRef.current.lower) return;
    activeIndexesRef.current = next;
    setActiveIndexes(next);
  };

  const moveTo = (nextTarget: number, pauseDuration = AUTO_RESUME_DELAY) => {
    targetRef.current = nextTarget;
    inertiaRef.current = 0;
    snapAtRef.current = performance.now() + 160;
    pauseAuto(pauseDuration);
    syncActiveIndexes(targetRef.current);
  };

  const spacingFor = () => {
    const width = rootRef.current?.clientWidth ?? 1200;
    return Math.min(Math.max(width * 0.205, 225), 330);
  };

  const syncCards = (now: number) => {
    const spacing = spacingFor();
    TRACKS.forEach((track) => {
      cardRefs.current[track.id].forEach((card, index) => {
        if (!card) return;
        const delta = wrapDelta(index + track.direction * currentRef.current + track.phase, total);
        const styles = distanceStyle(delta, index, now, spacing, track);
        Object.entries(styles).forEach(([name, value]) => card.style.setProperty(name, String(value)));
      });
    });
  };

  useLayoutEffect(() => {
    syncActiveIndexes(currentRef.current);
    syncCards(performance.now());
    // Card references and geometry are mutable to keep the render loop outside React state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [total]);

  useEffect(() => {
    if (!interactive || reducedMotion || total < 2) {
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
        targetRef.current += inertiaRef.current * deltaTime;
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
        && now >= pauseAutoUntilRef.current
        && inertiaRef.current === 0
        && snapAtRef.current === null
      );
      if (canAutoMove) targetRef.current += AUTO_SPEED * deltaTime;

      const smoothing = 1 - Math.pow(1 - DAMPING, deltaTime * 60);
      currentRef.current += (targetRef.current - currentRef.current) * smoothing;
      syncCards(now);
      syncActiveIndexes(currentRef.current);
      frameId = requestAnimationFrame(render);
    };

    frameId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(frameId);
    // The loop owns the mutable motion model and intentionally avoids render-time state updates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactive, reducedMotion, total]);

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
      targetRef.current = drag.startTarget - deltaX / spacingFor();
      drag.velocity = (event.clientX - drag.lastX) / Math.max(8, now - drag.lastTime);
      drag.lastX = event.clientX;
      drag.lastTime = now;
      syncActiveIndexes(targetRef.current);
    };

    const finishDrag = (event: globalThis.PointerEvent, cancelled = false) => {
      const drag = dragRef.current;
      if (!drag || drag.pointerId !== event.pointerId) return;
      if (root.hasPointerCapture(event.pointerId)) root.releasePointerCapture(event.pointerId);
      dragRef.current = null;
      setIsInteracting(false);
      if (!cancelled && didDragRef.current) {
        inertiaRef.current = Math.min(Math.max((-drag.velocity / spacingFor()) * 1000, -4), 4);
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
    // Event listeners bind to a shared mutable motion model.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactive, reducedMotion]);

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (!interactive) return;
    if (event.key === "ArrowRight") {
      event.preventDefault();
      moveTo(Math.round(targetRef.current) + 1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      moveTo(Math.round(targetRef.current) - 1);
    }
  };

  const handleCardClick = (track: TrackConfig, index: number, event: MouseEvent<HTMLElement>) => {
    if (!interactive) return;
    if (didDragRef.current) {
      event.preventDefault();
      didDragRef.current = false;
      return;
    }
    const centeredIndex = activeIndexesRef.current[track.id];
    const settled = Math.abs(targetRef.current - currentRef.current) < 0.08;
    if (index === centeredIndex && settled) {
      onSelect?.();
      return;
    }
    moveTo(targetForCard(index, track, currentRef.current, total));
  };

  const handleCardFocus = (track: TrackConfig, index: number) => {
    if (!interactive) return;
    moveTo(targetForCard(index, track, currentRef.current, total));
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
      data-active-index={`upper:${activeIndexes.upper};lower:${activeIndexes.lower}`}
      data-paused={isInteracting}
      data-reveal-item
      style={{ "--home-reveal-delay": "170ms" } as CSSProperties}
    >
      {TRACKS.map((track) => (
        <div className={`discover-orbit__track discover-orbit__track--${track.id}`} data-discover-track={track.id} key={track.id}>
          {items.map((item, index) => {
            const isActive = activeIndexes[track.id] === index;
            const commonProps = {
              ref: (node: HTMLElement | null) => { cardRefs.current[track.id][index] = node; },
              className: `discover-orbit__card ${isActive ? "is-active" : ""}`,
              "data-index": index,
              "aria-current": isActive ? "true" as const : "false" as const,
            };

            return interactive ? (
              <button
                {...commonProps}
                key={`${track.id}-${item.title}`}
                type="button"
                aria-label={`${track.id} ${item.title}`}
                onClick={(event) => handleCardClick(track, index, event)}
                onFocus={() => handleCardFocus(track, index)}
                onKeyDown={handleKeyDown}
                onPointerEnter={() => setHovering(true)}
                onPointerLeave={() => setHovering(false)}
              >
                <DiscoverTrackCard item={item} />
              </button>
            ) : (
              <article {...commonProps} key={`${track.id}-${item.title}`} aria-label={item.title}>
                <DiscoverTrackCard item={item} />
              </article>
            );
          })}
        </div>
      ))}
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
