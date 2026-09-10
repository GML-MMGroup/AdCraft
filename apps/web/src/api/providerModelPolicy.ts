import type { ProviderModelSummaryV1 } from "./providerRegistry.ts";

export const RETIRED_ARK_MINI_MODEL_REF = "volcengine_ark:doubao-seed-2-0-mini-260428";
export const RETIRED_OPENAI_IMAGE_MODEL_REF = "openai:gpt-image-2";

export type ModelEligibilityContext = "default" | "diagnostic";

export interface ModelEligibility {
  visible: boolean;
  selectable: boolean;
  reason: string | null;
}

function unavailableReason(model: ProviderModelSummaryV1): string {
  if (model.unavailable_reason) {
    switch (model.unavailable_reason) {
      case "provider_credentials_missing": return "Provider credentials are not configured.";
      case "provider_credential_rejected": return "The provider rejected its configured credential.";
      case "provider_model_retired": return "This provider model has been retired.";
      case "model_conformance_required": return "Model conformance verification is required.";
      default: return model.unavailable_reason;
    }
  }
  switch (model.availability) {
    case "unavailable": return "Model is currently unavailable.";
    case "unauthorized": return "Provider credentials do not authorize this model.";
    case "unsupported": return "This model is not supported by the current adapter.";
    case "deprecated": return "This model has been deprecated.";
    default: return "Model is not executable.";
  }
}

function conformanceReason(model: ProviderModelSummaryV1): string | null {
  switch (model.conformance_status) {
    case "unverified": return "Model conformance has not been verified.";
    case "revoked": return "Model conformance has been revoked.";
    case "compatible":
    case "certified": return null;
    default: return "Model conformance status is unavailable.";
  }
}

export function modelEligibility(
  model: ProviderModelSummaryV1,
  context: ModelEligibilityContext,
): ModelEligibility {
  const isAuditOnly = model.provider_id === "fake"
    || model.transport_kind === "fake"
    || model.availability === "deprecated"
    || model.model_ref === RETIRED_ARK_MINI_MODEL_REF
    || model.model_ref === RETIRED_OPENAI_IMAGE_MODEL_REF;
  if (isAuditOnly) {
    return { visible: false, selectable: false, reason: unavailableReason(model) };
  }

  let reason: string | null = null;
  if (model.availability !== "available") {
    reason = unavailableReason(model);
  } else if (model.adapter_id || model.transport_kind) {
    reason = conformanceReason(model);
  }

  const selectable = reason === null;
  return {
    visible: selectable || context === "diagnostic",
    selectable,
    reason,
  };
}

export function selectableModelOptions(
  models: readonly ProviderModelSummaryV1[],
): ProviderModelSummaryV1[] {
  return models.filter((model) => modelEligibility(model, "default").selectable);
}
