import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { AgentCanvasWorkflowV2, CanvasBindingCreateRequestV2 } from "../../../types-v2.ts";
import { useAgentCanvasSession } from "./useAgentCanvasSession.ts";

const fixture = vi.hoisted(() => ({ create: vi.fn(), setWorkflow: vi.fn(), workflow: null as AgentCanvasWorkflowV2 | null }));
vi.mock("../../../api/agentCanvasApi.ts", () => ({ agentCanvasApi: { createAgentCanvasBinding: fixture.create } }));
vi.mock("../../../AppContextValue.ts", () => ({ useApp: () => ({
  agentCanvasWorkflow: fixture.workflow, setAgentCanvasWorkflow: fixture.setWorkflow,
  workspaceHydrated: true, workspaceRestoreError: null,
}) }));
const request: CanvasBindingCreateRequestV2 = {
  source: { kind: "node_output", source_node_id: "source" }, target_node_id: "target",
  input_role: "image_reference", enabled: true, order: 0,
};
beforeEach(() => {
  fixture.create.mockReset(); fixture.setWorkflow.mockReset();
  fixture.workflow = { workflow_id: "a", nodes: [], bindings: [], assets: [] } as unknown as AgentCanvasWorkflowV2;
});
afterEach(cleanup);

it("does not dispatch a canceled queued binding", async () => {
  const h = renderHook(useAgentCanvasSession);
  await act(async () => { await h.result.current.actions.createBinding(request, { isCurrent: () => false }); });
  expect(fixture.create).not.toHaveBeenCalled();
  expect(fixture.setWorkflow).not.toHaveBeenCalled();
});

it.each(["response", "failure"])("ignores a late %s after cancellation", async (kind) => {
  let resolve!: (value: unknown) => void;
  let reject!: (value: Error) => void;
  fixture.create.mockReturnValue(new Promise((yes, no) => { resolve = yes; reject = no; }));
  let active = true;
  const h = renderHook(useAgentCanvasSession);
  let operation!: Promise<unknown>;
  act(() => { operation = h.result.current.actions.createBinding(request, { isCurrent: () => active }); });
  expect(fixture.create).toHaveBeenCalledOnce();
  active = false;
  await act(async () => {
    if (kind === "failure") reject(new Error("late failure"));
    else resolve({ value: { workflow: fixture.workflow, binding: { binding_id: "late" } } });
    await operation;
  });
  expect(fixture.setWorkflow).not.toHaveBeenCalled();
  expect(h.result.current.state.authoringError).toBeNull();
});

it("retains authority application for an active binding request", async () => {
  fixture.create.mockResolvedValue({ value: { workflow: fixture.workflow, binding: { binding_id: "real" } } });
  const h = renderHook(useAgentCanvasSession);
  await act(async () => { await h.result.current.actions.createBinding(request, { isCurrent: () => true }); });
  expect(fixture.create).toHaveBeenCalledWith("a", request, { conflictHandling: "caller" });
  expect(fixture.setWorkflow).toHaveBeenCalledOnce();
});
