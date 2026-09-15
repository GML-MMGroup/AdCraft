import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";
import { notifyProviderConfigurationChanged } from "../../../api/providerConfigurationEvents.ts";

const api = vi.hoisted(() => ({
  listProviderModels: vi.fn(),
  getModelDefaults: vi.fn(),
}));

vi.mock("../../../api/client.ts", () => ({ api }));

import { useAgentCanvasProviderModels } from "./useAgentCanvasProviderModels.ts";
import { PROVIDER_MODEL_CACHE_MAX_AGE_MS } from "./providerModelResources.ts";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function node(nodeId: string, nodeType: CanvasNodeV2["node_type"]): CanvasNodeV2 {
  return {
    node_id: nodeId,
    workflow_id: "workflow-1",
    node_type: nodeType,
    creative_role: nodeType === "script" ? "script" : nodeType === "image" ? "general_image" : "general_text",
    role_contract_version: "ad-media-role-v1",
    title: nodeType,
    status: "draft",
    summary_prompt: null,
    generation_prompt: "Prompt",
    structured_content: {},
    model_id: null,
    model_selection_mode: "default",
    model_ref: null,
    model_summary: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    created_at: "2026-07-30T00:00:00Z",
    updated_at: "2026-07-30T00:00:00Z",
  };
}

function workflowWith(nodeValue: CanvasNodeV2): AgentCanvasWorkflowV2 {
  return {
    workflow_id: "workflow-1",
    project_id: "project-1",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 1,
    layout_revision: 1,
    nodes: [nodeValue],
    bindings: [],
    assets: [],
  };
}

