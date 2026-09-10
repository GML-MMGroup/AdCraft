import { afterEach, expect, it, vi } from "vitest";
import { v2Api } from "./v2Client.ts";
import { v2AuthoringConflictStore } from "./v2AuthoringConflictStore.ts";
import { v2EtagStore } from "./v2EtagStore.ts";

afterEach(() => {
  v2AuthoringConflictStore.clear();
  v2EtagStore.clear();
  vi.unstubAllGlobals();
});

it("refreshes a caller-owned binding conflict without publishing a global retry", async () => {
  v2EtagStore.set("workflow", "workflow-1", '"1"');
  const workflow = { workflow_id: "workflow-1", revision: 2 };
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => init?.method === "POST"
    ? new Response(JSON.stringify({ detail: { code: "workflow_state_conflict", message: "Conflict" } }), { status: 412 })
    : new Response(JSON.stringify(workflow), { headers: { ETag: '"2"' } }));
  vi.stubGlobal("fetch", fetchMock);
  await expect(v2Api.createAgentCanvasBinding("workflow-1", {
    source: { kind: "node_output", source_node_id: "source" }, target_node_id: "target", input_role: "image_reference",
  }, { conflictHandling: "caller" })).rejects.toMatchObject({ status: 412 });
  expect(v2EtagStore.get("workflow", "workflow-1")).toBe('"2"');
  expect(v2AuthoringConflictStore.current()).toBeNull();
  const calls = fetchMock.mock.calls.length;
  await v2AuthoringConflictStore.retry();
  expect(fetchMock).toHaveBeenCalledTimes(calls);
});
