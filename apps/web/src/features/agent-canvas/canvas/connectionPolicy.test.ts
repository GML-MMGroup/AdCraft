import { describe, expect, it } from "vitest";

import type { CanvasConnectionPolicyV2 } from "../../../types-v2.ts";
import {
  MANUAL_BINDING_REQUIRED,
  compatibleConnectedNodeTypes,
  connectionRuleForPair,
} from "./connectionPolicy.ts";

const policy: CanvasConnectionPolicyV2 = {
  policy_version: "agent_canvas_connection_policy_v1",
  target_node_types: {
    text: ["text", "script"],
    script: ["text", "script"],
    image: ["text", "script", "image"],
    video: ["text", "script", "image", "video", "audio", "editing"],
    audio: ["text", "script"],
    editing: ["video", "audio", "editing"],
  },
  input_roles: [
    {
      source_node_type: "text",
      target_node_type: "image",
      roles: ["text_context"],
      default_role: "text_context",
    },
    {
      source_node_type: "image",
      target_node_type: "video",
      roles: ["image_reference"],
      default_role: "image_reference",
    },
    {
      source_node_type: "audio",
      target_node_type: "editing",
      roles: ["audio_reference"],
      default_role: "audio_reference",
    },
  ],
  image_asset_targets: {
    image: ["image_reference"],
    video: ["image_reference"],
  },
  binding_kind_by_source_type: {
    text: "text_context",
    script: "text_context",
    image: "image_reference",
    video: "video_reference",
    audio: "audio_reference",
    editing: "video_reference",
  },
  model_validation: {
    explicit_model: "authoring_and_run",
    automatic_model: "run",
  },
};

describe("Agent Canvas connection policy", () => {
  it("keeps user-created canvas connections optional by default", () => {
    expect(MANUAL_BINDING_REQUIRED).toBe(false);
  });

  it("derives downstream and upstream add-menu types from backend role rules", () => {
    expect(compatibleConnectedNodeTypes(policy, "text", "downstream")).toEqual(["image"]);
    expect(compatibleConnectedNodeTypes(policy, "editing", "upstream")).toEqual(["audio"]);
  });

  it("returns the backend default role for a compatible pair", () => {
    expect(connectionRuleForPair(policy, "image", "video")).toEqual({
      source_node_type: "image",
      target_node_type: "video",
      roles: ["image_reference"],
      default_role: "image_reference",
    });
    expect(connectionRuleForPair(policy, "video", "text")).toBeNull();
  });
});
