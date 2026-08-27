import { describe, expect, it } from "vitest";

import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";
import { normalizeProviderParameters, runnableDraftParameterMigrations } from "./providerModels.ts";

describe("normalizeProviderParameters", () => {
  it("keeps the canonical integer duration and removes retired video keys", () => {
    expect(normalizeProviderParameters("video", {
      requested_duration_seconds: 20,
      effective_duration_seconds: 15,
    })).toEqual({
      parameters: { duration_seconds: 20 },
      migrated: true,
    });
  });

  it("does not infer provider compatibility from local binding data", () => {
    expect(normalizeProviderParameters("image", { duration_seconds: 20 })).toEqual({
      parameters: { duration_seconds: 20 },
      migrated: false,
    });
  });

  it("never migrates source-only Video parameters into Global Run", () => {
    const node = {
      node_id: "node-source-video",
      node_type: "video",
      status: "draft",
      execution_mode: "source_only",
      parameters: { requested_duration_seconds: 15 },
    } as CanvasNodeV2;
    const workflow = { nodes: [node] } as AgentCanvasWorkflowV2;

    expect(runnableDraftParameterMigrations(workflow)).toEqual([]);
  });
});
