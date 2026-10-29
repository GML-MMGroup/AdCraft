import { useState } from "react";
import { ReactFlow } from "@xyflow/react";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { V2ApiError } from "../../../api/v2Client.ts";
import type { AgentCanvasWorkflowV2, CanvasBindingV2, CanvasNodeV2 } from "../../../types-v2.ts";
import { normalizeAgentCanvasWorkflowV2, normalizeCanvasNodeV2 } from "../model/normalizers.ts";
import { useAgentCanvasSession } from "../session/useAgentCanvasSession.ts";
import { useAgentCanvasHistoryKeyboard } from "./useAgentCanvasHistoryKeyboard.ts";

const mocks = vi.hoisted(() => ({
  app: {} as Record<string, unknown>,
  api: {
    createAgentCanvasNode: vi.fn(), deleteAgentCanvasNode: vi.fn(), restoreAgentCanvasNode: vi.fn(),
    createAgentCanvasConnectedNode: vi.fn(), importAgentCanvasEditingExport: vi.fn(),
    createAgentCanvasBinding: vi.fn(), deleteAgentCanvasBinding: vi.fn(), restoreAgentCanvasBinding: vi.fn(),
    patchAgentCanvasLayout: vi.fn(), agentCanvasWorkflowWithEtag: vi.fn(), patchAgentCanvasNode: vi.fn(),
  },
}));
vi.mock("../../../api/agentCanvasApi.ts", async (load) => {
  const original = await load<typeof import("../../../api/agentCanvasApi.ts")>();
  return { ...original, agentCanvasApi: { ...original.agentCanvasApi, ...mocks.api } };
});
vi.mock("../../../AppContextValue.ts", () => ({ useApp: () => mocks.app }));

const api = mocks.api;
let server: AgentCanvasWorkflowV2;
let deletedNodes: Map<string, { node: CanvasNodeV2; bindings: CanvasBindingV2[] }>;
const node = (id: string) => normalizeCanvasNodeV2({
  node_id: id, workflow_id: "wf", node_type: "image", creative_role: "product",
  role_contract_version: "ad-media-role-v2", title: id, status: "ready",
  summary_prompt: "Previous summary", generation_prompt: "Previous prompt", structured_content: {},
  model_id: null, parameters: {}, prompt_context_snapshot_id: null,
  output_asset_id: "generated-output", output_asset_version_id: "output-v1", latest_attempt: null,
  position: { x: 10, y: 20 }, revision: 1, error: null,
  created_at: "2026-07-28T00:00:00Z", updated_at: "2026-07-28T00:00:00Z",
});
const binding = (id = "edge", source = "a", target = "b"): CanvasBindingV2 => ({
  binding_id: id, workflow_id: "wf", source: { kind: "node_output", source_node_id: source },
  target_node_id: target, input_role: "image_reference", enabled: true, order: 3,
  label: "Front view", metadata: { view: "front" }, created_at: "2026-07-28T00:00:00Z", updated_at: "2026-07-28T00:00:00Z",
});
function workflow(nodes = [node("a"), node("b")], bindings = [binding()]) {
  return normalizeAgentCanvasWorkflowV2({
    workflow_id: "wf", project_id: "project", workflow_schema_version: 2, canvas_model: "agent_canvas_v1",
    revision: 1, layout_revision: 1, nodes, bindings, assets: [],
  });
}
function reply(change: Partial<AgentCanvasWorkflowV2>, extra = {}) {
  server = { ...server, ...change, revision: server.revision + 1 };
  return { value: { workflow: server, node: null, binding: null, ...extra }, etag: `"r${server.revision}"` };
}
function useCanvas(initial: AgentCanvasWorkflowV2, blocked = false) {
  const [current, setWorkflow] = useState(initial);
  mocks.app = { agentCanvasWorkflow: current, setAgentCanvasWorkflow: setWorkflow, workspaceHydrated: true, workspaceRestoreError: null };
  const session = useAgentCanvasSession();
  useAgentCanvasHistoryKeyboard(session.history, blocked);
  return { ...session, setWorkflow };
}
function press(key = "z", modifiers: { ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean } = { ctrlKey: true }, target: EventTarget = window) {
  const event = new KeyboardEvent("keydown", { key, ...modifiers, bubbles: true, cancelable: true, composed: true });
  act(() => { target.dispatchEvent(event); });
  return event;
}
async function step(action: () => Promise<unknown>) { await act(async () => { await action(); }); }
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => { resolve = yes; });
  return { promise, resolve };
}
const createRequest = { node_type: "image" as const, creative_role: "product" as const, title: "Created", position: { x: 0, y: 0 } };
const connectRequest = { source: { kind: "node_output" as const, source_node_id: "a" }, target_node_id: "b", input_role: "image_reference" as const };
const conflict = (status = 412) => new V2ApiError({ status, code: "workflow_revision_conflict", message: "Conflict", payload: {} });

