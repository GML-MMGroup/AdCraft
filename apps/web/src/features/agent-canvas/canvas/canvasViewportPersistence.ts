export function shouldPersistAgentCanvasViewport({
  focusedNodeId,
  layoutPreviewActive,
}: {
  focusedNodeId: string | null;
  layoutPreviewActive: boolean;
}): boolean {
  return !focusedNodeId && !layoutPreviewActive;
}
