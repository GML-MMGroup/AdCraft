import { isV2ApiError } from "../../../api/agentCanvasApi.ts";

const FRIENDLY_ERRORS: Record<string, string> = {
  canvas_binding_cycle: "This connection would create a dependency cycle.",
  canvas_cycle_detected: "This connection would create a dependency cycle.",
  canvas_connection_cycle: "This connection would create a dependency cycle.",
  canvas_connection_not_allowed: "These node types cannot be connected.",
  canvas_connection_incompatible: "These node types cannot be connected.",
  canvas_connection_duplicate: "These nodes are already connected.",
  canvas_binding_role_invalid: "This input role is not valid for the selected nodes.",
  canvas_input_role_invalid: "This input role is not valid for the selected nodes.",
  canvas_reference_limit_exceeded: "This node has reached the provider's reference limit.",
  provider_inputs_unsupported: "The selected provider cannot use these inputs.",
  provider_reference_delivery_unavailable: "The provider cannot currently receive this reference.",
  upstream_inputs_not_ready: "Required upstream nodes must be Ready before this node can run.",
  world_setting_projection_unavailable: "World Setting context is temporarily unavailable. Retry this node.",
  model_not_configured: "No default model is configured for this node type.",
  model_default_not_configured: "No default model is configured for this node type.",
  model_not_found: "The selected model is no longer in the local catalog.",
  model_unavailable: "The selected model is currently unavailable.",
  model_capability_mismatch: "The selected model cannot run this node with its current inputs.",
  provider_credentials_missing: "This model provider has no configured credential.",
  provider_credentials_invalid: "This model provider credential is not valid.",
  agent_model_incompatible: "The Agent default cannot perform this action.",
  model_catalog_sync_failed: "The provider model catalog could not be synchronized.",
  model_selection_invalid: "Choose a valid model selection before running this node.",
};

export function canvasAuthoringErrorMessage(error: unknown): string {
  if (!isV2ApiError(error)) {
    return error instanceof Error ? error.message : "The canvas operation could not be completed.";
  }
  if (error.code === "binding_model_incompatible") {
    const models = Array.isArray(error.details.compatible_model_ids)
      ? error.details.compatible_model_ids.filter((value): value is string => typeof value === "string")
      : [];
    return models.length
      ? `The selected model cannot use this input. Choose ${models.join(", ")}.`
      : "The selected model cannot use this input. Choose a compatible model.";
  }
  return (error.code && FRIENDLY_ERRORS[error.code]) || error.message;
}
