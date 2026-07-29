import { describe, expect, it, vi } from "vitest";

import type { CanvasNodeV2 } from "../../../types-v2.ts";
import type { ReadyMediaVariationDraft } from "./readyMediaVariation.ts";
import { createAndRunReadyMediaVariation } from "./readyMediaVariationOrchestration.ts";

const source = {
  node_id: "source-image",
  node_type: "image",
  status: "ready",
} as CanvasNodeV2;
const sibling = {
  node_id: "sibling-image",
  node_type: "image",
  status: "draft",
} as CanvasNodeV2;
const draft: ReadyMediaVariationDraft = {
  title: "Alternative",
  generationPrompt: "Alternative prompt",
  modelId: "image-model-v2",
  parameters: { aspect_ratio: "3:4" },
};

describe("Ready media variation orchestration", () => {
  it("creates first and runs only the canonical returned sibling", async () => {
    const order: string[] = [];
    const createSibling = vi.fn(async () => {
      order.push("create");
      return sibling;
    });
    const runSibling = vi.fn(async () => {
      order.push("run");
    });

    await createAndRunReadyMediaVariation({
      source,
      draft,
      createSibling,
      runSibling,
      onRunSubmissionError: vi.fn(),
    });

    expect(order).toEqual(["create", "run"]);
    expect(createSibling).toHaveBeenCalledWith(source, draft);
    expect(runSibling).toHaveBeenCalledWith(sibling, {
      sourceAction: "ready_media_variation_generate",
    });
  });

  it("does not run when sibling creation fails or returns no node", async () => {
    const runSibling = vi.fn();
    await expect(createAndRunReadyMediaVariation({
      source,
      draft,
      createSibling: vi.fn().mockRejectedValue(new Error("create failed")),
      runSibling,
      onRunSubmissionError: vi.fn(),
    })).rejects.toThrow("create failed");
    expect(runSibling).not.toHaveBeenCalled();

    await expect(createAndRunReadyMediaVariation({
      source,
      draft,
      createSibling: vi.fn().mockResolvedValue(null),
      runSibling,
      onRunSubmissionError: vi.fn(),
    })).rejects.toThrow("The variation node was not created.");
    expect(runSibling).not.toHaveBeenCalled();
  });

  it("reports a run submission failure without deleting the created sibling", async () => {
    const retainedNodes = [source, sibling];
    const failure = new Error("run unavailable");
    const onRunSubmissionError = vi.fn();

    await expect(createAndRunReadyMediaVariation({
      source,
      draft,
      createSibling: vi.fn().mockResolvedValue(sibling),
      runSibling: vi.fn().mockRejectedValue(failure),
      onRunSubmissionError,
    })).rejects.toThrow("run unavailable");

    expect(onRunSubmissionError).toHaveBeenCalledWith(failure);
    expect(retainedNodes).toEqual([source, sibling]);
  });
});
