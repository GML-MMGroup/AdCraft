import type { CanvasNodeV2 } from "../../../types-v2.ts";
import { projectCharacterNodePresentation } from "./characterNodePresentation.ts";

export type CanvasNodeIdentitySource = Partial<Pick<CanvasNodeV2,
  "workflow_id" | "creative_role" | "metadata" | "structured_content" | "prompt_preparation"
>>;

export interface CanvasNodeIdentity {
  family: "character" | "storyboard";
  scope: string;
  key: string;
  number: number;
}

function positiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : null;
}

function nonemptyString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/** Shared by labels and layout; never infer creative order from positions or opaque node IDs. */
export function canvasNodeIdentity(node: CanvasNodeIdentitySource): CanvasNodeIdentity | null {
  const metadata = node.metadata ?? {};
  if (node.creative_role === "character") {
    const character = projectCharacterNodePresentation({
      creative_role: node.creative_role,
      metadata,
      structured_content: node.structured_content ?? {},
      prompt_preparation: node.prompt_preparation ?? null,
    });
    const key = character?.occurrenceId ?? "";
    // Only the backend's monotonic character-N allocator supplies a stable number.
    const suffix = /^character-([1-9]\d*)$/.exec(key)?.[1];
    const number = suffix ? positiveInteger(Number(suffix)) : null;
    return number === null ? null : {
      family: "character", scope: node.workflow_id ?? "", key, number,
    };
  }
  if (node.creative_role === "storyboard_sequence" || node.creative_role === "storyboard_video") {
    const number = positiveInteger(metadata.sequence_index);
    return number === null ? null : {
      family: "storyboard",
      scope: JSON.stringify([node.workflow_id ?? "", nonemptyString(metadata.source_agent_document_id)]),
      key: JSON.stringify([nonemptyString(metadata.source_sequence_id), number]),
      number,
    };
  }
  return null;
}
