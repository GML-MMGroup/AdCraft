import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CanvasNodeStatusV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import { AgentCanvasAudioPlayer } from "./AgentCanvasAudioPlayer.tsx";

function audioNode(status: CanvasNodeStatusV2, prompt: string | null = null): CanvasNodeV2 {
  return {
    node_id: "audio-node",
    workflow_id: "workflow-1",
    node_type: "audio",
    creative_role: "bgm",
    role_contract_version: "ad-media-role-v1",
    title: "Audio",
    status,
    summary_prompt: null,
    generation_prompt: prompt,
    structured_content: {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: status === "ready" ? "audio-asset" : null,
    position: { x: 100, y: 100 },
    revision: 1,
    error: null,
    variation_draft: null,
    created_at: "2026-08-04T00:00:00Z",
    updated_at: "2026-08-04T00:00:00Z",
  };
}

function audioAsset(): ProjectAssetSummaryV2 {
  return {
    asset_id: "audio-asset",
    project_id: "project-1",
    workflow_id: "workflow-1",
    media_type: "audio",
    source_type: "generated",
    display_name: "Generated BGM",
    mime_type: "audio/wav",
    status: "ready",
    size_bytes: 5_292_284,
    storage_key: null,
    preview_url: null,
    media_url: "/api/v2/assets/audio-asset/content",
    width: null,
    height: null,
    duration_seconds: 30,
    checksum: "audio-checksum",
    source_semantic_role: "bgm",
    source_node_id: "audio-node",
    source_execution_id: "execution-1",
    provider: "tianpuyue",
    model_id: "TemPolor-i3",
    prompt_provenance: {},
    quality_metadata: {},
    created_at: "2026-08-04T00:00:00Z",
  };
}

describe("AgentCanvasAudioPlayer", () => {
  beforeEach(() => {
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function play() {
      this.dispatchEvent(new Event("play"));
      return Promise.resolve();
    });
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function pause() {
      this.dispatchEvent(new Event("pause"));
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("keeps the empty player composition visible before generation", () => {
    const node = {
      ...audioNode("draft", "A calm ambient score"),
      prompt_preparation: {
        status: "ready",
        operation_id: "prompt-operation-1",
        attempt_no: 1,
        context_snapshot_id: "prompt-context-1",
        prompt_digest: "prompt-digest-1",
        error: null,
        updated_at: "2026-08-04T00:00:00Z",
      },
    } satisfies CanvasNodeV2;

    render(<AgentCanvasAudioPlayer node={node} status="draft" asset={null} />);

    expect(screen.getByText("No audio yet")).toBeTruthy();
    expect((screen.getByRole("slider", { name: "Seek audio" }) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Add audio to favorites" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Rewind audio 5 seconds" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Play audio" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Fast-forward audio 5 seconds" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("replaces the timeline with an announced waveform while generating", () => {
    render(<AgentCanvasAudioPlayer node={audioNode("working")} status="working" asset={null} />);

    expect(screen.getByText("Generating...")).toBeTruthy();
    expect(screen.getByRole("status", { name: "Generating audio waveform" })).toBeTruthy();
    expect(screen.queryByRole("slider", { name: "Seek audio" })).toBeNull();
    expect((screen.getByRole("button", { name: "Play audio" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("uses the prompt excerpt and real media duration without a hover title", () => {
    const prompt = "A neon cyberpunk soundtrack with pulsing bass, metallic percussion, and cinematic synths";
    const { container } = render(
      <AgentCanvasAudioPlayer node={audioNode("ready", prompt)} status="ready" asset={audioAsset()} />,
    );

    const title = container.querySelector(".agent-canvas-audio-player__title");
    expect(title?.textContent).not.toBe(prompt);
    expect(title?.textContent?.endsWith("...")).toBe(true);
    expect(title?.hasAttribute("title")).toBe(false);
    expect((screen.getByRole("slider", { name: "Seek audio" }) as HTMLInputElement).max).toBe("30");
    expect(container.querySelector("audio")?.getAttribute("src")).toBe("/api/v2/assets/audio-asset/content");
  });

  it("plays, pauses, seeks, skips, and toggles the local favorite state", () => {
    const { container } = render(
      <AgentCanvasAudioPlayer
        node={audioNode("ready", "Cyberpunk city BGM")}
        status="ready"
        asset={audioAsset()}
      />,
    );
    const audio = container.querySelector("audio") as HTMLAudioElement;

    fireEvent.click(screen.getByRole("button", { name: "Play audio" }));
    expect(screen.getByRole("button", { name: "Pause audio" })).toBeTruthy();

    fireEvent.change(screen.getByRole("slider", { name: "Seek audio" }), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Fast-forward audio 5 seconds" }));
    expect(audio.currentTime).toBe(15);
    fireEvent.click(screen.getByRole("button", { name: "Rewind audio 5 seconds" }));
    expect(audio.currentTime).toBe(10);

    const favorite = screen.getByRole("button", { name: "Add audio to favorites" });
    fireEvent.click(favorite);
    expect(screen.getByRole("button", { name: "Remove audio from favorites" }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Pause audio" }));
    expect(screen.getByRole("button", { name: "Play audio" })).toBeTruthy();
  });
});
