import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ChatMessageV2 } from "../../../types-v2.ts";
import { NaturalMessage } from "./NaturalMessage.tsx";
import type { NaturalMessagePresentation } from "./naturalMessagePresentation.ts";

afterEach(cleanup);

function message(
  speaker: ChatMessageV2["speaker"],
  text: string,
): ChatMessageV2 {
  return {
    item_type: "message",
    message_kind: "conversation",
    message_id: "message-1",
    conversation_id: "conversation-1",
    speaker,
    text,
    linked_node_ids: [],
    script_node_id: null,
    proposal_id: null,
    capability_id: null,
    sequence: 1,
    created_at: "2026-08-27T05:00:00Z",
  };
}

function presentation(showAgentIdentity: boolean): NaturalMessagePresentation {
  return {
    messageId: "message-1",
    showAgentIdentity,
    startsSpeakerRun: showAgentIdentity,
  };
}

describe("NaturalMessage", () => {
  it("renders user messages as unlabeled bubbles", () => {
    render(<NaturalMessage message={message("user", "Create a quiet product film.")} presentation={presentation(false)} />);

    expect(screen.getByText("Create a quiet product film.")).toBeTruthy();
    expect(screen.queryByText("You")).toBeNull();
    expect(screen.queryByText("AdCraft Video Agent")).toBeNull();
    expect(document.querySelector(".agent-chat__message--user")).toBeTruthy();
  });

  it("shows a frontend-only Skill marker on the sent user message", () => {
    render(
      <NaturalMessage
        message={message("user", "Create a quiet product film.")}
        presentation={presentation(false)}
        skillTitle="Cinematic Poetic Realism"
      />,
    );

    expect(screen.getByText("Cinematic Poetic Realism")).toBeTruthy();
    const icon = document.querySelector<HTMLImageElement>(".agent-chat__message-skill img");
    expect(icon?.getAttribute("src")).toBe("/imgs/ui-icons/skill.svg");
    expect(icon?.getAttribute("alt")).toBe("");
  });

  it("does not attach a Skill marker to Agent messages", () => {
    render(
      <NaturalMessage
        message={message("adcraft_video_agent", "The direction is ready.")}
        presentation={presentation(true)}
        skillTitle="Cinematic Poetic Realism"
      />,
    );

    expect(screen.queryByText("Cinematic Poetic Realism")).toBeNull();
    expect(document.querySelector(".agent-chat__message-skill")).toBeNull();
  });

  it("shows Agent identity only when the run projection requests it", () => {
    const agentMessage = message("adcraft_video_agent", "The direction is ready.");
    const { rerender } = render(
      <NaturalMessage message={agentMessage} presentation={presentation(true)} />,
    );
    expect(screen.getByText("AdCraft Video Agent")).toBeTruthy();

    rerender(<NaturalMessage message={agentMessage} presentation={presentation(false)} />);
    expect(screen.queryByText("AdCraft Video Agent")).toBeNull();
  });

  it("uses the existing markdown renderer and blocks unsafe links", () => {
    render(
      <NaturalMessage
        message={message("adcraft_video_agent", [
          "## Direction",
          "- Keep the frame quiet",
          "> Product remains central",
          "Use `soft light` and [reference](javascript:alert(1)).",
          "```json",
          '{"status":"ready"}',
          "```",
        ].join("\n"))}
        presentation={presentation(true)}
      />,
    );

    expect(screen.getByRole("heading", { name: "Direction" })).toBeTruthy();
    expect(screen.getByRole("list")).toBeTruthy();
    expect(document.querySelector("blockquote")).toBeTruthy();
    expect(document.querySelector("code.language-json")?.textContent).toContain('"status":"ready"');
    expect(screen.getByRole("link", { name: "Unsafe link blocked" }).getAttribute("href")).toBe("#");
  });

  it("expands long content without rewriting it", () => {
    const text = Array.from({ length: 12 }, (_, index) => `Line ${index + 1}: unchanged content.`).join("\n");
    render(
      <NaturalMessage
        message={message("adcraft_video_agent", text)}
        presentation={presentation(true)}
      />,
    );

    const body = document.querySelector(".agent-chat__message-body")!;
    expect(body.classList.contains("is-collapsed")).toBe(true);
    expect(body.textContent).toBe(text);
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(body.classList.contains("is-expanded")).toBe(true);
    expect(body.textContent).toBe(text);
    fireEvent.click(screen.getByRole("button", { name: "Show less" }));
    expect(body.classList.contains("is-collapsed")).toBe(true);
  });

  it("keeps timestamps accessible and leaves semantic-looking text untouched", () => {
    render(
      <NaturalMessage
        message={message("adcraft_video_agent", "Summary: 结果： ordinary message text")}
        presentation={presentation(true)}
      />,
    );

    expect(screen.getByText("Summary: 结果： ordinary message text")).toBeTruthy();
    const time = document.querySelector("time")!;
    expect(time.getAttribute("dateTime")).toBe("2026-08-27T05:00:00Z");
    expect(time.getAttribute("aria-label")).toContain("Sent");
  });
});
