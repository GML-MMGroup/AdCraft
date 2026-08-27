import { useState } from "react";

import type { ChatMessageV2 } from "../../../types-v2.ts";
import {
  isLikelyMarkdown,
  renderMarkdownAwareText,
} from "../canvas/AgentCanvasMarkdown.tsx";
import type { NaturalMessagePresentation } from "./naturalMessagePresentation.ts";

export interface NaturalMessageProps {
  message: ChatMessageV2;
  presentation: NaturalMessagePresentation;
}

function isLongMessage(text: string): boolean {
  return text.length > 520 || text.split(/\r?\n/).length > 8;
}

function displayTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function NaturalMessage({ message, presentation }: NaturalMessageProps) {
  const [expanded, setExpanded] = useState(false);
  const long = isLongMessage(message.text);
  const isAgent = message.speaker === "adcraft_video_agent";

  return (
    <article
      className={[
        "agent-chat__message",
        `agent-chat__message--${isAgent ? "agent" : "user"}`,
        presentation.startsSpeakerRun ? "starts-speaker-run" : "continues-speaker-run",
      ].join(" ")}
      aria-label={isAgent ? "Agent message" : "Your message"}
    >
      {presentation.showAgentIdentity ? (
        <strong className="agent-chat__message-identity">AdCraft Video Agent</strong>
      ) : null}
      <div
        className={`agent-chat__message-body${long ? expanded ? " is-expanded" : " is-collapsed" : ""}`}
      >
        {isLikelyMarkdown(message.text)
          ? <div className="agent-chat__markdown">{renderMarkdownAwareText(message.text)}</div>
          : <p>{message.text}</p>}
      </div>
      <footer className="agent-chat__message-meta">
        {long ? (
          <button
            type="button"
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? "Show less" : "Show more"}
          </button>
        ) : null}
        <time dateTime={message.created_at} aria-label={`Sent ${message.created_at}`}>
          {displayTime(message.created_at)}
        </time>
      </footer>
    </article>
  );
}