beforeEach(() => {
  Object.values(api).forEach((mock) => mock.mockReset());
  server = workflow();
  deletedNodes = new Map();
  api.createAgentCanvasNode.mockImplementation(async () => {
    const created = node("created");
    return reply({ nodes: [...server.nodes, created] }, { node: created });
  });
  api.deleteAgentCanvasNode.mockImplementation(async (_workflowId, id) => {
    const removed = server.nodes.find((item) => item.node_id === id)!;
    const incident = server.bindings.filter((item) => item.target_node_id === id || (item.source.kind === "node_output" && item.source.source_node_id === id));
    deletedNodes.set(id, { node: removed, bindings: incident });
    return reply({ nodes: server.nodes.filter((item) => item.node_id !== id), bindings: server.bindings.filter((item) => !incident.includes(item)) });
  });
  api.restoreAgentCanvasNode.mockImplementation(async (_workflowId, id) => {
    const saved = deletedNodes.get(id)!;
    const restored = saved.bindings.filter((item) => !server.bindings.some((other) => other.binding_id === item.binding_id));
    return reply({ nodes: [...server.nodes, saved.node], bindings: [...server.bindings, ...restored] }, {
      node: saved.node, restored_binding_ids: restored.map((item) => item.binding_id), skipped_binding_ids: [],
    });
  });
  api.createAgentCanvasBinding.mockImplementation(async () => {
    const created = binding("created-edge");
    return reply({ bindings: [...server.bindings, created] }, { binding: created });
  });
  api.deleteAgentCanvasBinding.mockImplementation(async (_workflowId, id) => reply({ bindings: server.bindings.filter((item) => item.binding_id !== id) }));
  api.restoreAgentCanvasBinding.mockImplementation(async (_workflowId, request) => {
    const restored = { ...request, workflow_id: "wf", created_at: "2026-07-28T00:00:00Z", updated_at: "2026-07-28T00:00:00Z" };
    return reply({ bindings: [...server.bindings, restored] }, { binding: restored });
  });
  api.patchAgentCanvasLayout.mockImplementation(async (_workflowId, request) => {
    server = { ...server, layout_revision: server.layout_revision + 1, nodes: server.nodes.map((item) => {
      const position = request.positions.find((p: { node_id: string }) => p.node_id === item.node_id);
      return position ? { ...item, position: { x: position.x, y: position.y } } : item;
    }) };
    return { workflow_id: "wf", revision: server.revision, layout_revision: server.layout_revision, positions: request.positions };
  });
  api.agentCanvasWorkflowWithEtag.mockImplementation(async () => ({ value: server, etag: `"r${server.revision}"` }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("canvas history through the session and keyboard", () => {
  it("groups keyboard edge-first node deletion, then restores the prompt, output and missing binding", async () => {
    let current!: ReturnType<typeof useCanvas>;
    function Canvas() {
      current = useCanvas(server);
      const wf = current.state.workflow!;
      return <>
        <div style={{ width: 800, height: 600 }}><ReactFlow
          nodes={wf.nodes.map((item) => ({ id: item.node_id, data: { label: item.title }, position: item.position, selected: item.node_id === "a" }))}
          edges={wf.bindings.map((item) => ({ id: item.binding_id, source: item.source.kind === "node_output" ? item.source.source_node_id : "asset", target: item.target_node_id }))}
          deleteKeyCode={["Backspace", "Delete"]}
          onEdgesDelete={(edges) => { edges.forEach((edge) => { void current.actions.deleteBinding(edge.id); }); }}
          onNodesDelete={(nodes) => { nodes.forEach((item) => { void current.actions.deleteNode(item.id); }); }}
        /></div>
        {wf.nodes.map((item) => <p key={item.node_id} data-testid={`content-${item.node_id}`}>{item.generation_prompt} / {item.output_asset_id} / {item.output_asset_version_id}</p>)}
      </>;
    }
    render(<Canvas />);
    fireEvent.keyDown(document, { key: "Delete", code: "Delete" });
    await waitFor(() => expect(current.history.state.undo).toHaveLength(1));
    expect(current.history.state.undo[0]).toEqual({ kind: "delete", node_ids: ["a"], bindings: [binding()] });
    expect(screen.queryByTestId("content-a")).toBeNull();
    expect(press().defaultPrevented).toBe(true);
    await waitFor(() => expect(current.history.state.redo).toHaveLength(1));
    expect(api.restoreAgentCanvasNode).toHaveBeenCalledWith("wf", "a", expect.any(String), { conflictHandling: "caller" });
    expect(api.restoreAgentCanvasBinding).toHaveBeenCalledWith("wf", {
      binding_id: "edge", source: { kind: "node_output", source_node_id: "a" }, target_node_id: "b",
      input_role: "image_reference", enabled: true, order: 3, label: "Front view", metadata: { view: "front" },
    }, expect.any(String), { conflictHandling: "caller" });
    expect(api.restoreAgentCanvasNode.mock.invocationCallOrder[0]).toBeLessThan(api.restoreAgentCanvasBinding.mock.invocationCallOrder[0]);
    expect(screen.getByTestId("content-a").textContent).toBe("Previous prompt / generated-output / output-v1");
  });

  it("records create only after the server succeeds and restores the same id on redo", async () => {
    const h = renderHook(() => useCanvas(server));
    const pending = deferred<ReturnType<typeof reply>>();
    api.createAgentCanvasNode.mockReturnValueOnce(pending.promise);
    let operation!: Promise<unknown>;
    act(() => { operation = h.result.current.actions.createNode(createRequest); });
    expect(h.result.current.history.state.undo).toEqual([]);
    await step(async () => { pending.resolve(reply({ nodes: [...server.nodes, node("created")] }, { node: node("created") })); await operation; });
    expect(h.result.current.history.state.undo).toEqual([{ kind: "create", node_id: "created" }]);
    await step(h.result.current.history.undo);
    expect(api.deleteAgentCanvasNode).toHaveBeenLastCalledWith("wf", "created", { conflictHandling: "caller" });
    await step(h.result.current.history.redo);
    expect(api.restoreAgentCanvasNode).toHaveBeenLastCalledWith("wf", "created", expect.any(String), { conflictHandling: "caller" });
    expect(h.result.current.state.workflow?.nodes.some((item) => item.node_id === "created")).toBe(true);
  });

  it("does not record a failed creation or an optimistic connection canceled before its response", async () => {
    const h = renderHook(() => useCanvas(server));
    api.createAgentCanvasNode.mockRejectedValueOnce(new Error("failed"));
    await step(async () => { await expect(h.result.current.actions.createNode(createRequest)).rejects.toThrow("failed"); });
    await step(() => h.result.current.actions.createBinding(connectRequest, { isCurrent: () => false }));
    expect(h.result.current.history.state.undo).toEqual([]);
  });

  it("records connected-node creation and upload-created source nodes", async () => {
    const h = renderHook(() => useCanvas(server));
    api.createAgentCanvasConnectedNode.mockResolvedValueOnce({ value: { workflow_id: "wf", revision: 2, layout_revision: 1, node: node("connected"), binding: binding("connected-edge", "a", "connected"), events_cursor: 2 } });
    await step(() => h.result.current.actions.createConnectedNode({ anchor_node_id: "a", direction: "downstream", node: createRequest, binding: { input_role: "image_reference" } }));
    expect(h.result.current.history.state.undo).toEqual([{ kind: "create", node_id: "connected" }]);
    await step(() => h.result.current.actions.createNode({ ...createRequest, source_asset_id: "upload" }));
    expect(h.result.current.history.state.undo.at(-1)).toEqual({ kind: "create", node_id: "created" });
  });

  it("groups multi-select nodes and standalone edges and redoes the entire delete gesture", async () => {
    server = workflow([node("a"), node("b"), node("c"), node("d")], [binding(), binding("standalone", "c", "d")]);
    const h = renderHook(() => useCanvas(server));
    await step(() => Promise.all([
      h.result.current.actions.deleteBinding("edge"), h.result.current.actions.deleteBinding("standalone"),
      h.result.current.actions.deleteNode("a"), h.result.current.actions.deleteNode("b"),
    ]));
    expect(h.result.current.history.state.undo).toHaveLength(1);
    expect(h.result.current.history.state.undo[0]).toMatchObject({ kind: "delete", node_ids: ["a", "b"], bindings: [binding(), binding("standalone", "c", "d")] });
    await step(h.result.current.history.undo);
    expect(h.result.current.state.workflow?.nodes).toHaveLength(4);
    expect(h.result.current.state.workflow?.bindings).toHaveLength(2);
    await step(h.result.current.history.redo);
    expect(h.result.current.state.workflow?.nodes.map((item) => item.node_id)).toEqual(["c", "d"]);
    expect(h.result.current.state.workflow?.bindings).toEqual([]);
  });

  it("undoes and redoes a multi-node drag through the layout queue", async () => {
    const h = renderHook(() => useCanvas(server));
    const before = [{ node_id: "a", x: 10, y: 20 }, { node_id: "b", x: 10, y: 20 }];
    const after = [{ node_id: "a", x: 100, y: 200 }, { node_id: "b", x: 300, y: 400 }];
    await step(() => h.result.current.actions.moveNodes(before, after));
    await step(h.result.current.history.undo);
    expect(h.result.current.state.workflow?.nodes.map((item) => item.position)).toEqual([{ x: 10, y: 20 }, { x: 10, y: 20 }]);
    await step(h.result.current.history.redo);
    expect(h.result.current.state.workflow?.nodes.map((item) => item.position)).toEqual([{ x: 100, y: 200 }, { x: 300, y: 400 }]);
    expect(api.patchAgentCanvasLayout.mock.calls.map((call) => call[1].positions)).toEqual([after, before, after]);
  });

  it("records the committed server positions for move validity and redo", async () => {
    const h = renderHook(() => useCanvas(server));
    const patch = api.patchAgentCanvasLayout.getMockImplementation()!;
    api.patchAgentCanvasLayout.mockImplementationOnce(async (id, request) => patch(id, { ...request, positions: [{ node_id: "a", x: 101, y: 201 }] }));
    await step(() => h.result.current.actions.moveNodes([{ node_id: "a", x: 10, y: 20 }], [{ node_id: "a", x: 100, y: 200 }]));
    expect(h.result.current.history.state.undo[0]).toMatchObject({ after: [{ node_id: "a", x: 101, y: 201 }] });
    await step(h.result.current.history.undo);
    await step(h.result.current.history.redo);
    expect(h.result.current.state.workflow?.nodes.find((item) => item.node_id === "a")?.position).toEqual({ x: 101, y: 201 });
  });

  it.each(["connect", "disconnect"] as const)("undoes and redoes %s with the server binding snapshot", async (kind) => {
    server = workflow(undefined, kind === "connect" ? [] : [binding()]);
    const h = renderHook(() => useCanvas(server));
    await step(() => kind === "connect" ? h.result.current.actions.createBinding(connectRequest) : h.result.current.actions.deleteBinding("edge"));
    const snapshot = kind === "connect" ? binding("created-edge") : binding();
    expect(h.result.current.history.state.undo).toEqual([{ kind, binding: snapshot }]);
    await step(h.result.current.history.undo);
    expect(h.result.current.state.workflow?.bindings).toHaveLength(kind === "connect" ? 0 : 1);
    await step(h.result.current.history.redo);
    expect(h.result.current.state.workflow?.bindings).toHaveLength(kind === "connect" ? 1 : 0);
    expect(api.restoreAgentCanvasBinding).toHaveBeenCalledWith("wf", expect.objectContaining({ binding_id: snapshot.binding_id, metadata: snapshot.metadata, order: 3 }), expect.any(String), { conflictHandling: "caller" });
  });

  it("drops a move invalidated by an Agent layout change and shows the validity toast", async () => {
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.moveNodes([{ node_id: "a", x: 10, y: 20 }], [{ node_id: "a", x: 100, y: 200 }]));
    act(() => h.result.current.setWorkflow({ ...server, nodes: server.nodes.map((item) => ({ ...item, position: { x: 900, y: 900 } })) }));
    await step(h.result.current.history.undo);
    expect(h.result.current.history.state.undo).toEqual([]);
    expect(h.result.current.history.state.redo).toEqual([]);
    expect(h.result.current.history.notice).toBe("The canvas changed since this step, so it can't be undone.");
    expect(api.patchAgentCanvasLayout).toHaveBeenCalledTimes(1);
  });

  it.each([412, 428])("refreshes the ETag and retries once after %s", async (status) => {
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.createNode(createRequest));
    api.deleteAgentCanvasNode.mockRejectedValueOnce(conflict(status));
    await step(h.result.current.history.undo);
    expect(api.agentCanvasWorkflowWithEtag).toHaveBeenCalledTimes(1);
    expect(api.deleteAgentCanvasNode).toHaveBeenCalledTimes(2);
    expect(api.deleteAgentCanvasNode.mock.calls.every((call) => call[2]?.conflictHandling === "caller")).toBe(true);
    expect(h.result.current.history.state.redo).toHaveLength(1);
  });

  it("keeps the entry after the retry fails and allows a later undo", async () => {
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.createNode(createRequest));
    api.deleteAgentCanvasNode.mockRejectedValueOnce(conflict()).mockRejectedValueOnce(conflict());
    await step(h.result.current.history.undo);
    expect(api.deleteAgentCanvasNode).toHaveBeenCalledTimes(2);
    expect(h.result.current.history.state.undo).toHaveLength(1);
    expect(h.result.current.history.notice).toBe("Undo failed. Please try again.");
    await step(h.result.current.history.undo);
    expect(h.result.current.history.state.redo).toHaveLength(1);
  });

  it("treats an Agent-writing binding DELETE no-op as failure and retains the entry", async () => {
    server = workflow(undefined, []);
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.createBinding(connectRequest));
    api.deleteAgentCanvasBinding.mockResolvedValueOnce({ value: { workflow: server } });
    await step(h.result.current.history.undo);
    expect(h.result.current.history.notice).toBe("The Agent is writing this node's prompt; try again shortly.");
    expect(h.result.current.history.state.undo).toHaveLength(1);
    expect(h.result.current.history.state.redo).toEqual([]);
  });

  it.each(["textarea", "input", "select", "contenteditable", "nokey", "shadow"])("leaves native undo alone inside %s", async (kind) => {
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.createNode(createRequest));
    const host = document.createElement("div"); document.body.append(host);
    const element = document.createElement(["input", "textarea", "select"].includes(kind) ? kind : "span");
    if (kind === "nokey") host.className = "nokey";
    if (kind === "contenteditable") host.setAttribute("contenteditable", "true");
    if (kind === "shadow") { const root = host.attachShadow({ mode: "open" }); root.append(element); element.setAttribute("contenteditable", "true"); }
    else host.append(element);
    expect(press("z", { ctrlKey: true }, element).defaultPrevented).toBe(false);
    expect(api.deleteAgentCanvasNode).not.toHaveBeenCalled();
    host.remove();
  });

  it.each([{ key: "y", ctrlKey: true }, { key: "z", ctrlKey: true, shiftKey: true }, { key: "z", metaKey: true, shiftKey: true }])("handles redo shortcut $key $shiftKey", async ({ key, ...modifiers }) => {
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.createNode(createRequest));
    press("z", { metaKey: true });
    await waitFor(() => expect(h.result.current.history.state.redo).toHaveLength(1));
    expect(press(key, modifiers).defaultPrevented).toBe(true);
    await waitFor(() => expect(h.result.current.history.state.undo).toHaveLength(1));
  });

  it("ignores shortcuts with empty stacks, during layout confirmation, or while undo is in flight", async () => {
    const h = renderHook(({ blocked }) => useCanvas(server, blocked), { initialProps: { blocked: false } });
    expect(press().defaultPrevented).toBe(false);
    await step(() => h.result.current.actions.createNode(createRequest));
    h.rerender({ blocked: true });
    expect(press().defaultPrevented).toBe(false);
    h.rerender({ blocked: false });
    const pending = deferred<ReturnType<typeof reply>>();
    api.deleteAgentCanvasNode.mockReturnValueOnce(pending.promise);
    press(); press(); press("y");
    expect(api.deleteAgentCanvasNode).toHaveBeenCalledTimes(1);
    await step(async () => pending.resolve(reply({ nodes: server.nodes.filter((item) => item.node_id !== "created") })));
    await waitFor(() => expect(h.result.current.history.state.redo).toHaveLength(1));
  });

  it("restores the current positions after a failed move undo so it can be retried", async () => {
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.moveNodes([{ node_id: "a", x: 10, y: 20 }], [{ node_id: "a", x: 100, y: 200 }]));
    api.patchAgentCanvasLayout.mockRejectedValueOnce(conflict()).mockRejectedValueOnce(conflict());
    await step(h.result.current.history.undo);
    expect(h.result.current.history.state.undo).toHaveLength(1);
    expect(h.result.current.history.notice).toBe("Undo failed. Please try again.");
    expect(h.result.current.state.workflow?.nodes.find((item) => item.node_id === "a")?.position).toEqual({ x: 100, y: 200 });
    await step(h.result.current.history.undo);
    expect(h.result.current.history.state.redo).toHaveLength(1);
  });

  it("resumes a partially completed multi-node restore after a later request fails", async () => {
    const h = renderHook(() => useCanvas(server));
    await step(() => Promise.all([h.result.current.actions.deleteNode("a"), h.result.current.actions.deleteNode("b")]));
    const restore = api.restoreAgentCanvasNode.getMockImplementation()!;
    api.restoreAgentCanvasNode.mockImplementationOnce(restore).mockRejectedValueOnce(conflict()).mockRejectedValueOnce(conflict());
    await step(h.result.current.history.undo);
    expect(h.result.current.history.state.undo).toHaveLength(1);
    await step(h.result.current.history.undo);
    expect(api.restoreAgentCanvasNode.mock.calls.map((call) => call[1])).toEqual(["a", "b", "b", "b"]);
    expect(h.result.current.state.workflow?.nodes).toHaveLength(2);
    expect(h.result.current.history.state.redo).toHaveLength(1);
  });

  it("queues undo behind a pending authoring write and ignores repeated shortcuts in the same tick", async () => {
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.createNode(createRequest));
    const pending = deferred<ReturnType<typeof reply>>();
    api.patchAgentCanvasNode.mockReturnValueOnce(pending.promise);
    let patch!: Promise<void>;
    act(() => { patch = h.result.current.actions.patchNode("a", { title: "Changed" }); });
    const first = new KeyboardEvent("keydown", { key: "z", ctrlKey: true, cancelable: true });
    const repeated = new KeyboardEvent("keydown", { key: "z", ctrlKey: true, cancelable: true });
    act(() => { window.dispatchEvent(first); window.dispatchEvent(repeated); });
    expect(first.defaultPrevented).toBe(true);
    expect(repeated.defaultPrevented).toBe(false);
    expect(api.deleteAgentCanvasNode).not.toHaveBeenCalled();
    await step(async () => { pending.resolve(reply({})); await patch; });
    await waitFor(() => expect(h.result.current.history.state.redo).toHaveLength(1));
    expect(api.deleteAgentCanvasNode).toHaveBeenCalledTimes(1);
  });

  it("undoes the newest server-confirmed creation when queued behind it", async () => {
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.createNode(createRequest));
    const pending = deferred<ReturnType<typeof reply>>();
    api.createAgentCanvasNode.mockReturnValueOnce(pending.promise);
    let creation!: Promise<unknown>;
    act(() => { creation = h.result.current.actions.createNode(createRequest); });
    press();
    await step(async () => { pending.resolve(reply({ nodes: [...server.nodes, node("second")] }, { node: node("second") })); await creation; });
    await waitFor(() => expect(h.result.current.history.busy).toBe(false));
    expect(api.deleteAgentCanvasNode).toHaveBeenCalledWith("wf", "second", { conflictHandling: "caller" });
    expect(h.result.current.history.state.undo).toEqual([{ kind: "create", node_id: "created" }]);
    expect(h.result.current.history.state.redo).toEqual([{ kind: "create", node_id: "second" }]);
  });

  it("reuses the binding restore idempotency key when retrying a conflict", async () => {
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.deleteBinding("edge"));
    api.restoreAgentCanvasBinding.mockRejectedValueOnce(conflict());
    await step(h.result.current.history.undo);
    expect(api.restoreAgentCanvasBinding).toHaveBeenCalledTimes(2);
    expect(api.restoreAgentCanvasBinding.mock.calls[0][2]).toBe(api.restoreAgentCanvasBinding.mock.calls[1][2]);
    expect(h.result.current.history.state.redo).toHaveLength(1);
  });

  it("records a user adding an editing export to the canvas as node creation", async () => {
    const h = renderHook(() => useCanvas(server));
    api.importAgentCanvasEditingExport.mockResolvedValueOnce({ value: { workflow_id: "wf", revision: 2, layout_revision: 1,
      node: node("exported"), binding: binding("exported-edge", "a", "exported"), asset: { asset_id: "exported-output" } } });
    await step(() => h.result.current.actions.importEditingExport("a", { export_id: "export" }));
    expect(h.result.current.history.state.undo).toEqual([{ kind: "create", node_id: "exported" }]);
  });

  it("lets node restore recover legacy image bindings from the server snapshot", async () => {
    const legacy: CanvasBindingV2 = { ...binding(), source: { kind: "image_asset", source_asset_id: "legacy", source_asset_version_id: null } };
    server = workflow(undefined, [legacy]);
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.deleteNode("b"));
    await step(h.result.current.history.undo);
    expect(h.result.current.state.workflow?.bindings).toEqual([legacy]);
    expect(api.restoreAgentCanvasBinding).not.toHaveBeenCalled();
  });

  it("does not record a standalone legacy image disconnect and skips its client restore after node deletion", async () => {
    const legacy: CanvasBindingV2 = { ...binding(), source: { kind: "image_asset", source_asset_id: "legacy", source_asset_version_id: null } };
    server = workflow(undefined, [legacy]);
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.deleteBinding("edge"));
    expect(h.result.current.history.state.undo).toEqual([]);
    expect(h.result.current.history.notice).toBeNull();
    server = { ...server, bindings: [legacy] };
    act(() => h.result.current.setWorkflow(server));
    await step(() => Promise.all([h.result.current.actions.deleteBinding("edge"), h.result.current.actions.deleteNode("b")]));
    await step(h.result.current.history.undo);
    expect(api.restoreAgentCanvasNode).toHaveBeenCalledTimes(1);
    expect(api.restoreAgentCanvasBinding).not.toHaveBeenCalled();
    expect(h.result.current.history.state.redo).toHaveLength(1);
  });

  it("uses server-restored bindings and silently skips missing endpoints", async () => {
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.deleteNode("a"));
    await step(h.result.current.history.undo);
    expect(api.restoreAgentCanvasBinding).not.toHaveBeenCalled();
    expect(h.result.current.state.workflow?.bindings).toHaveLength(1);
    await step(h.result.current.history.redo);
    deletedNodes.get("a")!.bindings = [];
    server = { ...server, nodes: [] };
    act(() => h.result.current.setWorkflow(server));
    await step(h.result.current.history.undo);
    expect(api.restoreAgentCanvasBinding).not.toHaveBeenCalled();
  });

  it("clears history on workflow change and unmount, including late server responses", async () => {
    const h = renderHook(() => useCanvas(server));
    await step(() => h.result.current.actions.createNode(createRequest));
    const pending = deferred<ReturnType<typeof reply>>();
    api.createAgentCanvasNode.mockReturnValueOnce(pending.promise);
    let operation!: Promise<unknown>;
    act(() => { operation = h.result.current.actions.createNode(createRequest); });
    act(() => h.result.current.setWorkflow({ ...server, workflow_id: "other" }));
    await step(async () => { pending.resolve(reply({}, { node: node("late") })); await operation; });
    expect(h.result.current.history.state.undo).toEqual([]);
    act(() => h.result.current.setWorkflow(server));
    expect(h.result.current.history.state.undo).toEqual([]);
    h.unmount();
    const fresh = renderHook(() => useCanvas(server));
    expect(fresh.result.current.history.state.undo).toEqual([]);
    expect(press().defaultPrevented).toBe(false);
  });
});
