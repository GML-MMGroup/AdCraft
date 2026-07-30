import { describe, expect, it } from "vitest";

import { V2ApiError } from "../../../api/v2Client.ts";
import { canvasAuthoringErrorMessage } from "./canvasErrorMessage.ts";

describe("canvasAuthoringErrorMessage", () => {
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
});
