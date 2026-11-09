import type { CanvasNodeV2 } from "../../../types-v2.ts";

function editableValues(node: CanvasNodeV2): unknown[] {
  return [
    node.node_type,
    node.creative_role,
    node.execution_mode,
    node.title,
    node.generation_prompt ?? null,
    node.model_selection_mode ?? "default",
    node.model_ref ?? null,
    node.parameters,
    node.structured_content,
  ];
}

export function nodeDraftExpectedRevision(base: CanvasNodeV2, current: CanvasNodeV2): number {
  if (base.node_id !== current.node_id || current.revision <= base.revision) return base.revision;
  // Runtime projections can advance while a user edits. Rebase only when all
  // editable values still match the draft's baseline; real edits stay fenced.
  return JSON.stringify(editableValues(base)) === JSON.stringify(editableValues(current))
    ? current.revision
    : base.revision;
}
