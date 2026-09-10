import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";

const MODEL_MENU_MAX_HEIGHT = 236;
const MODEL_MENU_WIDTH = 360;
const MODEL_MENU_GAP = 5;
const VIEWPORT_GUTTER = 12;
const MODEL_MENU_MIN_USABLE_HEIGHT = 48;

interface ModelMenuPosition {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
}
type Placement = "above" | "below";

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

function calculateModelMenuPosition(
  triggerRect: DOMRect,
  menuRect: DOMRect,
  previousPlacement: Placement | null,
): ModelMenuPosition & { placement: Placement } {
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const width = Math.min(
    MODEL_MENU_WIDTH,
    Math.max(0, viewportWidth - VIEWPORT_GUTTER * 2),
  );
  const available = {
    above: Math.max(0, triggerRect.top - MODEL_MENU_GAP - VIEWPORT_GUTTER),
    below: Math.max(0, viewportHeight - VIEWPORT_GUTTER - triggerRect.bottom - MODEL_MENU_GAP),
  };
  const measuredHeight = menuRect.height || MODEL_MENU_MAX_HEIGHT;
  const usableHeight = Math.min(measuredHeight, MODEL_MENU_MIN_USABLE_HEIGHT);
  const placement = previousPlacement && available[previousPlacement] >= usableHeight ? previousPlacement
    : measuredHeight <= available.below || available.below >= available.above ? "below" : "above";
  const maxHeight = Math.min(MODEL_MENU_MAX_HEIGHT, available[placement], Math.max(0, viewportHeight - VIEWPORT_GUTTER * 2));
  const menuHeight = Math.min(measuredHeight, maxHeight);
  const requestedTop = placement === "above"
    ? triggerRect.top - MODEL_MENU_GAP - menuHeight
    : triggerRect.bottom + MODEL_MENU_GAP;
  const top = clamp(
    requestedTop,
    VIEWPORT_GUTTER,
    viewportHeight - menuHeight - VIEWPORT_GUTTER,
  );
  const left = clamp(
    triggerRect.left,
    VIEWPORT_GUTTER,
    viewportWidth - width - VIEWPORT_GUTTER,
  );

  return { top, left, width, maxHeight, placement };
}

export function useWorkbenchMenu(disabled: boolean, itemCount: number) {
  const [open, setOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState<ModelMenuPosition | null>(null);
  const triggerRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const placementRef = useRef<Placement | null>(null);
  useEffect(() => {
    if (disabled) {
      setOpen(false);
    }
  }, [disabled]);

  useLayoutEffect(() => {
    if (!open) {
      placementRef.current = null;
      setMenuPosition(null);
      return;
    }

    let frame: number | null = null;
    const updatePosition = () => {
      const trigger = triggerRef.current;
      const menu = menuRef.current;
      if (!trigger || !menu) return;
      const { placement, ...next } = calculateModelMenuPosition(
        trigger.getBoundingClientRect(),
        menu.getBoundingClientRect(),
        placementRef.current,
      );
      placementRef.current = placement;
      setMenuPosition((current) => current && current.top === next.top && current.left === next.left
        && current.width === next.width && current.maxHeight === next.maxHeight ? current : next);
    };
    const schedulePositionUpdate = () => {
      if (frame !== null) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        frame = null;
        updatePosition();
      });
    };

    updatePosition();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(updatePosition) : null;
    if (triggerRef.current) observer?.observe(triggerRef.current);
    if (menuRef.current) observer?.observe(menuRef.current);
    window.addEventListener("resize", schedulePositionUpdate);
    window.addEventListener("scroll", schedulePositionUpdate, true);
    return () => {
      observer?.disconnect();
      if (frame !== null) window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", schedulePositionUpdate);
      window.removeEventListener("scroll", schedulePositionUpdate, true);
    };
  }, [open, itemCount]);

  useEffect(() => {
    if (!open) return;
    const closeFromOutside = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      const target = event.target;
      if (!(target instanceof Node) || !(triggerRef.current?.contains(target) || menuRef.current?.contains(target))) return;
      const options = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('button[role="option"]:not(:disabled)') ?? []);
      if (!options.length) return;
      event.preventDefault();
      const current = options.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1
        : event.key === "ArrowDown" ? (current + 1) % options.length
          : current <= 0 ? options.length - 1 : current - 1;
      options[next]?.focus();
    };
    document.addEventListener("pointerdown", closeFromOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeFromOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  // The portal must be measurable before its first layout effect, but never visible at guessed coordinates.
  const menuStyle: CSSProperties = {
    position: "fixed",
    ...(menuPosition ?? { top: 0, left: 0, width: `min(${MODEL_MENU_WIDTH}px, calc(100vw - ${VIEWPORT_GUTTER * 2}px))`, maxHeight: MODEL_MENU_MAX_HEIGHT }),
    visibility: menuPosition ? "visible" : "hidden",
  };
  return { open, setOpen, menuStyle, triggerRef, menuRef };
}
