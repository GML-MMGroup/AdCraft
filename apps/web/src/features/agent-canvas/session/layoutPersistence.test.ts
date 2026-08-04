import { describe, expect, it, vi } from "vitest";

import { V2ApiError } from "../../../api/v2Client.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasLayoutPatchRequestV2,
} from "../../../types-v2.ts";
import { persistAgentCanvasLayout } from "./layoutPersistence.ts";

function workflow(layoutRevision: number, revision = 4): AgentCanvasWorkflowV2 {
  return {
    workflow_id: "workflow-1",
    project_id: "project-1",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision,
    layout_revision: layoutRevision,
    nodes: [],
    bindings: [],
    assets: [],
  };
}

describe("persistAgentCanvasLayout", () => {
  it("rebases only the intended positions after a layout revision conflict", async () => {
    let current = workflow(2, 5);
    const requests: CanvasLayoutPatchRequestV2[] = [];
    const patchLayout = vi.fn(async (request: CanvasLayoutPatchRequestV2) => {
      requests.push(request);
      if (requests.length === 1) {
        throw new V2ApiError({
          status: 409,
          code: "layout_revision_conflict",
          message: "Layout changed.",
          details: { current_layout_revision: 3 },
          violations: [],
          suggestedActions: [],
          payload: null,
        });
      }
      return {
        workflow_id: "workflow-1",
        revision: 6,
        layout_revision: 4,
        positions: request.positions,
      };
    });
    const loadWorkflow = vi.fn(async () => workflow(3, 6));
    const applyWorkflow = vi.fn((next: AgentCanvasWorkflowV2) => {
      current = next;
    });
    const applyLayout = vi.fn();

    await persistAgentCanvasLayout({
      workflowId: "workflow-1",
      positions: [{ node_id: "node-1", x: 640, y: 320 }],
      readWorkflow: () => current,
      loadWorkflow,
      patchLayout,
      applyWorkflow,
      applyLayout,
    });

    expect(requests).toEqual([
      {
        expected_layout_revision: 2,
        positions: [{ node_id: "node-1", x: 640, y: 320 }],
      },
      {
        expected_layout_revision: 3,
        positions: [{ node_id: "node-1", x: 640, y: 320 }],
      },
    ]);
    expect(loadWorkflow).toHaveBeenCalledOnce();
    expect(applyWorkflow).toHaveBeenCalledWith(expect.objectContaining({
      revision: 6,
      layout_revision: 3,
    }));
    expect(applyLayout).toHaveBeenCalledWith(expect.objectContaining({
      layout_revision: 4,
    }));
  });

  it("does not convert semantic conflicts into layout retries", async () => {
    const conflict = new V2ApiError({
      status: 412,
      code: "workflow_state_conflict",
      message: "Semantic state changed.",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    });

    await expect(persistAgentCanvasLayout({
      workflowId: "workflow-1",
      positions: [{ node_id: "node-1", x: 640, y: 320 }],
      readWorkflow: () => workflow(2),
      loadWorkflow: vi.fn(),
      patchLayout: vi.fn().mockRejectedValue(conflict),
      applyWorkflow: vi.fn(),
      applyLayout: vi.fn(),
    })).rejects.toBe(conflict);
  });

  it("does not send an old workflow layout after the active workflow changes", async () => {
    const patchLayout = vi.fn();
    await expect(persistAgentCanvasLayout({
      workflowId: "workflow-old",
      positions: [{ node_id: "node-old", x: 20, y: 30 }],
      readWorkflow: () => ({
        ...workflow(2),
        workflow_id: "workflow-new",
      }),
      loadWorkflow: vi.fn(),
      patchLayout,
      applyWorkflow: vi.fn(),
      applyLayout: vi.fn(),
    })).rejects.toThrow("active Agent Canvas workflow changed");
    expect(patchLayout).not.toHaveBeenCalled();
  });
});
