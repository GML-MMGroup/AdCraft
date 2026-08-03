import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client.ts";
import { providerRegistryErrorMessage } from "./providerRegistryMessages.ts";

describe("providerRegistryErrorMessage", () => {
  it.each([
    "model_not_found",
    "model_unavailable",
    "model_capability_mismatch",
    "model_default_mode_invalid",
    "model_automatic_policy_unsupported",
  ])("preserves the backend message for %s", (code) => {
    const error = new ApiError("Request failed", 422, {
      detail: { code, message: `Bounded backend message for ${code}` },
    });

    expect(providerRegistryErrorMessage(error, "defaults")).toBe(`Bounded backend message for ${code}`);
  });
});
