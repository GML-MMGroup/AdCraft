export type ConnectionPortType = "prompt" | "text" | "image" | "video" | "audio" | "json" | "resource" | "data";

export interface ConnectionPort {
  id: string;
  label: string;
  dataType: ConnectionPortType;
  multiple?: boolean;
}

export interface ConnectionValidationNode {
  id: string;
  data: {
    inputPorts?: ConnectionPort[];
    outputPorts?: ConnectionPort[];
  };
}

export interface ConnectionValidationEdge {
  id?: string;
  source?: string | null;
  target?: string | null;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

export interface ConnectionValidationResult {
  ok: boolean;
  message: string;
}

export function arePortTypesCompatible(outputType: ConnectionPortType, inputType: ConnectionPortType) {
  if (outputType === inputType) return true;
  if (outputType === "prompt" && inputType === "text") return true;
  if (outputType === "text" && inputType === "prompt") return true;
  if (outputType === "resource" && ["image", "video", "audio", "text", "json"].includes(inputType)) return true;
  if (inputType === "resource" && ["image", "video", "audio", "text", "json"].includes(outputType)) return true;
  if (outputType === "data" || inputType === "data") return outputType === "resource" || inputType === "resource";
  return false;
}

export function validateConnection(
  connection: ConnectionValidationEdge,
  nodes: ConnectionValidationNode[],
  edges: ConnectionValidationEdge[],
): ConnectionValidationResult {
  if (!connection.source || !connection.target) return { ok: false, message: "Connection needs a source and target." };
  if (connection.source === connection.target) return { ok: false, message: "A node cannot connect to itself." };
  if (!nodes.some((node) => node.id === connection.source) || !nodes.some((node) => node.id === connection.target)) {
    return { ok: false, message: "Connection references a missing node." };
  }

  const sourceNode = nodes.find((node) => node.id === connection.source);
  const targetNode = nodes.find((node) => node.id === connection.target);
  const sourcePort = getPortById(sourceNode, "output", connection.sourceHandle);
  const targetPort = getPortById(targetNode, "input", connection.targetHandle);
  if (!sourcePort) return { ok: false, message: "Current node has no usable output port." };
  if (!targetPort) return { ok: false, message: "Target node has no usable input port." };
  if (!arePortTypesCompatible(sourcePort.dataType, targetPort.dataType)) {
    return { ok: false, message: `${sourcePort.dataType} output cannot connect to ${targetPort.dataType} input.` };
  }
  if (edges.some((edge) => edge.source === connection.source && edge.target === connection.target)) {
    return { ok: false, message: "This connection already exists." };
  }
  if (!targetPort.multiple && edges.some((edge) => edge.target === connection.target && (edge.targetHandle ?? "") === targetPort.id)) {
    return { ok: false, message: "This input already has an upstream node." };
  }
  if (wouldCreateCycle(connection.source, connection.target, edges)) {
    return { ok: false, message: "This connection would create a cycle." };
  }
  return { ok: true, message: "OK" };
}

export function validateCanvas(nodes: ConnectionValidationNode[], edges: ConnectionValidationEdge[]): ConnectionValidationResult {
  if (!nodes.length) return { ok: false, message: "Add at least one node before running." };
  for (const edge of edges) {
    const validation = validateConnection(
      {
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle ?? null,
        targetHandle: edge.targetHandle ?? null,
      },
      nodes,
      edges.filter((item) => item.id !== edge.id),
    );
    if (!validation.ok && validation.message !== "This input already has an upstream node.") return validation;
  }
  return { ok: true, message: "OK" };
}

function getPortById(node: ConnectionValidationNode | undefined, direction: "input" | "output", handleId: string | null | undefined) {
  const ports = direction === "input" ? node?.data.inputPorts : node?.data.outputPorts;
  return ports?.find((port) => port.id === handleId) ?? ports?.[0];
}

function wouldCreateCycle(source: string, target: string, edges: ConnectionValidationEdge[]) {
  const downstream = new Map<string, string[]>();
  for (const edge of edges) {
    if (!edge.source || !edge.target) continue;
    downstream.set(edge.source, [...(downstream.get(edge.source) ?? []), edge.target]);
  }
  downstream.set(source, [...(downstream.get(source) ?? []), target]);

  const visited = new Set<string>();
  const stack = [target];
  while (stack.length) {
    const node = stack.pop();
    if (!node) continue;
    if (node === source) return true;
    if (visited.has(node)) continue;
    visited.add(node);
    stack.push(...(downstream.get(node) ?? []));
  }
  return false;
}
