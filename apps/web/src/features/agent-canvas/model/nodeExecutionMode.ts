import type { CanvasNodeV2 } from "../../../types-v2.ts";

export function isSourceOnlyNode(node: Pick<CanvasNodeV2, "execution_mode">): boolean {
  return node.execution_mode === "source_only";
}

export function assertGenerativeNode(node: Pick<CanvasNodeV2, "execution_mode">): void {
  if (isSourceOnlyNode(node)) {
    throw new Error("Source-only nodes cannot create Provider tasks or variations.");
  }
}
