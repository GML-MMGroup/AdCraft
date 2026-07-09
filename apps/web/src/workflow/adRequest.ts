import type { AdRequest, UploadedAsset, WorkflowGraph, WorkflowNode } from "../types";

type ResolveWorkflowAdRequestOptions = {
  frontendAdRequest: AdRequest;
  defaultAdRequest: AdRequest;
  selectedAssets: UploadedAsset[];
  workflow?: WorkflowGraph | null;
  nodes: WorkflowNode[];
};

export function resolveWorkflowAdRequest({
  frontendAdRequest,
  defaultAdRequest,
  selectedAssets,
  workflow,
  nodes,
}: ResolveWorkflowAdRequestOptions): AdRequest {
  const backendAdRequest = workflowAdRequest(workflow);
  const frontendWasEdited = hasAdRequestEdits(frontendAdRequest, defaultAdRequest);
  const baseAdRequest = backendAdRequest && !frontendWasEdited ? { ...defaultAdRequest, ...backendAdRequest } : frontendAdRequest;
  const requirementsNode = nodes.find((node) => getWorkflowNodeType(node) === "requirements-analysis" || node.id === "requirements-analysis");
  const requirementsPrompt = requirementsNode ? getNodePrompt(requirementsNode) : "";
  const workflowName = workflow?.name?.replace(/\s*workflow\s*$/i, "").trim();
  const productName =
    baseAdRequest.product_name && baseAdRequest.product_name !== defaultAdRequest.product_name
      ? baseAdRequest.product_name
      : workflowName || baseAdRequest.product_name || "Ad product";
  const productDescription =
    baseAdRequest.product_description && baseAdRequest.product_description !== defaultAdRequest.product_description
      ? baseAdRequest.product_description
      : workflow?.description || requirementsPrompt || baseAdRequest.product_description || "Advertising brief";
  const targetAudience =
    baseAdRequest.target_audience && baseAdRequest.target_audience !== defaultAdRequest.target_audience
      ? baseAdRequest.target_audience
      : baseAdRequest.target_audience || "General audience";

  return {
    ...baseAdRequest,
    product_name: productName,
    product_description: productDescription,
    target_audience: targetAudience,
    selected_assets: selectedAssets,
  };
}

export function workflowAdRequest(workflow?: WorkflowGraph | null): Partial<AdRequest> | null {
  if (!workflow) return null;
  if (isRecord(workflow.ad_request)) return workflow.ad_request as Partial<AdRequest>;
  if (isRecord(workflow.metadata?.ad_request)) return workflow.metadata.ad_request as Partial<AdRequest>;
  return null;
}

export function hasAdRequestEdits(current: Partial<AdRequest>, defaults: Partial<AdRequest>) {
  const keys = new Set([...Object.keys(current), ...Object.keys(defaults)].filter((key) => key !== "selected_assets"));
  for (const key of keys) {
    if (!stableEqual((current as Record<string, unknown>)[key], (defaults as Record<string, unknown>)[key])) return true;
  }
  return false;
}

function getWorkflowNodeType(node: WorkflowNode) {
  return node.node_type ?? node.type ?? node.id;
}

function getNodePrompt(node: WorkflowNode) {
  return node.override_prompt ?? node.prompt ?? "";
}

function stableEqual(left: unknown, right: unknown) {
  return JSON.stringify(left ?? null) === JSON.stringify(right ?? null);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
