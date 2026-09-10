import { describe, expect, it } from "vitest";

import { V2ApiError } from "../../../api/v2Client.ts";
import { canvasAuthoringErrorMessage } from "./canvasErrorMessage.ts";

describe("canvasAuthoringErrorMessage", () => {
  it("explains a retryable World Setting projection failure", () => {
    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 409,
      code: "world_setting_projection_unavailable",
      message: "Projection service unavailable.",
      details: { retryable: true },
    }))).toBe("World Setting context is temporarily unavailable. Retry this node.");
  });

  it("turns cycle and capability failures into actionable canvas messages", () => {
    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 409,
      code: "canvas_binding_cycle",
      message: "Cycle",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }))).toContain("cycle");

    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 422,
      code: "binding_model_incompatible",
      message: "Unsupported",
      details: { compatible_model_ids: ["seedance-1.0", "seedance-lite"] },
      violations: [],
      suggestedActions: [],
      payload: null,
    }))).toContain("seedance-1.0");
  });

  it("preserves an unknown backend message", () => {
    expect(canvasAuthoringErrorMessage(new Error("Connection failed."))).toBe("Connection failed.");
  });

  it("maps model failures without exposing backend implementation details", () => {
    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 409,
      code: "provider_credentials_missing",
      message: "missing provider key",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }))).toBe("This model provider has no configured credential.");

    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 409,
      code: "model_unavailable",
      message: "unavailable",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }))).toBe("The selected model is currently unavailable.");
  });

  it("explains that incomplete prompt preparation blocks Run admission", () => {
    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 409,
      code: "node_prompt_preparation_incomplete",
      message: "Prompt preparation is incomplete.",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }))).toBe("Prompt preparation is still in progress. Try running this node again when it is ready.");
  });

  it.each([
    ["provider_gateway_config_stale", "Provider gateway configuration is out of date. Synchronize models before retrying."],
    ["provider_gateway_unavailable", "The configured provider gateway is unavailable."],
    ["model_adapter_unavailable", "The selected model has no executable adapter."],
    ["model_conformance_required", "The selected model has not completed compatibility verification."],
    ["model_conformance_revoked", "Compatibility approval for the selected model has been revoked."],
    ["model_parameter_incompatible", "One or more parameters are not supported by the selected model."],
    ["reference_input_mode_unsupported", "The selected model cannot use the current reference input mode."],
    ["reference_count_exceeded", "The current references exceed the selected model's limit."],
  ])("maps provider-neutral failure %s", (code, message) => {
    expect(canvasAuthoringErrorMessage(new V2ApiError({
      status: 422,
      code,
      message: "backend implementation detail",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }))).toBe(message);
  });
});
