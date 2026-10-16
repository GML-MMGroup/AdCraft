import { act, cleanup, renderHook } from "@testing-library/react";
import { type ChangeEvent } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { useCanvasMediaUpload } from "./useCanvasMediaUpload.ts";

const api = vi.hoisted(() => ({
  uploadAgentCanvasAsset: vi.fn(),
  listAgentCanvasProjectAssets: vi.fn(),
}));
vi.mock("../../../api/agentCanvasApi.ts", () => ({ agentCanvasApi: api }));

function asset(mediaType: "image" | "video"): ProjectAssetSummaryV2 {
  return {
    asset_id: "uploaded", version_id: "version-1", media_type: mediaType,
    source_type: "upload", display_name: "Local media", mime_type: `${mediaType}/test`,
    status: "ready", preview_url: null, media_url: "/media/uploaded",
    width: 1280, height: 720, duration_seconds: mediaType === "video" ? 8 : null,
    checksum: "checksum",
  };
}
function fileEvent(type: string | null = "image/png") {
  return { currentTarget: {
    files: type ? [new File(["test"], "local.png", { type })] : [], value: "local.png",
  } } as unknown as ChangeEvent<HTMLInputElement>;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.resetAllMocks();
  api.listAgentCanvasProjectAssets.mockResolvedValue({ assets: [] });
});
afterEach(cleanup);

describe("canvas local media upload", () => {
  it.each(["image", "video"] as const)("uploads %s with the shared contract and adds a source node at the chosen position", async (mediaType) => {
    api.uploadAgentCanvasAsset.mockResolvedValue({ asset: asset(mediaType) });
    const createSourceNode = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useCanvasMediaUpload({ workflowId: "workflow-1", createSourceNode }));
    expect(api.listAgentCanvasProjectAssets).not.toHaveBeenCalled();
    const event = fileEvent(`${mediaType}/test`);
    act(() => result.current.openPicker({ x: 420, y: 120 }));
    await act(() => result.current.onFileChange(event));
    const [workflowId, formData, operationKey] = api.uploadAgentCanvasAsset.mock.calls[0];
    expect(workflowId).toBe("workflow-1");
    expect(operationKey).toBeTruthy();
    expect(JSON.parse(formData.get("metadata"))).toEqual({
      media_type: mediaType, title: "local", semantic_role: null, metadata: {},
    });
    expect(createSourceNode).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      source: "project", assetId: "uploaded", versionId: "version-1", mediaType,
      width: 1280, height: 720, durationSeconds: mediaType === "video" ? 8 : null,
    }), { x: 420, y: 120 });
    expect(event.currentTarget.value).toBe("");
    expect(result.current.uploading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("cancels without uploading and rejects unsupported files", async () => {
    const createSourceNode = vi.fn();
    const { result } = renderHook(() => useCanvasMediaUpload({ workflowId: "workflow-1", createSourceNode }));
    act(() => result.current.openPicker({ x: 0, y: 0 }));
    await act(() => result.current.onFileChange(fileEvent(null)));
    expect(result.current.error).toBeNull();
    act(() => result.current.openPicker({ x: 0, y: 0 }));
    await act(() => result.current.onFileChange(fileEvent("audio/mp3")));
    expect(result.current.error).toContain("Choose an image or video");
    expect(api.uploadAgentCanvasAsset).not.toHaveBeenCalled();
    expect(createSourceNode).not.toHaveBeenCalled();
  });

  it("blocks duplicate submissions while uploading and allows the same file again after completion", async () => {
    const pending = deferred<{ asset: ProjectAssetSummaryV2 }>();
    api.uploadAgentCanvasAsset.mockReturnValue(pending.promise);
    const { result } = renderHook(() => useCanvasMediaUpload({ workflowId: "workflow-1", createSourceNode: vi.fn() }));
    act(() => result.current.openPicker({ x: 0, y: 0 }));
    let operation!: Promise<void>;
    act(() => { operation = result.current.onFileChange(fileEvent()); });
    expect(result.current.uploading).toBe(true);
    act(() => result.current.openPicker({ x: 20, y: 20 }));
    await act(() => result.current.onFileChange(fileEvent()));
    expect(api.uploadAgentCanvasAsset).toHaveBeenCalledTimes(1);
    await act(async () => { pending.resolve({ asset: asset("image") }); await operation; });
    act(() => result.current.openPicker({ x: 20, y: 20 }));
    await act(() => result.current.onFileChange(fileEvent()));
    expect(api.uploadAgentCanvasAsset).toHaveBeenCalledTimes(2);
  });

  it.each([false, true])("does not create a node after leaving the workflow (unmount=%s)", async (unmountPage) => {
    const pending = deferred<{ asset: ProjectAssetSummaryV2 }>();
    api.uploadAgentCanvasAsset.mockReturnValue(pending.promise);
    const createSourceNode = vi.fn();
    const { result, rerender, unmount } = renderHook(
      ({ workflowId }) => useCanvasMediaUpload({ workflowId, createSourceNode }),
      { initialProps: { workflowId: "workflow-1" } },
    );
    act(() => result.current.openPicker({ x: 0, y: 0 }));
    let operation!: Promise<void>;
    act(() => { operation = result.current.onFileChange(fileEvent()); });
    if (unmountPage) unmount();
    else rerender({ workflowId: "workflow-2" });
    await act(async () => { pending.resolve({ asset: asset("image") }); await operation; });
    expect(createSourceNode).not.toHaveBeenCalled();
  });

  it.each(["upload", "node"])("reports %s failures without retrying uploads", async (stage) => {
    api.uploadAgentCanvasAsset.mockResolvedValue({ asset: asset("image") });
    const createSourceNode = vi.fn().mockResolvedValue(undefined);
    if (stage === "upload") api.uploadAgentCanvasAsset.mockRejectedValue(new Error("Network error"));
    else createSourceNode.mockRejectedValue(new Error("Node error"));
    const { result } = renderHook(() => useCanvasMediaUpload({ workflowId: "workflow-1", createSourceNode }));
    act(() => result.current.openPicker({ x: 0, y: 0 }));
    await act(() => result.current.onFileChange(fileEvent()));
    expect(result.current.uploading).toBe(false);
    expect(result.current.error).toContain(stage === "upload" ? "Unable to upload" : "Open Project Assets and choose Add node");
    expect(api.uploadAgentCanvasAsset).toHaveBeenCalledTimes(1);
    if (stage === "upload") expect(createSourceNode).not.toHaveBeenCalled();
  });
});
