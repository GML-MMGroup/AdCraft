import { useEffect, useId, useRef, useState } from "react";

import { ChevronDownIcon, ChevronUpIcon } from "../../../icons.tsx";
import { useTranslation } from "../../../i18n/useTranslation";

export function AgentThinkingBlock({
  reasoningText,
  phase,
  durationSeconds,
}: {
  reasoningText: string;
  phase: "thinking" | "done";
  durationSeconds: number | null;
}) {
  const t = useTranslation();
  const bodyId = useId();
  const [expanded, setExpanded] = useState(phase === "thinking");
  const userToggledRef = useRef(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const followRef = useRef(true);

  useEffect(() => {
    if (phase === "done" && !userToggledRef.current) setExpanded(false);
  }, [phase]);

  useEffect(() => {
    const body = bodyRef.current;
    if (!body || phase !== "thinking" || !expanded || !followRef.current) return;
    body.scrollTop = body.scrollHeight;
  }, [expanded, phase, reasoningText]);

  function toggle() {
    userToggledRef.current = true;
    setExpanded((value) => !value);
  }

  const label = phase === "thinking"
    ? t("Thinking…")
    : durationSeconds !== null && Number.isFinite(durationSeconds)
      ? t("Thought for {n}s", { n: Math.max(0, Math.round(durationSeconds)) })
      : t("Thoughts");

  return (
    <section className={`agent-chat__thinking${expanded ? " is-expanded" : " is-collapsed"}`}>
      <button
        type="button"
        className="agent-chat__thinking-toggle"
        aria-expanded={expanded}
        aria-controls={bodyId}
        onClick={toggle}
      >
        {phase === "thinking" ? <span className="agent-chat__thinking-spinner" aria-hidden="true" /> : null}
        <span className="agent-chat__thinking-label">{label}</span>
        {expanded ? <ChevronUpIcon aria-hidden="true" /> : <ChevronDownIcon aria-hidden="true" />}
      </button>
      <div
        id={bodyId}
        ref={bodyRef}
        className="agent-chat__thinking-body"
        hidden={!expanded}
        onScroll={(event) => {
          const element = event.currentTarget;
          followRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 24;
        }}
      >
        {reasoningText}
      </div>
    </section>
  );
}
