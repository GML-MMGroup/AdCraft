import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentCanvasEditingPanel } from "./AgentCanvasEditingPanel.tsx";
import { editingFixture } from "./cutia/fixtures.test-support.ts";
import { CUTIA_CHANNEL } from "./cutia/protocol.ts";
import { CUTIA_PROJECT_KEY, snapshotKey } from "./cutia/project.ts";
import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });
function setup() {
  const fixture = editingFixture();
  const patchNode = vi.fn().mockResolvedValue(undefined);
  const onClose = vi.fn();
  const onAddRenderedAssetToCanvas = vi.fn().mockResolvedValue(undefined);
  render(<AgentCanvasEditingPanel {...fixture} patchNode={patchNode} onClose={onClose} onAddRenderedAssetToCanvas={onAddRenderedAssetToCanvas} />);
  const frame = screen.getByTitle("Editing studio") as HTMLIFrameElement;
  const session = decodeURIComponent(new URL(frame.src).hash.slice(1));
  const post = vi.spyOn(frame.contentWindow!, "postMessage");
  const send = async (type: string, payload = {}, overrides = {}) => act(async () => {
    window.dispatchEvent(new MessageEvent("message", { source: frame.contentWindow, origin: window.location.origin, data: { channel: CUTIA_CHANNEL, session, type, ...payload }, ...overrides }));
  });
  return { ...fixture, patchNode, onClose, onAddRenderedAssetToCanvas, frame, session, post, send };
}

