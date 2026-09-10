import { describe, expect, it } from "vitest";

import type { ProviderModelSummaryV1 } from "./providerRegistry.ts";
import { modelEligibility } from "./providerModelPolicy.ts";

function model(overrides: Partial<ProviderModelSummaryV1> = {}): ProviderModelSummaryV1 {
  return {
    model_ref: "volcengine_ark:doubao-seedance-1-5-pro",
    provider_id: "volcengine_ark",
    provider_model_id: "doubao-seedance-1-5-pro",
    display_name: "Seedance 1.5 Pro",
    capability: "video",
    capability_metadata: {},
    availability: "available",
    unavailable_reason: null,
    catalog_revision: 4,
    adapter_id: "ark-video-v1",
    transport_kind: "ark_video_native",
    release_tier: "default",
    conformance_status: "compatible",
    accepted_input_modes: ["text"],
    parameter_schema_id: "video-v1",
    parameter_descriptors: [],
    reference_policy: null,
    ...overrides,
  };
}

describe("modelEligibility", () => {
  it.each(["compatible", "certified"] as const)(
    "allows an available expanded model with %s conformance",
    (conformance_status) => {
      expect(modelEligibility(model({ conformance_status }), "diagnostic")).toEqual({
        visible: true,
        selectable: true,
        reason: null,
      });
    },
  );

  it("keeps an unverified expanded model visible but disabled in a diagnostic picker", () => {
    expect(modelEligibility(model({ conformance_status: "unverified" }), "diagnostic")).toEqual({
      visible: true,
      selectable: false,
      reason: "Model conformance has not been verified.",
    });
  });

  it("uses the bounded backend reason for an unavailable model", () => {
    expect(modelEligibility(model({
      availability: "unavailable",
      unavailable_reason: "Provider credentials are missing.",
    }), "diagnostic")).toEqual({
      visible: true,
      selectable: false,
      reason: "Provider credentials are missing.",
    });
  });

  it.each([
    ["provider_credentials_missing", "Provider credentials are not configured."],
    ["provider_credential_rejected", "The provider rejected its configured credential."],
    ["provider_model_retired", "This provider model has been retired."],
    ["model_conformance_required", "Model conformance verification is required."],
  ])("translates stable unavailable reason %s", (unavailable_reason, reason) => {
    expect(modelEligibility(model({
      availability: "unavailable",
      unavailable_reason,
    }), "diagnostic")).toEqual({
      visible: true,
      selectable: false,
      reason,
    });
  });

  it.each([
    { provider_id: "fake", transport_kind: "ark_video_native" as const },
    { provider_id: "volcengine_ark", transport_kind: "fake" as const },
    { availability: "deprecated" as const },
    { model_ref: "volcengine_ark:doubao-seed-2-0-mini-260428" },
    {
      model_ref: "openai:gpt-image-2",
      provider_id: "openai",
      availability: "available" as const,
      conformance_status: "certified" as const,
    },
  ])("hides production-ineligible audit model %#", (overrides) => {
    expect(modelEligibility(model(overrides), "diagnostic").visible).toBe(false);
  });

  it("allows the exact certified OpenRouter image model", () => {
    expect(modelEligibility(model({
      model_ref: "openrouter:openai/gpt-image-2",
      provider_id: "openrouter",
      provider_model_id: "openai/gpt-image-2",
      adapter_id: "openrouter-image-native-v1",
      transport_kind: "openrouter_images_native",
      conformance_status: "certified",
    }), "default")).toEqual({
      visible: true,
      selectable: true,
      reason: null,
    });
  });

  it("allows the exact compatible OpenRouter Agent and Text model", () => {
    expect(modelEligibility(model({
      model_ref: "openrouter:openai/gpt-5.6-sol",
      provider_id: "openrouter",
      provider_model_id: "openai/gpt-5.6-sol",
      capability: "text",
      adapter_id: "openrouter-pi-agent-v1",
      transport_kind: "pi_native_openai_compatible",
      conformance_status: "compatible",
    }), "default")).toEqual({
      visible: true,
      selectable: true,
      reason: null,
    });
  });

  it("trusts availability for a legacy executable row without adapter metadata", () => {
    expect(modelEligibility(model({
      adapter_id: null,
      transport_kind: null,
      release_tier: null,
      conformance_status: "unverified",
    }), "default")).toEqual({
      visible: true,
      selectable: true,
      reason: null,
    });
  });

  it("omits diagnostic-only models from installation defaults", () => {
    expect(modelEligibility(model({ conformance_status: "revoked" }), "default")).toEqual({
      visible: false,
      selectable: false,
      reason: "Model conformance has been revoked.",
    });
  });
});
