import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LocaleProvider, useLocale } from "../../../i18n/locale.tsx";
import type { ChatMessageV2 } from "../../../types-v2.ts";
import { NaturalMessage } from "./NaturalMessage.tsx";
import type { NaturalMessagePresentation } from "./naturalMessagePresentation.ts";

afterEach(() => {
  cleanup();
  window.localStorage.removeItem("adcraft.locale");
});

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
  it("adds Editing card guidance and switches existing readiness messages to Chinese", () => {
    function LanguageSwitch() {
      const { setLocale } = useLocale();
      return <button onClick={() => setLocale("zh-CN")}>中文</button>;
    }

    render(
      <LocaleProvider initialLocale="en-US">
        <LanguageSwitch />
        <NaturalMessage
          message={message("adcraft_video_agent", "The Editing node is ready with the Ready Videos and BGM.")}
          presentation={presentation(true)}
        />
      </LocaleProvider>,
    );

    const english = "The Editing node is ready with the Ready Videos and BGM. Click the Editing card to export the video or add the final video to the canvas.";
    expect(screen.getByText(english)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "中文" }));
    expect(screen.getByText("剪辑节点已就绪，视频和背景音乐已准备好。点击剪辑卡片，即可导出视频或将最终视频添加到画布。")).toBeTruthy();
    expect(screen.queryByText(english)).toBeNull();
  });

  it("leaves user-authored Editing readiness text unchanged in Chinese mode", () => {
    const text = "The Editing node is ready with the Ready Videos and BGM.";
    render(
      <LocaleProvider initialLocale="zh-CN">
        <NaturalMessage message={message("user", text)} presentation={presentation(false)} />
      </LocaleProvider>,
    );

    expect(screen.getByText(text)).toBeTruthy();
  });

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

  it("renders Agent messages with the Agent bubble presentation", () => {
    render(
      <NaturalMessage
        message={message("adcraft_video_agent", "Choose the total advertisement duration to continue.")}
        presentation={presentation(true)}
      />,
    );

    const article = document.querySelector(".agent-chat__message--agent");
    const body = article?.querySelector(".agent-chat__message-body");
    expect(article).toBeTruthy();
    expect(body?.classList.contains("agent-chat__message-body--agent-bubble")).toBe(true);
    expect(body?.textContent).toContain("Choose the total advertisement duration to continue.");
  });

  it("shows Agent identity only when the run projection requests it", () => {
    const agentMessage = message("adcraft_video_agent", "The direction is ready.");
    const { rerender } = render(
      <NaturalMessage message={agentMessage} presentation={presentation(true)} />,
    );
    expect(screen.getByRole("img", { name: "AdCraft" })).toBeTruthy();
    expect(screen.queryByText("AdCraft Video Agent")).toBeNull();

    rerender(<NaturalMessage message={agentMessage} presentation={presentation(false)} />);
    expect(screen.queryByRole("img", { name: "AdCraft" })).toBeNull();
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

  it.each(["user", "adcraft_video_agent"] as const)("shows complete long %s messages without collapse controls", (speaker) => {
    const text = Array.from({ length: 12 }, (_, index) => `Line ${index + 1}: unchanged content.`).join("\n");
    render(
      <NaturalMessage
        message={message(speaker, text)}
        presentation={presentation(true)}
      />,
    );

    const body = document.querySelector(".agent-chat__message-body")!;
    expect(body.textContent).toBe(text);
    expect(body.classList.contains("is-collapsed")).toBe(false);
    expect(screen.queryByRole("button", { name: /Show more|Show less/ })).toBeNull();
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
