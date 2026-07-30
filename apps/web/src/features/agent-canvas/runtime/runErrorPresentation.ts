import { isV2ApiError } from "../../../api/v2Client.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasNodeErrorV2,
} from "../../../types-v2.ts";

export type AgentCanvasRunErrorPresentation = {
  message: string;
  attentionNodeIds: string[];
};

export function presentAgentCanvasNodeError(error: CanvasNodeErrorV2): string {
  if (error.code === "storyboard_video_input_contract_invalid") {
    return "This storyboard video needs exactly one required Storyboard Grid and one required Scene Design Board.";
  }
  if (error.code === "upstream_inputs_not_ready") {
    return "Generate all required upstream inputs before running this node.";
  }
  if (error.code === "canvas_reference_limit_exceeded") {
    return "This node exceeds the selected model's reference limit.";
  }
  if (error.code === "provider_inputs_unsupported") {
    return "The selected provider model cannot use all connected inputs.";
  }
  if (error.code === "provider_reference_delivery_unavailable") {
    return "A required reference cannot be delivered to the selected provider.";
  }
  return error.message;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && Boolean(item))
    : [];
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function presentAgentCanvasRunError(
  error: unknown,
  workflow: AgentCanvasWorkflowV2 | null,
): AgentCanvasRunErrorPresentation {
  if (!isV2ApiError(error) || !error.code) {
    return {
      message: error instanceof Error ? error.message : "The run could not start.",
      attentionNodeIds: [],
    };
  }

  if (error.code === "upstream_inputs_not_ready") {
    const missingNodeIds = stringList(error.details.missing_node_ids);
    const nodes = new Map(workflow?.nodes.map((node) => [node.node_id, node.title]) ?? []);
    const labels = missingNodeIds.map((nodeId) => nodes.get(nodeId) ?? nodeId);
    return {
      message: labels.length
        ? `Generate the required inputs first: ${labels.join(", ")}.`
        : "Generate all required upstream inputs before running this node.",
      attentionNodeIds: missingNodeIds,
    };
  }

  if (error.code === "storyboard_video_input_contract_invalid") {
    return {
      message: "A storyboard video needs exactly one required Storyboard Grid and one required Scene Design Board.",
      attentionNodeIds: [],
    };
  }

  if (error.code === "canvas_reference_limit_exceeded") {
    const mediaType = stringValue(error.details.media_type) ?? "media";
    const count = numberValue(error.details.count);
    const limit = numberValue(error.details.limit);
    return {
      message: count !== null && limit !== null
        ? `This node has ${count} ${mediaType} references; the selected model supports ${limit}.`
        : `This node exceeds the selected model's ${mediaType} reference limit.`,
      attentionNodeIds: [],
    };
  }

  if (error.code === "provider_inputs_unsupported") {
    const compatibleModels = stringList(error.details.compatible_model_ids);
    return {
      message: compatibleModels.length
        ? `The current model cannot use these inputs. Choose a compatible model: ${compatibleModels.join(", ")}.`
        : "The current model cannot use all connected inputs. Choose a compatible configured model.",
      attentionNodeIds: [],
    };
  }

  if (error.code === "provider_reference_delivery_unavailable") {
    const assetId = stringValue(error.details.asset_id);
    const bindingId = stringValue(error.details.binding_id);
    const identifier = assetId ?? bindingId;
    return {
      message: identifier
        ? `The required reference ${identifier} cannot be delivered to the selected provider.`
        : "A required reference cannot be delivered to the selected provider.",
      attentionNodeIds: [],
    };
  }

  return {
    message: error.message,
    attentionNodeIds: [],
  };
}
