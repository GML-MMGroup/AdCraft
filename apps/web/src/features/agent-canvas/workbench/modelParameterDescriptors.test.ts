import { describe, expect, it } from "vitest";

import type { ModelParameterDescriptorV1 } from "../../../api/providerRegistry.ts";
import { validateModelParameters } from "./modelParameterDescriptors.ts";

function descriptor(overrides: Partial<ModelParameterDescriptorV1>): ModelParameterDescriptorV1 {
  return {
    name: "duration_seconds",
    value_type: "integer",
    required: false,
    allowed_values: [],
    minimum: null,
    maximum: null,
    default: null,
    ...overrides,
  };
}

describe("validateModelParameters", () => {
  it("accepts declared enum, boolean, integer, number, and string values", () => {
    const descriptors = [
      descriptor({ name: "resolution", value_type: "enum", allowed_values: ["720p", "1080p"] }),
      descriptor({ name: "audio", value_type: "boolean" }),
      descriptor({ name: "duration_seconds", value_type: "integer", minimum: 1, maximum: 30 }),
      descriptor({ name: "guidance", value_type: "number", minimum: 0, maximum: 1 }),
      descriptor({ name: "mode", value_type: "string" }),
    ];

    expect(validateModelParameters(descriptors, {
      resolution: "1080p",
      audio: true,
      duration_seconds: 30,
      guidance: 0.5,
      mode: "cinematic",
    })).toEqual([]);
  });

  it("reports required, type, enum, bound, and unsupported-value issues without changing values", () => {
    const parameters = {
      resolution: "4k",
      audio: "yes",
      duration_seconds: 30.5,
      guidance: 2,
      legacy_option: "preserve-me",
    };
    const descriptors = [
      descriptor({ name: "resolution", value_type: "enum", allowed_values: ["720p", "1080p"] }),
      descriptor({ name: "audio", value_type: "boolean" }),
      descriptor({ name: "duration_seconds", value_type: "integer", maximum: 30 }),
      descriptor({ name: "guidance", value_type: "number", maximum: 1 }),
      descriptor({ name: "mode", value_type: "string", required: true }),
    ];

    const issues = validateModelParameters(descriptors, parameters);

    expect(issues.map((issue) => issue.name)).toEqual([
      "resolution",
      "audio",
      "duration_seconds",
      "guidance",
      "mode",
    ]);
    expect(parameters).toEqual({
      resolution: "4k",
      audio: "yes",
      duration_seconds: 30.5,
      guidance: 2,
      legacy_option: "preserve-me",
    });
  });

  it("does not materialize descriptor defaults for omitted values", () => {
    expect(validateModelParameters([
      descriptor({ default: 30 }),
    ], {})).toEqual([]);
  });

  it("preserves workflow metadata outside the provider descriptor namespace", () => {
    expect(validateModelParameters([
      descriptor({ name: "duration_seconds", minimum: 1, maximum: 15 }),
    ], {
      duration_seconds: 5,
      source_option_id: "option-1",
      stage_draft_key: "video-main",
    })).toEqual([]);
  });
});
