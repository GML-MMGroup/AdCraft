import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { Ajv2020 } from "ajv/dist/2020.js";
import { describe, expect, it } from "vitest";

const schema = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../src/generated/agent-runtime.schema.json", import.meta.url)),
    "utf8",
  ),
);
const ajv = new Ajv2020({ allErrors: true, strict: false });
ajv.addSchema(schema);
const contract = (name: string) =>
  ajv.compile({ $ref: `${schema.$id}#/$defs/${name}` });

describe("Video parameter compilation contracts", () => {
  it("accepts explicit controls extracted from an English node prompt", () => {
    const validateContext = contract("VideoParameterIntentContextV2");
    const validateIntent = contract("VideoParameterIntentV2");

    expect(
      validateContext({
        context_kind: "video_parameter_intent",
        workflow_id: "workflow_one",
        target_node_id: "video_one",
        target_node_revision: 3,
        selected_model_ref: "ark/seedance-fast",
        sources: [
          {
            source_kind: "node_prompt",
            source_node_id: "video_one",
            source_revision: 3,
            text: "Create a 15-second 1080p video.",
          },
        ],
        capability: {
          supported_parameters: ["duration_seconds", "resolution"],
          duration_seconds_min: 2,
          duration_seconds_max: 15,
          supported_resolutions: ["720p", "1080p"],
          supported_aspect_ratios: ["16:9"],
          supports_native_audio: false,
          default_parameters: { duration_seconds: 5 },
          capability_revision: 1,
        },
      }),
    ).toBe(true);
    expect(
      validateIntent({
        status: "explicit_controls",
        candidates: [
          {
            field: "duration_seconds",
            value: 15,
            source_kind: "node_prompt",
          },
          {
            field: "resolution",
            value: "1080p",
            source_kind: "node_prompt",
          },
        ],
      }),
    ).toBe(true);
  });

  it("accepts raw multilingual direct text without translating source identity", () => {
    const validate = contract("VideoParameterIntentContextV2");

    expect(
      validate({
        context_kind: "video_parameter_intent",
        workflow_id: "workflow_one",
        target_node_id: "video_one",
        target_node_revision: 3,
        selected_model_ref: "ark/seedance-fast",
        sources: [
          {
            source_kind: "binding",
            source_node_id: "text_one",
            source_revision: 2,
            binding_id: "binding_one",
            text: "请生成十五秒视频，分辨率 1080p。",
          },
        ],
        capability: {
          supported_parameters: ["duration_seconds", "resolution"],
          duration_seconds_min: 2,
          duration_seconds_max: 15,
          supported_resolutions: ["720p", "1080p"],
          supported_aspect_ratios: ["16:9"],
          supports_native_audio: false,
          default_parameters: { duration_seconds: 5 },
          capability_revision: 1,
        },
      }),
    ).toBe(true);
  });

  it("accepts no-explicit-controls and rejects spoofed Binding identity", () => {
    const validateIntent = contract("VideoParameterIntentV2");

    expect(
      validateIntent({ status: "no_explicit_controls", candidates: [] }),
    ).toBe(true);
    expect(
      validateIntent({
        status: "explicit_controls",
        candidates: [
          {
            field: "duration_seconds",
            value: 15,
            source_kind: "binding",
          },
        ],
      }),
    ).toBe(false);
  });
});
