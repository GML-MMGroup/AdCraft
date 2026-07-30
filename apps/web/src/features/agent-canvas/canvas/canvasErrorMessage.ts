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
