import type { AgentCanvasWorkflowV2, ProviderResolvedMediaInputAuditV2 } from "../../../types-v2.ts";

export const REFERENCE_IMAGE_REJECTION_MESSAGE = "The provider flagged a reference image as possibly containing a real person. The provider may be mistaken; you can retry a few times.";
export const REFERENCE_IMAGE_REJECTION_LABEL = "Reference image flagged by the provider as possibly containing a real person";

export function referenceImageRejection(message: string): { contentIndex: number | null } | null {
  // Never classify text from the user's submitted prompt as a provider error.
  const detail = message.split(/\r?\npayload=/, 1)[0] ?? "";
  const responseBody = detail.match(/^response_body=(.+)$/m)?.[1];
  if (!responseBody) return null;
  try {
    const error = (JSON.parse(responseBody) as {
      error?: { code?: unknown; message?: unknown; param?: unknown };
    }).error;
    if (typeof error?.code !== "string" || !error.code.endsWith(".PrivacyInformation")
      || typeof error.message !== "string" || !/input image.*may contain real person/i.test(error.message)) return null;
    const param = typeof error.param === "string" ? error.param : "";
    const index = /^content\[(\d+)\]$/.exec(param)?.[1]
      ?? /input image\s+['"]?content\[(\d+)\]/i.exec(error.message)?.[1];
    // Seedance sends one text item, followed by the resolved media inputs.
    // Other providers need their own request-order mapping before highlighting.
    const contentIndex = /^provider=volcengine\s*$/m.test(detail) && index !== undefined
      && Number.isSafeInteger(Number(index)) ? Number(index) : null;
    return { contentIndex };
  } catch {
    return null;
  }
}

export function rejectedReferenceBindingId(
  workflow: AgentCanvasWorkflowV2,
  nodeId: string,
  input: ProviderResolvedMediaInputAuditV2 | undefined,
): string | null {
  if (!input || input.media_type !== "image") return null;
  const binding = workflow.bindings.find((item) => item.binding_id === input.binding_id
    && item.target_node_id === nodeId && item.enabled);
  if (!binding) return null;
  const source = binding.source;
  const assetId = source.kind === "image_asset" ? source.source_asset_id
    : workflow.nodes.find((item) => item.node_id === source.source_node_id)?.output_asset_id;
  if (assetId !== input.asset_id) return null;
  const asset = workflow.assets.find((item) => item.asset_id === assetId);
  if (!asset || asset.media_type !== "image") return null;
  if (source.kind === "image_asset" && source.source_asset_version_id) {
    if (input.asset_version_id) {
      return source.source_asset_version_id === input.asset_version_id ? binding.binding_id : null;
    }
    if (source.source_asset_version_id !== asset.version_id) return null;
  }
  // Asset IDs can survive regeneration, so also compare immutable content identity.
  if (input.checksum && input.checksum !== asset.checksum) return null;
  if (input.asset_version_id && input.asset_version_id !== asset.version_id) return null;
  return binding.binding_id;
}
