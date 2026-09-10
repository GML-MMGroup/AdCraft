import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client.ts";
import { providerRegistryErrorMessage } from "./providerRegistryMessages.ts";

describe("providerRegistryErrorMessage", () => {
  it.each(["provider_base_url_invalid", "credential_endpoint_invalid"])(
    "maps %s to the approved Base URL guidance",
    (code) => {
      const error = new ApiError("Request failed", 422, {
        detail: { code, message: "unsafe raw endpoint detail" },
      });

      expect(providerRegistryErrorMessage(error, "save")).toBe(
        "Enter an approved HTTPS Base URL for this provider capability.",
      );
    },
  );

  it("explains that a stale gateway projection requires model synchronization", () => {
    const error = new ApiError("Request failed", 409, {
      detail: { code: "provider_gateway_config_stale", message: "stale digest" },
    });

    expect(providerRegistryErrorMessage(error, "sync")).toBe(
      "Provider gateway configuration is out of date. Synchronize models before retrying.",
    );
  });

  it.each([
    "model_not_found",
    "model_unavailable",
    "model_capability_mismatch",
    "model_default_mode_invalid",
    "model_automatic_policy_unsupported",
    "model_conformance_required",
    "provider_model_retired",
    "retired_model_default_conflict",
  ])("preserves the backend message for %s", (code) => {
    const error = new ApiError("Request failed", 422, {
      detail: { code, message: `Bounded backend message for ${code}` },
    });

    expect(providerRegistryErrorMessage(error, "defaults")).toBe(`Bounded backend message for ${code}`);
  });

  it.each([
    ["provider_credentials_missing", "Configure the provider credential before using this model."],
    ["provider_credential_rejected", "The provider rejected this credential."],
  ])("maps %s to bounded credential guidance", (code, expected) => {
    const error = new ApiError("Request failed", 422, { detail: { code } });

    expect(providerRegistryErrorMessage(error, "defaults")).toBe(expected);
  });
});
