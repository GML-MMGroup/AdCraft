import type { CanvasNodeV2 } from "../../../types-v2.ts";
import type { ReadyMediaVariationDraft } from "./readyMediaVariation.ts";

type CreateSibling = (
  source: CanvasNodeV2,
  draft: ReadyMediaVariationDraft,
) => Promise<CanvasNodeV2 | null | undefined>;

type RunSibling = (
  sibling: CanvasNodeV2,
  options: { sourceAction: "ready_media_variation_generate" },
) => Promise<void>;

export async function createAndRunReadyMediaVariation({
  source,
  draft,
  createSibling,
  runSibling,
  onRunSubmissionError,
}: {
  source: CanvasNodeV2;
  draft: ReadyMediaVariationDraft;
  createSibling: CreateSibling;
  runSibling: RunSibling;
  onRunSubmissionError: (error: unknown) => void;
}): Promise<CanvasNodeV2> {
  const sibling = await createSibling(source, draft);
  if (!sibling) throw new Error("The variation node was not created.");

  try {
    await runSibling(sibling, {
      sourceAction: "ready_media_variation_generate",
    });
  } catch (error) {
    onRunSubmissionError(error);
    throw error;
  }

  return sibling;
}