describe("useAgentCanvasProviderModels", () => {
  afterEach(cleanup);

  beforeEach(() => {
    cleanup();
    notifyProviderConfigurationChanged("all");
    vi.clearAllMocks();
    api.getModelDefaults.mockResolvedValue({
      defaults: { text: "vendor:text-default", video: "vendor:video-default" },
      modes: { text: "explicit", video: "explicit" },
      revisions: { text: 1, video: 1 },
    });
  });

  it.each(["text", "script", "image", "video", "audio"] as const)(
    "loads the canonical catalog filtered for a %s node",
    async (nodeType) => {
      api.listProviderModels.mockResolvedValue({ items: [] });
      const selected = node(`${nodeType}-1`, nodeType);

      renderHook(() => useAgentCanvasProviderModels(workflowWith(selected), selected));

      await waitFor(() => expect(api.listProviderModels).toHaveBeenCalledWith({
        node_type: nodeType,
        include_unavailable: true,
      }));
    },
  );

  it("reopens a closed node with immediate cached models and no new requests", async () => {
    const video = node("video-cache", "video");
    const catalog = [{ model_ref: "vendor:video-default" }];
    api.listProviderModels.mockResolvedValue({ items: catalog });
    const { result, rerender } = renderHook(
      ({ selected }: { selected: CanvasNodeV2 | null }) => useAgentCanvasProviderModels(workflowWith(video), selected),
      { initialProps: { selected: video as CanvasNodeV2 | null } },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    rerender({ selected: null });
    expect(result.current.models).toEqual([]);
    rerender({ selected: video });
    expect(result.current.models).toEqual(catalog);
    expect(result.current.defaultModelRef).toBe("vendor:video-default");
    expect(result.current.loading).toBe(false);
    expect(api.listProviderModels).toHaveBeenCalledTimes(1);
    expect(api.getModelDefaults).toHaveBeenCalledTimes(1);
  });

  it("caches each node type separately while sharing installation defaults", async () => {
    const video = node("video-cache", "video");
    const image = node("image-cache", "image");
    api.listProviderModels.mockImplementation(async ({ node_type }) => ({ items: [{ model_ref: node_type }] }));
    const { result, rerender } = renderHook(
      ({ selected }) => useAgentCanvasProviderModels(workflowWith(selected), selected),
      { initialProps: { selected: video } },
    );
    await waitFor(() => expect(result.current.models[0]?.model_ref).toBe("video"));
    rerender({ selected: image });
    expect(result.current.models.some(model => model.model_ref === "video")).toBe(false);
    await waitFor(() => expect(result.current.models[0]?.model_ref).toBe("image"));
    rerender({ selected: video });
    expect(result.current.models[0]?.model_ref).toBe("video");
    expect(result.current.loading).toBe(false);
    expect(api.listProviderModels).toHaveBeenCalledTimes(2);
    expect(api.getModelDefaults).toHaveBeenCalledTimes(1);
  });

  it("reuses an in-flight request after closing and reopening", async () => {
    const video = node("video-inflight", "video");
    let resolveCatalog!: (value: { items: [] }) => void;
    api.listProviderModels.mockReturnValue(new Promise(resolve => { resolveCatalog = resolve; }));
    const { result, rerender } = renderHook(
      ({ selected }: { selected: CanvasNodeV2 | null }) => useAgentCanvasProviderModels(null, selected),
      { initialProps: { selected: video as CanvasNodeV2 | null } },
    );
    rerender({ selected: null });
    rerender({ selected: video });
    expect(api.listProviderModels).toHaveBeenCalledTimes(1);
    expect(api.getModelDefaults).toHaveBeenCalledTimes(1);
    await act(async () => resolveCatalog({ items: [] }));
    await waitFor(() => expect(result.current.loading).toBe(false));
  });

  it("shares requests across consumers, Strict Mode and a later remount", async () => {
    const video = node("shared-video", "video");
    api.listProviderModels.mockResolvedValue({ items: [{ model_ref: "cached" }] });
    const first = renderHook(() => useAgentCanvasProviderModels(null, video), { wrapper: StrictMode });
    const second = renderHook(() => useAgentCanvasProviderModels(null, video));
    await waitFor(() => expect(second.result.current.loading).toBe(false));
    expect(first.result.current.models[0]?.model_ref).toBe("cached");
    first.unmount();
    second.unmount();
    const remounted = renderHook(() => useAgentCanvasProviderModels(null, video));
    expect(remounted.result.current.models[0]?.model_ref).toBe("cached");
    expect(remounted.result.current.loading).toBe(false);
    expect(api.listProviderModels).toHaveBeenCalledTimes(1);
    expect(api.getModelDefaults).toHaveBeenCalledTimes(1);
  });

  it("does not refresh for same-type node changes or Workflow revisions", async () => {
    const video = node("first", "video");
    api.listProviderModels.mockResolvedValue({ items: [] });
    const { result, rerender } = renderHook(
      ({ selected, workflow }) => useAgentCanvasProviderModels(workflow, selected),
      { initialProps: { selected: video, workflow: workflowWith(video) } },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    rerender({ selected: node("second", "video"), workflow: { ...workflowWith(video), revision: 99 } });
    expect(result.current.loading).toBe(false);
    expect(api.listProviderModels).toHaveBeenCalledTimes(1);
    expect(api.getModelDefaults).toHaveBeenCalledTimes(1);
  });

  it("publishes the model catalog before a slow defaults response", async () => {
    const defaults = deferred<{ defaults: { video: string } }>();
    api.getModelDefaults.mockReturnValue(defaults.promise);
    api.listProviderModels.mockResolvedValue({ items: [{ model_ref: "catalog-ready" }] });
    const { result } = renderHook(() => useAgentCanvasProviderModels(null, node("video", "video")));
    await waitFor(() => expect(result.current.models[0]?.model_ref).toBe("catalog-ready"));
    expect(result.current.loading).toBe(true);
    await act(async () => defaults.resolve({ defaults: { video: "catalog-ready" } }));
    expect(result.current.loading).toBe(false);
    expect(result.current.defaultModelRef).toBe("catalog-ready");
  });

  it("refreshes expired cache on reopen without clearing existing content", async () => {
    let now = 1_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    api.listProviderModels.mockResolvedValue({ items: [{ model_ref: "old" }] });
    const video = node("ttl-video", "video");
    const { result, rerender } = renderHook(
      ({ selected }: { selected: CanvasNodeV2 | null }) => useAgentCanvasProviderModels(null, selected),
      { initialProps: { selected: video as CanvasNodeV2 | null } },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    rerender({ selected: null });
    now += PROVIDER_MODEL_CACHE_MAX_AGE_MS + 1;
    const nextCatalog = deferred<{ items: { model_ref: string }[] }>();
    api.listProviderModels.mockReturnValue(nextCatalog.promise);
    rerender({ selected: video });
    expect(result.current.models[0]?.model_ref).toBe("old");
    expect(result.current.loading).toBe(false);
    expect(api.listProviderModels).toHaveBeenCalledTimes(2);
    await act(async () => nextCatalog.resolve({ items: [{ model_ref: "new" }] }));
    expect(result.current.models[0]?.model_ref).toBe("new");
  });

  it("revalidates active resources on focus and stops listening while closed", async () => {
    api.listProviderModels.mockResolvedValue({ items: [] });
    const video = node("focus-video", "video");
    const { result, rerender } = renderHook(
      ({ selected }: { selected: CanvasNodeV2 | null }) => useAgentCanvasProviderModels(null, selected),
      { initialProps: { selected: video as CanvasNodeV2 | null } },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(api.listProviderModels).toHaveBeenCalledTimes(2);
    expect(api.getModelDefaults).toHaveBeenCalledTimes(2);
    expect(result.current.loading).toBe(false);
    rerender({ selected: null });
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(api.listProviderModels).toHaveBeenCalledTimes(2);
  });

  it("checks cache age when selecting another node of the same type", async () => {
    let now = 1_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    api.listProviderModels.mockResolvedValue({ items: [{ model_ref: "cached" }] });
    const { result, rerender } = renderHook(
      ({ selected }) => useAgentCanvasProviderModels(null, selected),
      { initialProps: { selected: node("video-a", "video") } },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    now += PROVIDER_MODEL_CACHE_MAX_AGE_MS + 1;
    rerender({ selected: node("video-b", "video") });
    expect(result.current.models[0]?.model_ref).toBe("cached");
    expect(result.current.loading).toBe(false);
    expect(api.listProviderModels).toHaveBeenCalledTimes(2);
    expect(api.getModelDefaults).toHaveBeenCalledTimes(2);
    await act(async () => {});
  });

  it("invalidates only defaults when installation defaults change", async () => {
    api.listProviderModels.mockResolvedValue({ items: [{ model_ref: "catalog" }] });
    const { result } = renderHook(() => useAgentCanvasProviderModels(null, node("video", "video")));
    await waitFor(() => expect(result.current.loading).toBe(false));
    api.getModelDefaults.mockResolvedValue({ defaults: { video: "new-default" } });
    await act(async () => notifyProviderConfigurationChanged("defaults"));
    expect(result.current.defaultModelRef).toBe("new-default");
    expect(result.current.models[0]?.model_ref).toBe("catalog");
    expect(api.listProviderModels).toHaveBeenCalledTimes(1);
    expect(api.getModelDefaults).toHaveBeenCalledTimes(2);
  });

  it("invalidates all types but only reloads active resources", async () => {
    api.listProviderModels.mockResolvedValue({ items: [] });
    const { result, rerender } = renderHook(
      ({ selected }) => useAgentCanvasProviderModels(null, selected),
      { initialProps: { selected: node("video", "video") } },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    rerender({ selected: node("image", "image") });
    await waitFor(() => expect(result.current.loading).toBe(false));
    api.listProviderModels.mockClear();
    await act(async () => notifyProviderConfigurationChanged("all"));
    expect(api.listProviderModels).toHaveBeenCalledTimes(1);
    expect(api.listProviderModels).toHaveBeenLastCalledWith({ node_type: "image", include_unavailable: true });
    rerender({ selected: node("video", "video") });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(api.listProviderModels).toHaveBeenCalledTimes(2);
  });

  it.each(["success", "failure"])("ignores pre-invalidation late %s responses", async outcome => {
    const oldCatalog = deferred<{ items: { model_ref: string }[] }>();
    const oldDefaults = deferred<{ defaults: { video: string } }>();
    api.listProviderModels.mockReturnValueOnce(oldCatalog.promise).mockResolvedValue({ items: [{ model_ref: "new" }] });
    api.getModelDefaults.mockReturnValueOnce(oldDefaults.promise).mockResolvedValue({ defaults: { video: "new" } });
    const { result } = renderHook(() => useAgentCanvasProviderModels(null, node("video", "video")));
    await act(async () => notifyProviderConfigurationChanged("all"));
    expect(result.current.models[0]?.model_ref).toBe("new");
    await act(async () => {
      if (outcome === "success") {
        oldCatalog.resolve({ items: [{ model_ref: "old" }] });
        oldDefaults.resolve({ defaults: { video: "old" } });
      } else {
        oldCatalog.reject(new Error("Old request failed"));
        oldDefaults.reject(new Error("Old request failed"));
      }
    });
    expect(result.current.models[0]?.model_ref).toBe("new");
    expect(result.current.defaultModelRef).toBe("new");
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("keeps successful data on refresh failure and retries only on a new activation", async () => {
    const video = node("retry-video", "video");
    api.listProviderModels.mockResolvedValueOnce({ items: [{ model_ref: "cached" }] }).mockRejectedValue(new Error("Offline"));
    const { result, rerender } = renderHook(
      ({ selected }: { selected: CanvasNodeV2 | null }) => useAgentCanvasProviderModels(null, selected),
      { initialProps: { selected: video as CanvasNodeV2 | null } },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(result.current.error).toBe("Offline");
    expect(result.current.models[0]?.model_ref).toBe("cached");
    expect(result.current.loading).toBe(false);
    rerender({ selected: { ...video, revision: 2 } });
    expect(api.listProviderModels).toHaveBeenCalledTimes(2);
    api.listProviderModels.mockResolvedValue({ items: [{ model_ref: "recovered" }] });
    rerender({ selected: null });
    rerender({ selected: video });
    await waitFor(() => expect(result.current.models[0]?.model_ref).toBe("recovered"));
    expect(result.current.error).toBeNull();
    expect(api.listProviderModels).toHaveBeenCalledTimes(3);
  });

  it("does not load models for source-only media", () => {
    const selected = { ...node("source-only-video", "video"), execution_mode: "source_only" as const };
    const { result } = renderHook(() => useAgentCanvasProviderModels(null, selected));
    expect(result.current.loading).toBe(false);
    expect(api.listProviderModels).not.toHaveBeenCalled();
    expect(api.getModelDefaults).not.toHaveBeenCalled();
  });

  it("does not query a model catalog for an Editing node", async () => {
    const editing = node("editing-1", "editing");
    renderHook(() => useAgentCanvasProviderModels(workflowWith(editing), editing));

    await waitFor(() => expect(api.listProviderModels).not.toHaveBeenCalled());
  });

  it("keeps canonical catalog errors available to the inspector", async () => {
    api.listProviderModels.mockRejectedValue(new Error("Model catalog is unavailable."));
    const image = node("image-1", "image");

    const { result } = renderHook(() => useAgentCanvasProviderModels(workflowWith(image), image));

    await waitFor(() => expect(result.current.error).toBe("Model catalog is unavailable."));
  });

  it("keeps the model catalog available when only installation defaults fail", async () => {
    const catalogModel = { model_ref: "vendor:image-model" };
    api.listProviderModels.mockResolvedValue({ items: [catalogModel] });
    api.getModelDefaults.mockRejectedValue(new Error("Defaults are unavailable."));
    const image = node("image-1", "image");

    const { result } = renderHook(() => useAgentCanvasProviderModels(workflowWith(image), image));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.models).toEqual([catalogModel]);
    expect(result.current.defaultModelRef).toBeNull();
    expect(result.current.error).toBe("Default model could not be loaded.");
  });

  it.each([
    ["script", "vendor:text-default"],
    ["video", "vendor:video-default"],
  ] as const)("returns the installation default for a %s node", async (nodeType, expected) => {
    api.listProviderModels.mockResolvedValue({ items: [] });
    const selected = node(`${nodeType}-default`, nodeType);

    const { result } = renderHook(() => useAgentCanvasProviderModels(
      workflowWith(selected),
      selected,
    ));

    await waitFor(() => expect(result.current.defaultModelRef).toBe(expected));
  });
});
