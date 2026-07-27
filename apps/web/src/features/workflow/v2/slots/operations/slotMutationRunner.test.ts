import { describe, expect, it, vi } from "vitest";

import { normalizeWorkflowV2 } from "../../../../../api/v2Normalizers.ts";
import { createSlotMutationRunner } from "./slotMutationRunner.ts";

function workflow(stateVersion: number) {
  return normalizeWorkflowV2({
    workflow_id: "workflow-1",
    workflow_schema_version: 2,
    state_version: stateVersion,
    nodes: [],
    edges: [],
    items: [],
    slots: [],
    asset_versions: [],
  });
}

function createRunner(options: {
  activeWorkflowId?: string | null;
  currentRevision?: boolean;
  workflowEpoch?: number;
} = {}) {
  const order: string[] = [];
  const latest = workflow(3);
  const deps = {
    getWorkflowId: () => "workflow-1",
    currentWorkflowIsV2: () => true,
    getActiveWorkflowId: () => options.activeWorkflowId === undefined ? "workflow-1" : options.activeWorkflowId,
    getWorkflowEpoch: () => options.workflowEpoch ?? 1,
    captureRevision: (workflowId: string) => ({ workflowId, revision: 1 }),
    isCurrentRevision: () => options.currentRevision ?? true,
    applyWorkflow: vi.fn(async () => {
      order.push("apply-workflow");
    }),
    refreshWorkflow: vi.fn(async () => {
      order.push("refresh-workflow");
      return latest;
    }),
    refreshAssets: vi.fn(async () => {
      order.push("refresh-assets");
    }),
    syncSnapshot: vi.fn(async () => {
      order.push("sync-snapshot");
    }),
  };
  return { runner: createSlotMutationRunner(deps), deps, order, latest };
}

describe("slotMutationRunner", () => {
  it("reconciles an out-of-date response from the active workflow and rejects the stale mutation", async () => {
    const { runner, deps, latest } = createRunner({ currentRevision: false });

    const result = await runner.applyReconciledWorkflow(
      "workflow-1",
      { workflowId: "workflow-1", revision: 1 },
      workflow(2),
    );

    expect(result).toEqual({ stale: true, workflow: latest });
    expect(deps.applyWorkflow).not.toHaveBeenCalled();
    expect(deps.refreshWorkflow).toHaveBeenCalledTimes(1);
    expect(() => runner.requireFresh(result)).toThrow(
      "V2 slot changed while this request was in flight. Latest state loaded; review and retry.",
    );
  });

  it("does not apply or refresh a result after workflow identity changes", async () => {
    const { runner, deps } = createRunner({ activeWorkflowId: "workflow-2", currentRevision: false });

    await expect(runner.applyReconciledWorkflow(
      "workflow-1",
      { workflowId: "workflow-1", revision: 1 },
      workflow(2),
    )).rejects.toThrow(
      "V2 slot changed while this request was in flight. Review the latest state and retry.",
    );

    expect(deps.applyWorkflow).not.toHaveBeenCalled();
    expect(deps.refreshWorkflow).not.toHaveBeenCalled();
  });

  it("completes generation in workflow, assets, snapshot, versions, cleanup order", async () => {
    const { runner, order } = createRunner();

    const result = await runner.completeGeneration({
      workflowId: "workflow-1",
      capture: { workflowId: "workflow-1", revision: 1 },
      returnedWorkflow: workflow(2),
      refreshAssetsReason: "slot-run-completed",
      refreshSlotVersions: async () => {
        order.push("refresh-versions");
      },
      afterRefresh: () => {
        order.push("mark-clean");
      },
    });

    expect(result.workflow?.state_version).toBe(2);
    expect(order).toEqual([
      "apply-workflow",
      "refresh-assets",
      "sync-snapshot",
      "refresh-versions",
      "mark-clean",
    ]);
  });

  it("centralizes status, error propagation, and in-flight cleanup", async () => {
    const { runner } = createRunner();
    const setStatus = vi.fn();
    const setInFlight = vi.fn();
    const failure = new Error("etag conflict");

    await expect(runner.execute({
      setStatus,
      setInFlight,
      startStatus: "Saving...",
      successStatus: "Saved",
      failureMessage: "Save failed",
      propagateError: true,
    }, async () => {
      throw failure;
    })).rejects.toBe(failure);

    expect(setInFlight.mock.calls).toEqual([[true], [false, "etag conflict"]]);
    expect(setInFlight.mock.invocationCallOrder[1]).toBeLessThan(
      setStatus.mock.invocationCallOrder[1],
    );
    expect(setStatus.mock.calls).toEqual([["Saving..."], ["etag conflict"]]);
  });

  it("stops refresh stages and lifecycle updates after the workflow epoch changes", async () => {
    const options = {
      activeWorkflowId: "workflow-1" as string | null,
      workflowEpoch: 1,
    };
    const { runner, deps, latest } = createRunner(options);
    let releaseWorkflowRefresh!: () => void;
    const workflowRefreshPending = new Promise<void>((resolve) => {
      releaseWorkflowRefresh = resolve;
    });
    deps.refreshWorkflow.mockImplementation(async () => {
      await workflowRefreshPending;
      return latest;
    });
    const setStatus = vi.fn();
    const setInFlight = vi.fn();

    const operation = runner.execute({
      setStatus,
      setInFlight,
      startStatus: "Refreshing...",
      successStatus: "Refreshed",
      failureMessage: "Refresh failed",
    }, async () => {
      await runner.refreshWorkflowSnapshotAndVersions("workflow-1");
      return true;
    });
    await vi.waitFor(() => expect(deps.refreshWorkflow).toHaveBeenCalledTimes(1));

    options.activeWorkflowId = "workflow-2";
    options.workflowEpoch += 1;
    options.activeWorkflowId = "workflow-1";
    releaseWorkflowRefresh();
    await operation;

    expect(deps.syncSnapshot).not.toHaveBeenCalled();
    expect(setInFlight).toHaveBeenCalledTimes(1);
    expect(setStatus.mock.calls).toEqual([["Refreshing..."]]);
  });
});
