import { describe, expect, it, vi } from "vitest";

import { V2ApiError } from "../../../api/v2Client.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasLayoutPatchRequestV2,
  CanvasLayoutPositionV2,
} from "../../../types-v2.ts";
import { persistAgentCanvasLayoutPreview } from "./layoutPreviewPersistence.ts";
import { AgentCanvasLayoutQueue } from "./layoutQueue.ts";

function workflow(workflowId: string, layoutRevision: number): AgentCanvasWorkflowV2 {
  return {
    workflow_id: workflowId,
    project_id: `project-${workflowId}`,
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 4,
    layout_revision: layoutRevision,
    nodes: [],
    bindings: [],
    assets: [],
    active_style_skill: null,
  };
}

function positions(prefix: "target" | "original"): CanvasLayoutPositionV2[] {
  return Array.from({ length: 205 }, (_, index) => ({
    node_id: `node-${index}`,
    x: prefix === "target" ? 1_000 + index : index,
    y: prefix === "target" ? 2_000 + index : index * 2,
  }));
}

describe("persistAgentCanvasLayoutPreview", () => {
  it("does not interleave drag writes with a 205-node preview transaction", async () => {
    const events: string[] = [];
    const target = positions("target");
    const queue = new AgentCanvasLayoutQueue(async (batch) => {
      events.push(`drag:${batch.map(({ node_id }) => node_id).join(",")}`);
    });
    const patchLayout = vi.fn(async (workflowId: string, request: CanvasLayoutPatchRequestV2) => {
      events.push(`preview:${request.positions.length}`);
      return {
        workflow_id: workflowId,
        revision: 4,
        layout_revision: request.expected_layout_revision + 1,
        positions: request.positions,
      };
    });

    const priorDrag = queue.enqueue([{ node_id: "prior-drag", x: 10, y: 10 }]);
    const preview = queue.runExclusive(() => persistAgentCanvasLayoutPreview({
      workflow: workflow("workflow-a", 10),
      targetPositions: target,
      originalPositions: positions("original"),
      patchLayout,
      loadWorkflow: vi.fn(),
    }));
    const laterDrag = queue.enqueue([{ node_id: "later-drag", x: 20, y: 20 }]);

    await Promise.all([priorDrag, preview, laterDrag]);

    expect(events).toEqual([
      "drag:prior-drag",
      "preview:200",
      "preview:5",
      "drag:later-drag",
    ]);
  });

  it("compensates all original positions before exposing a later target-batch failure", async () => {
    const target = positions("target");
    const original = positions("original");
    const saveError = new Error("Target batch 2 failed");
    const calls: Array<{ workflowId: string; request: CanvasLayoutPatchRequestV2 }> = [];
    const patchLayout = vi.fn(async (workflowId: string, request: CanvasLayoutPatchRequestV2) => {
      calls.push({ workflowId, request });
      if (calls.length === 2) throw saveError;
      return {
        workflow_id: workflowId,
        revision: 4,
        layout_revision: request.expected_layout_revision + 1,
        positions: request.positions,
      };
    });

    await expect(persistAgentCanvasLayoutPreview({
      workflow: workflow("workflow-a", 10),
      targetPositions: target,
      originalPositions: original,
      patchLayout,
      loadWorkflow: vi.fn(),
    })).rejects.toBe(saveError);

    expect(calls).toEqual([
      { workflowId: "workflow-a", request: { expected_layout_revision: 10, positions: target.slice(0, 200) } },
      { workflowId: "workflow-a", request: { expected_layout_revision: 11, positions: target.slice(200) } },
      { workflowId: "workflow-a", request: { expected_layout_revision: 11, positions: original.slice(0, 200) } },
      { workflowId: "workflow-a", request: { expected_layout_revision: 12, positions: original.slice(200) } },
    ]);
  });

  it("keeps target and compensation patches scoped to the preview workflow after the UI switches", async () => {
    const target = positions("target");
    const original = positions("original");
    const workflowA = workflow("workflow-a", 20);
    const workflowB = workflow("workflow-b", 7);
    let activeWorkflow = workflowA;
    const untouchedWorkflowB = structuredClone(workflowB);
    const calls: Array<{ workflowId: string; request: CanvasLayoutPatchRequestV2 }> = [];

    const patchLayout = vi.fn(async (workflowId: string, request: CanvasLayoutPatchRequestV2) => {
      calls.push({ workflowId, request });
      if (calls.length === 2) {
        activeWorkflow = workflowB;
        throw new Error("Target batch 2 failed after navigation");
      }
      return {
        workflow_id: workflowId,
        revision: 4,
        layout_revision: request.expected_layout_revision + 1,
        positions: request.positions,
      };
    });

    await expect(persistAgentCanvasLayoutPreview({
      workflow: workflowA,
      targetPositions: target,
      originalPositions: original,
      patchLayout,
      loadWorkflow: vi.fn(),
      applyLayout: (response) => {
        if (activeWorkflow.workflow_id !== response.workflow_id) return;
        activeWorkflow = { ...activeWorkflow, layout_revision: response.layout_revision };
      },
    })).rejects.toThrow("Target batch 2 failed after navigation");

    expect(calls.map(({ workflowId }) => workflowId)).toEqual([
      "workflow-a",
      "workflow-a",
      "workflow-a",
      "workflow-a",
    ]);
    expect(activeWorkflow).toEqual(untouchedWorkflowB);
  });

  it("rebases the scoped transaction revision after a layout conflict", async () => {
    const target = positions("target").slice(0, 1);
    const conflict = new V2ApiError({
      status: 409,
      code: "layout_revision_conflict",
      message: "Layout changed.",
      details: { current_layout_revision: 13 },
      violations: [],
      suggestedActions: [],
      payload: null,
    });
    const requests: CanvasLayoutPatchRequestV2[] = [];
    const patchLayout = vi.fn(async (_workflowId: string, request: CanvasLayoutPatchRequestV2) => {
      requests.push(request);
      if (requests.length === 1) throw conflict;
      return {
        workflow_id: "workflow-a",
        revision: 5,
        layout_revision: request.expected_layout_revision + 1,
        positions: request.positions,
      };
    });

    await persistAgentCanvasLayoutPreview({
      workflow: workflow("workflow-a", 10),
      targetPositions: target,
      originalPositions: positions("original").slice(0, 1),
      patchLayout,
      loadWorkflow: vi.fn(async (workflowId: string) => workflow(workflowId, 13)),
    });

    expect(requests.map(({ expected_layout_revision }) => expected_layout_revision)).toEqual([10, 13]);
  });

  it("bounds the complete combined save and compensation error", async () => {
    const primary = new Error(`Primary layout save failed ${"p".repeat(500)}`);
    const compensation = new Error(`Compensation failed ${"x".repeat(400)}`);
    const patchLayout = vi.fn()
      .mockRejectedValueOnce(primary)
      .mockRejectedValueOnce(compensation);

    let thrown: unknown;
    try {
      await persistAgentCanvasLayoutPreview({
        workflow: workflow("workflow-a", 10),
        targetPositions: positions("target").slice(0, 1),
        originalPositions: positions("original").slice(0, 1),
        patchLayout,
        loadWorkflow: vi.fn(),
      });
    } catch (error) {
      thrown = error;
    }

    expect(thrown).toMatchObject({
      message: expect.stringMatching(/^Primary layout save failed/),
      cause: primary,
    });
    expect((thrown as Error).message.length).toBeLessThanOrEqual(260);
  });
});
