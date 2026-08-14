import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CanvasConnectionPolicyV2, CanvasNodeV2 } from "../../../types-v2.ts";
import { AgentCanvasConnectedNodeMenu } from "./AgentCanvasConnectedNodeMenu.tsx";

const policy: CanvasConnectionPolicyV2 = {
  policy_version: "agent_canvas_connection_policy_v1",
  target_node_types: {
    text: [],
    script: ["text"],
    image: ["text", "script", "image"],
    video: ["text", "script", "image", "video"],
    audio: ["text", "audio"],
    editing: ["video", "audio"],
  },
  input_roles: [
    {
      source_node_type: "image",
      target_node_type: "video",
      roles: ["image_reference"],
      default_role: "image_reference",
    },
    {
      source_node_type: "video",
      target_node_type: "editing",
      roles: ["video_reference"],
      default_role: "video_reference",
    },
  ],
  image_asset_targets: { video: ["image_reference"] },
  binding_kind_by_source_type: {
    text: "text_context",
    script: "text_context",
    image: "image_reference",
    video: "video_reference",
    audio: "audio_reference",
    editing: "video_reference",
  },
  model_validation: {},
};

const anchor: CanvasNodeV2 = {
  node_id: "image-1",
  workflow_id: "workflow-1",
  node_type: "image",
  creative_role: "general_image",
  role_contract_version: "ad-media-role-v1",
  title: "Image",
  status: "ready",
  summary_prompt: null,
  generation_prompt: null,
  structured_content: {},
  model_id: null,
  parameters: {},
  prompt_context_snapshot_id: null,
  output_asset_id: "asset-1",
  position: { x: 0, y: 0 },
  revision: 1,
  error: null,
  variation_draft: null,
  created_at: "2026-07-30T00:00:00Z",
  updated_at: "2026-07-30T00:00:00Z",
};

afterEach(() => cleanup());

describe("AgentCanvasConnectedNodeMenu", () => {
  it("lists only policy-compatible node types and returns the persisted role", () => {
    const onSelect = vi.fn();
    render(
      <AgentCanvasConnectedNodeMenu
        anchorNode={anchor}
        direction="downstream"
        point={{ x: 120, y: 160 }}
        policy={policy}
        onSelect={onSelect}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("menuitem", { name: "Create connected Video node" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "Create connected Audio node" })).toBeNull();

    fireEvent.click(screen.getByRole("menuitem", { name: "Create connected Video node" }));
    expect(onSelect).toHaveBeenCalledWith("video", "image_reference");
  });

  it("explains when no compatible connection exists", () => {
    render(
      <AgentCanvasConnectedNodeMenu
        anchorNode={{ ...anchor, node_type: "editing", creative_role: "editing" }}
        direction="downstream"
        point={{ x: 120, y: 160 }}
        policy={policy}
        onSelect={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("No compatible downstream node types.")).toBeTruthy();
  });

  it("lets the user choose when the backend policy permits multiple input roles", () => {
    const onSelect = vi.fn();
    render(
      <AgentCanvasConnectedNodeMenu
        anchorNode={anchor}
        direction="downstream"
        point={{ x: 120, y: 160 }}
        policy={{
          ...policy,
          input_roles: [{
            source_node_type: "image",
            target_node_type: "video",
            roles: ["image_reference", "video_reference"],
            default_role: "image_reference",
          }],
        }}
        onSelect={onSelect}
        onClose={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Input role for Video"), {
      target: { value: "video_reference" },
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "Create connected Video node" }));

    expect(onSelect).toHaveBeenCalledWith("video", "video_reference");
  });

  it("offers Script when the backend policy permits a connected Script node", () => {
    const onSelect = vi.fn();
    render(
      <AgentCanvasConnectedNodeMenu
        anchorNode={{ ...anchor, node_type: "text", creative_role: "general_text" }}
        direction="downstream"
        point={{ x: 120, y: 160 }}
        policy={{
          ...policy,
          input_roles: [{
            source_node_type: "text",
            target_node_type: "script",
            roles: ["text_context"],
            default_role: "text_context",
          }],
        }}
        onSelect={onSelect}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("menuitem", { name: "Create connected Script node" }));

    expect(onSelect).toHaveBeenCalledWith("script", "text_context");
  });
});