describe("Cutia editing host", () => {
  it("waits while downloads make progress and clears the inactivity timer once loaded", async () => {
    vi.useFakeTimers();
    const { send } = setup();
    await act(async () => { await vi.advanceTimersByTimeAsync(110_000); });
    await send("loading-media", { loading: "Loading media 2/5 · BGM 75%" });
    await act(async () => { await vi.advanceTimersByTimeAsync(110_000); });
    expect(screen.queryByRole("alert")).toBeNull();
    await send("loaded");
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("still reports a stalled editor after no loading activity", async () => {
    vi.useFakeTimers();
    setup();
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(screen.getByRole("alert").textContent).toContain("The editor could not load");
  });

  it("initializes the native editor without writing and rejects other origins, windows and sessions", async () => {
    const { send, post, patchNode, snapshot } = setup();
    await send("ready", {}, { origin: "https://wrong.example" });
    await send("ready", {}, { source: window });
    await send("ready", { session: "old" });
    expect(post).not.toHaveBeenCalled();
    await send("ready");
    expect(post).toHaveBeenCalledWith(expect.objectContaining({ type: "init", snapshot }), window.location.origin);
    await send("loading-media", { loading: "Loading media 1/5 · BGM 35%" });
    expect(screen.getByRole("status").textContent).toBe("Loading media 1/5 · BGM 35%");
    await send("loaded");
    expect(screen.queryByRole("link", { name: "Cutia", exact: true })).toBeNull();
    expect(screen.getByRole("button", { name: "Export", exact: true }).hasAttribute("disabled")).toBe(false);
    expect(patchNode).not.toHaveBeenCalled();
  });

  it("reopens a failed initialization in a fresh session without saving or losing the project", async () => {
    const { send, frame, session, snapshot, patchNode } = setup();
    await send("error", { error: "BGM: Failed to fetch" });
    expect(screen.getByRole("alert").textContent).toContain("BGM: Failed to fetch");
    fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    const nextFrame = screen.getByTitle("Editing studio") as HTMLIFrameElement;
    const nextSession = decodeURIComponent(new URL(nextFrame.src).hash.slice(1));
    expect(nextFrame).not.toBe(frame);
    expect(nextSession).not.toBe(session);
    expect(screen.queryByRole("alert")).toBeNull();
    const nextPost = vi.spyOn(nextFrame.contentWindow!, "postMessage");
    await act(async () => {
      window.dispatchEvent(new MessageEvent("message", { source: nextFrame.contentWindow, origin: window.location.origin,
        data: { channel: CUTIA_CHANNEL, session: nextSession, type: "ready" } }));
    });
    expect(nextPost).toHaveBeenCalledWith(expect.objectContaining({ type: "init", snapshot }), window.location.origin);
    expect(patchNode).not.toHaveBeenCalled();
  });

  it("flushes the newest native project into parameters while preserving unrelated values", async () => {
    const { snapshot, send, patchNode, post } = setup();
    snapshot.project.settings.fps = 24;
    await send("flush", { snapshot, requestId: "flush-1" });
    expect(patchNode).toHaveBeenCalledWith("editing-1", { parameters: { existing: "preserve", [CUTIA_PROJECT_KEY]: { snapshot } } }, { coalesce: true, optimistic: false });
    expect(post).toHaveBeenCalledWith(expect.objectContaining({ type: "response", requestId: "flush-1", error: undefined }), window.location.origin);
  });

  it("does not close until the child confirms its save completed", async () => {
    const { send, onClose, post } = setup();
    await send("loaded");
    fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
    expect(post).toHaveBeenCalledWith(expect.objectContaining({ type: "close" }), window.location.origin);
    expect(onClose).not.toHaveBeenCalled();
    await send("closed");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("retains unsaved edits on failure and retries the failed write", async () => {
    const { snapshot, send, patchNode, onClose } = setup();
    await send("loaded");
    patchNode.mockRejectedValueOnce(new Error("offline"));
    snapshot.project.settings.fps = 24;
    await send("flush", { snapshot, requestId: "failed" });
    expect(screen.getByRole("alert").textContent).toContain("offline");
    expect(screen.getByRole("status").textContent).not.toBe("Saved");
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry saving" }));
    await waitFor(() => expect(patchNode).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("uploads a rendered file, persists the export and invalidates it after another edit", async () => {
    const { snapshot, workflow, send, patchNode, onAddRenderedAssetToCanvas } = setup();
    const asset = { ...workflow.assets[0], asset_id: "rendered-film" };
    vi.spyOn(agentCanvasApi, "uploadAgentCanvasAsset").mockResolvedValue({ workflow_id: "workflow-1", asset, pending_handoff_id: null });
    await send("loaded");
    await send("exported", { buffer: new ArrayBuffer(16), filename: "Film.webm", mimeType: "video/webm", snapshotKey: snapshotKey(snapshot), requestId: "render" });
    await waitFor(() => expect(patchNode).toHaveBeenCalledWith("editing-1", expect.objectContaining({ parameters: expect.objectContaining({ [CUTIA_PROJECT_KEY]: expect.objectContaining({ export: expect.objectContaining({ assetId: "rendered-film" }) }) }) }), { optimistic: false }));
    fireEvent.click(screen.getByRole("button", { name: "Add to Canvas" }));
    await waitFor(() => expect(onAddRenderedAssetToCanvas).toHaveBeenCalledWith(asset));
    snapshot.project.settings.fps = 24;
    await send("snapshot", { snapshot });
    expect(screen.getByRole("button", { name: "Add to Canvas" }).hasAttribute("disabled")).toBe(true);
  });

  it("keeps a render downloadable and retries upload without rendering it again", async () => {
    const { snapshot, workflow, send } = setup();
    const upload = vi.spyOn(agentCanvasApi, "uploadAgentCanvasAsset").mockRejectedValueOnce(new Error("upload offline")).mockResolvedValue({ workflow_id: "workflow-1", asset: workflow.assets[0], pending_handoff_id: null });
    await send("loaded");
    await send("exported", { buffer: new ArrayBuffer(16), filename: "Film.webm", snapshotKey: snapshotKey(snapshot), requestId: "render" });
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("upload offline"));
    expect(screen.getByRole("button", { name: "Download exported video" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry upload" }));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    expect(upload.mock.calls[0][2]).toBe(upload.mock.calls[1][2]);
    await waitFor(() => expect(screen.getByRole("button", { name: "Add to Canvas" }).hasAttribute("disabled")).toBe(false));
  });

  it("does not overwrite malformed saved projects", () => {
    const { node, workflow } = editingFixture();
    node.parameters[CUTIA_PROJECT_KEY] = { snapshot: { schemaVersion: 99 } };
    const patchNode = vi.fn();
    render(<AgentCanvasEditingPanel node={node} workflow={workflow} patchNode={patchNode} onClose={vi.fn()} />);
    expect(screen.getByRole("alert").textContent).toContain("saved editing project");
    expect(screen.queryByTitle("Editing studio")).toBeNull();
    expect(patchNode).not.toHaveBeenCalled();
  });
});
