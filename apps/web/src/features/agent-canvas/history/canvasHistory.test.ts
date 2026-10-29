import { describe, expect, it } from "vitest";
import type { AgentCanvasWorkflowV2, CanvasBindingV2 } from "../../../types-v2.ts";
import { canvasHistoryReducer, createCanvasHistory, isCanvasHistoryEntryValid, type CanvasHistoryEntry } from "./canvasHistory.ts";

const binding: CanvasBindingV2 = {
  binding_id: "binding", workflow_id: "wf", source: { kind: "node_output", source_node_id: "a" },
  target_node_id: "b", input_role: "image_reference", enabled: true, order: 2,
  label: "Reference", metadata: { anchor: "front" }, created_at: "", updated_at: "",
};
const entries: CanvasHistoryEntry[] = [
  { kind: "create", node_id: "a" },
  { kind: "delete", node_ids: ["a", "b"], bindings: [binding] },
  { kind: "move", before: [{ node_id: "a", x: 0, y: 0 }], after: [{ node_id: "a", x: 80, y: 40 }] },
  { kind: "connect", binding },
  { kind: "disconnect", binding },
];

describe("canvas history", () => {
  it.each(entries)("records, undoes and redoes $kind", (entry) => {
    const recorded = canvasHistoryReducer(createCanvasHistory("wf"), { type: "record", entry });
    expect(recorded.undo).toEqual([entry]);
    const undone = canvasHistoryReducer(recorded, { type: "undo" });
    expect(undone.undo).toEqual([]);
    expect(undone.redo).toEqual([entry]);
    const redone = canvasHistoryReducer(undone, { type: "redo" });
    expect(redone.undo).toEqual([entry]);
    expect(redone.redo).toEqual([]);
  });

  it("clears redo after a new successful user operation", () => {
    let state = canvasHistoryReducer(createCanvasHistory("wf"), { type: "record", entry: entries[0] });
    state = canvasHistoryReducer(state, { type: "undo" });
    state = canvasHistoryReducer(state, { type: "record", entry: entries[2] });
    expect(state.undo).toEqual([entries[2]]);
    expect(state.redo).toEqual([]);
  });

  it("retains the latest 50 steps in order", () => {
    let state = createCanvasHistory("wf");
    for (let index = 0; index < 55; index += 1) {
      state = canvasHistoryReducer(state, { type: "record", entry: { kind: "create", node_id: String(index) } });
    }
    expect(state.undo).toHaveLength(50);
    expect(state.undo[0]).toEqual({ kind: "create", node_id: "5" });
    expect(state.undo[49]).toEqual({ kind: "create", node_id: "54" });
    for (let index = 0; index < 50; index += 1) state = canvasHistoryReducer(state, { type: "undo" });
    expect(state.redo).toHaveLength(50);
    for (let index = 0; index < 50; index += 1) state = canvasHistoryReducer(state, { type: "redo" });
    expect(state.undo[49]).toEqual({ kind: "create", node_id: "54" });
  });

  it("clears both stacks when the workflow switches", () => {
    let state = canvasHistoryReducer(createCanvasHistory("wf"), { type: "record", entry: entries[0] });
    state = canvasHistoryReducer(state, { type: "record", entry: entries[1] });
    state = canvasHistoryReducer(state, { type: "undo" });
    expect(canvasHistoryReducer(state, { type: "reset", workflowId: "other" })).toEqual(createCanvasHistory("other"));
  });

  it("drops an invalid step without moving it to the opposite stack", () => {
    const state = canvasHistoryReducer(createCanvasHistory("wf"), { type: "record", entry: entries[0] });
    expect(canvasHistoryReducer(state, { type: "drop", direction: "undo" }).undo).toEqual([]);
    const undone = canvasHistoryReducer(state, { type: "undo" });
    expect(canvasHistoryReducer(undone, { type: "drop", direction: "redo" }).redo).toEqual([]);
  });
});


describe("history validity against the current session", () => {
  const live = {
    nodes: [{ node_id: "a", position: { x: 80, y: 40 } }, { node_id: "b", position: { x: 0, y: 0 } }],
    bindings: [binding], assets: [],
  } as unknown as AgentCanvasWorkflowV2;
  it.each(entries)("checks $kind and its mirrored redo", (entry) => {
    let undoState = live;
    let redoState = live;
    switch (entry.kind) {
      case "create": redoState = { ...live, nodes: live.nodes.filter((node) => node.node_id !== "a") }; break;
      case "delete": undoState = { ...live, nodes: [], bindings: [] }; break;
      case "move": redoState = { ...live, nodes: live.nodes.map((node) => ({ ...node, position: { x: 0, y: 0 } })) }; break;
      case "connect": redoState = { ...live, bindings: [] }; break;
      case "disconnect": undoState = { ...live, bindings: [] }; break;
    }
    expect(isCanvasHistoryEntryValid(entry, "undo", undoState)).toBe(true);
    expect(isCanvasHistoryEntryValid(entry, "undo", redoState)).toBe(false);
    expect(isCanvasHistoryEntryValid(entry, "redo", redoState)).toBe(true);
    expect(isCanvasHistoryEntryValid(entry, "redo", undoState)).toBe(false);
  });

  it("rejects moves and binding restores whose node endpoint is missing", () => {
    const missing = { ...live, nodes: live.nodes.filter((node) => node.node_id !== "a"), bindings: [] };
    expect(isCanvasHistoryEntryValid(entries[2], "undo", missing)).toBe(false);
    expect(isCanvasHistoryEntryValid(entries[3], "redo", missing)).toBe(false);
    expect(isCanvasHistoryEntryValid(entries[4], "undo", missing)).toBe(false);
  });

  it("requires the image asset and target for a disconnected image reference", () => {
    const image: CanvasHistoryEntry = { kind: "disconnect", binding: { ...binding, source: {
      kind: "image_asset", source_asset_id: "image", source_asset_version_id: "version",
    } } };
    const missing = { ...live, bindings: [] };
    expect(isCanvasHistoryEntryValid(image, "undo", missing)).toBe(false);
    const present = { ...missing, assets: [{ asset_id: "image" }] } as AgentCanvasWorkflowV2;
    expect(isCanvasHistoryEntryValid(image, "undo", present)).toBe(true);
  });
});
