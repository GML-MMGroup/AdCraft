import type { ReactNode } from "react";

import type { ChatMessageV2 } from "../../../types-v2.ts";
import {
  isLikelyMarkdown,
  renderMarkdownAwareText,
} from "../canvas/AgentCanvasMarkdown.tsx";
import type { NaturalMessagePresentation } from "./naturalMessagePresentation.ts";
import { AgentMessageAvatar } from "./AgentMessageAvatar.tsx";
import { useTypewriterText, type TypewriterPlayback } from "./useTypewriterText.ts";

export interface NaturalMessageProps {
  message: ChatMessageV2;
  presentation: NaturalMessagePresentation;
  related?: ReactNode;
  skillTitle?: string | null;
  animate?: boolean;
  playback?: TypewriterPlayback;
}

function displayTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function NaturalMessage({ message, presentation, related, skillTitle, animate = false, playback }: NaturalMessageProps) {
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
      {isAgent && presentation.showAgentIdentity ? <AgentMessageAvatar /> : null}
      <div
        className={[
          "agent-chat__message-body",
          isAgent ? "agent-chat__message-body--agent-bubble" : "",
        ].filter(Boolean).join(" ")}
      >
        {!isAgent && skillTitle ? (
          <div className="agent-chat__message-skill" aria-label={`Skill: ${skillTitle}`}>
            <img src="/imgs/ui-icons/skill.svg" alt="" aria-hidden="true" />
            <span>{skillTitle}</span>
          </div>
        ) : null}
        <MessageText text={message.text} animate={isAgent && animate} playback={playback} />
      </div>
      {related}
      <footer className="agent-chat__message-meta">
        <time dateTime={message.created_at} aria-label={`Sent ${message.created_at}`}>
          {displayTime(message.created_at)}
        </time>
      </footer>
    </article>
  );
}

// Keep animation frames inside the text subtree, away from the canvas and chat history.
function MessageText({ text, animate, playback }: {
  text: string;
  animate: boolean;
  playback?: TypewriterPlayback;
}) {
  const shown = useTypewriterText(text, { animate, playback });
  return (
    <div className="agent-chat__message-text" aria-busy={shown !== text} data-typing={shown !== text}>
      {isLikelyMarkdown(text)
        ? <div className="agent-chat__markdown">{renderMarkdownAwareText(shown)}</div>
        : <p>{shown}</p>}
    </div>
  );
}
