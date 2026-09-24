import { useLayoutEffect, useRef, useState, type ReactNode, type PointerEvent } from "react";

import { brandPanelMaxWidth } from "./brandPanelResize";

/** Owns sizing only; decision content and production state stay independent. */
export function ResizableBrandPanel({ children }: { children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  const session = useRef<{ pointer: number; x: number; width: number } | null>(null);
  const widthRef = useRef(300);
  const maxRef = useRef(520);
  const [width, setWidth] = useState(300);
  const [maxWidth, setMaxWidth] = useState(520);
  const [dragging, setDragging] = useState(false);

  function apply(value: number) {
    const next = Math.round(Math.max(260, Math.min(maxRef.current, value)));
    widthRef.current = next;
    setWidth(next);
    root.current?.parentElement?.style.setProperty("--brand-panel-width", `${next}px`);
  }

  useLayoutEffect(() => {
    const host = root.current?.parentElement;
    if (!host) return;
    const measure = () => {
      const chat = host.querySelector(".agent-chat");
      maxRef.current = brandPanelMaxWidth(host.getBoundingClientRect().width, chat?.getBoundingClientRect().width ?? 0);
      setMaxWidth(maxRef.current);
      apply(widthRef.current);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    let chat: Element | null = null;
    const observeChat = () => {
      const next = host.querySelector(".agent-chat");
      if (next !== chat) {
        if (chat) observer.unobserve(chat);
        chat = next;
        if (chat) observer.observe(chat);
        measure();
      }
    };
    const mutations = new MutationObserver(observeChat);
    mutations.observe(host, { childList: true });
    observeChat();
    measure();
    return () => {
      observer.disconnect();
      mutations.disconnect();
      host.style.removeProperty("--brand-panel-width");
    };
  }, []);

  function stop(event: PointerEvent<HTMLDivElement>) {
    if (session.current?.pointer !== event.pointerId) return;
    session.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  return <div ref={root} className={`brand-panel-shell${dragging ? " is-resizing" : ""}`}>
    {children}
    {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex -- WAI-ARIA window splitter: focusable separator with arrow-key sizing. */}
    <div className="brand-panel-resize" role="separator" tabIndex={0}
      aria-label="Resize brand decision panel" aria-orientation="vertical"
      aria-valuemin={260} aria-valuemax={maxWidth} aria-valuenow={width}
      onPointerDown={event => {
        if (event.button !== 0 || session.current) return;
        session.current = { pointer: event.pointerId, x: event.clientX, width: widthRef.current };
        event.currentTarget.setPointerCapture(event.pointerId);
        setDragging(true);
        event.preventDefault();
      }}
      onPointerMove={event => {
        const start = session.current;
        if (start?.pointer !== event.pointerId) return;
        apply(start.width + event.clientX - start.x);
        event.preventDefault();
      }}
      onPointerUp={stop} onPointerCancel={stop} onLostPointerCapture={stop}
      onKeyDown={event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        apply(event.key === "Home" ? 260 : event.key === "End" ? maxRef.current : widthRef.current + (event.key === "ArrowRight" ? 24 : -24));
        event.preventDefault();
      }}
    />
  </div>;
}
