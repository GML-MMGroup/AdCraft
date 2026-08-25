import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectList, __resetProjectCoverResourceForTests, type ProjectListItem } from "./ProjectList.tsx";

const fixture = vi.hoisted(() => ({
  agentCanvasWorkflowWithEtag: vi.fn(),
  listAgentCanvasProjectAssets: vi.fn(),
}));

vi.mock("../../api/agentCanvasApi.ts", () => ({
  agentCanvasApi: {
    agentCanvasWorkflowWithEtag: fixture.agentCanvasWorkflowWithEtag,
    listAgentCanvasProjectAssets: fixture.listAgentCanvasProjectAssets,
  },
}));

class TestIntersectionObserver {
  static instances: TestIntersectionObserver[] = [];
  readonly elements = new Set<Element>();

  constructor(private readonly callback: IntersectionObserverCallback) {
    TestIntersectionObserver.instances.push(this);
  }

  observe(element: Element) { this.elements.add(element); }
  unobserve(element: Element) { this.elements.delete(element); }
  disconnect() { this.elements.clear(); }
  takeRecords(): IntersectionObserverEntry[] { return []; }

  static revealAll() {
    for (const observer of TestIntersectionObserver.instances) {
      observer.callback([...observer.elements].map((target) => ({ isIntersecting: true, target }) as IntersectionObserverEntry), observer as unknown as IntersectionObserver);
    }
  }
}

function projects(count: number): ProjectListItem[] {
  return Array.from({ length: count }, (_, index) => ({
    key: `project-${index}`,
    source: "saved",
    projectId: `project-${index}`,
    name: `Project ${index}`,
    time: "Updated today",
    updatedAt: "2026-07-24T08:00:00Z",
    favorite: false,
    workflowId: `workflow-${index}`,
    coverAssetId: null,
  }));
}

function abortError() {
  const error = new Error("Request aborted");
  error.name = "AbortError";
  return error;
}

function installControlledCoverRequests() {
  type Request = {
    workflowId: string;
    signal: AbortSignal;
    settled: boolean;
    resolve: (assets?: unknown[]) => void;
  };

  const requests: Request[] = [];
  const aborted: string[] = [];
  let active = 0;
  let maxActive = 0;

  fixture.listAgentCanvasProjectAssets.mockImplementation((
    workflowId: string,
    options?: { signal?: AbortSignal },
  ) => new Promise((resolve, reject) => {
    if (!options?.signal) {
      reject(new Error("Expected cover request to receive an AbortSignal"));
      return;
    }

    active += 1;
    maxActive = Math.max(maxActive, active);
    const request: Request = {
      workflowId,
      signal: options.signal,
      settled: false,
      resolve: (assets = []) => {
        if (request.settled) return;
        request.settled = true;
        active -= 1;
        request.signal.removeEventListener("abort", onAbort);
        resolve({ assets });
      },
    };
    const onAbort = () => {
      if (request.settled) return;
      request.settled = true;
      active -= 1;
      aborted.push(workflowId);
      reject(abortError());
    };
    options.signal.addEventListener("abort", onAbort, { once: true });
    requests.push(request);
  }));

  return {
    requests,
    aborted,
    active: () => active,
    maxActive: () => maxActive,
    resolve(workflowId: string, assets: unknown[] = []) {
      const request = requests.find((candidate) => candidate.workflowId === workflowId && !candidate.settled);
      if (!request) throw new Error(`No pending request for ${workflowId}`);
      request.resolve(assets);
    },
  };
}

describe("ProjectList covers", () => {
  beforeEach(() => {
    vi.stubGlobal("IntersectionObserver", TestIntersectionObserver);
    TestIntersectionObserver.instances = [];
    __resetProjectCoverResourceForTests();
    fixture.agentCanvasWorkflowWithEtag.mockResolvedValue({ value: { nodes: [] }, etag: '"workflow-r1"' });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("completing one cover does not abort or restart sibling jobs", async () => {
    const controlled = installControlledCoverRequests();
    render(
      <ProjectList
        projects={projects(5)}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    expect(fixture.listAgentCanvasProjectAssets).not.toHaveBeenCalled();
    await act(async () => { TestIntersectionObserver.revealAll(); });
    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledTimes(4);
    expect(controlled.active()).toBe(4);
    expect(controlled.maxActive()).toBe(4);

    await act(async () => { controlled.resolve("workflow-0"); });
    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledTimes(5);
    expect(controlled.aborted).toEqual([]);
    expect(controlled.active()).toBe(4);
    expect(controlled.maxActive()).toBe(4);
    for (let index = 0; index < 5; index += 1) {
      expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledWith(`workflow-${index}`, {
        signal: expect.any(AbortSignal),
      });
    }

    await act(async () => {
      for (let index = 1; index < 5; index += 1) controlled.resolve(`workflow-${index}`);
    });
    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledTimes(5);
    expect(controlled.aborted).toEqual([]);
    expect(controlled.active()).toBe(0);
    expect(controlled.maxActive()).toBe(4);
  });

  it("aborts an obsolete project identity and keeps the fresh cover", async () => {
    const controlled = installControlledCoverRequests();
    const initial = projects(1);
    const view = render(
      <ProjectList
        projects={initial}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );
    await act(async () => { TestIntersectionObserver.revealAll(); });
    const obsoleteRequest = controlled.requests[0];

    view.rerender(
      <ProjectList
        projects={[{ ...initial[0], updatedAt: "2026-07-25T08:00:00Z" }]}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );
    await act(async () => { TestIntersectionObserver.revealAll(); });
    expect(obsoleteRequest.signal.aborted).toBe(true);
    expect(controlled.aborted).toEqual(["workflow-0"]);
    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledTimes(2);

    await act(async () => {
      controlled.resolve("workflow-0", [coverAsset("fresh", "/media/fresh.webp")]);
    });
    expect((view.container.querySelector(".project-preview-image img") as HTMLImageElement).src).toContain("fresh.webp");
  });

  it("renders canonical V2 asset content URLs without a legacy media prefix", async () => {
    const controlled = installControlledCoverRequests();
    const view = render(
      <ProjectList
        projects={projects(1)}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    await act(async () => { TestIntersectionObserver.revealAll(); });
    await act(async () => {
      controlled.resolve("workflow-0", [coverAsset("product-cover", "/api/v2/assets/product-cover/content")]);
    });

    const image = view.container.querySelector(".project-preview-image img") as HTMLImageElement;
    expect(image.src).toContain("/api/v2/assets/product-cover/content?v=product-cover-version");
    expect(image.src).not.toContain("/media/api/v2/");
  });

  it("loads source node authority when product assets have ambiguous public roles", async () => {
    const controlled = installControlledCoverRequests();
    fixture.agentCanvasWorkflowWithEtag.mockResolvedValueOnce({
      value: {
        nodes: [
          { node_id: "product-main-node", metadata: { prompt_recipe_id: "adcraft.agent_canvas.product_main" } },
          { node_id: "product-multiview-node", metadata: { prompt_recipe_id: "adcraft.agent_canvas.product_multiview" } },
        ],
      },
      etag: '"workflow-r1"',
    });
    const view = render(
      <ProjectList
        projects={projects(1)}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    await act(async () => { TestIntersectionObserver.revealAll(); });
    await act(async () => {
      controlled.resolve("workflow-0", [
        coarseProductAsset("product-main", "product-main-node", ["reference-version"]),
        coarseProductAsset("product-multiview", "product-multiview-node", ["product-main-version"]),
      ]);
    });

    await waitFor(() => {
      expect((view.container.querySelector(".project-preview-image img") as HTMLImageElement).src).toContain("product-main/content");
    });
    expect(fixture.agentCanvasWorkflowWithEtag).toHaveBeenCalledWith("workflow-0", {
      signal: expect.any(AbortSignal),
    });
  });

  it("drops queued covers on unmount so a new page gets queue slots", async () => {
    const controlled = installControlledCoverRequests();
    const oldPage = render(
      <ProjectList
        projects={projects(6)}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    await act(async () => { TestIntersectionObserver.revealAll(); });
    expect(controlled.requests.map((request) => request.workflowId)).toEqual([
      "workflow-0", "workflow-1", "workflow-2", "workflow-3",
    ]);

    oldPage.unmount();
    await act(async () => {});
    expect(controlled.requests.every((request) => request.signal.aborted)).toBe(true);
    expect(controlled.aborted).toEqual(["workflow-0", "workflow-1", "workflow-2", "workflow-3"]);
    expect(controlled.active()).toBe(0);
    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledTimes(4);

    render(
      <ProjectList
        projects={projects(2).map((project) => ({ ...project, projectId: `new-${project.projectId}`, workflowId: `new-${project.workflowId}` }))}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );
    await act(async () => { TestIntersectionObserver.revealAll(); });

    expect(controlled.requests.map((request) => request.workflowId)).toEqual([
      "workflow-0", "workflow-1", "workflow-2", "workflow-3",
      "new-workflow-0", "new-workflow-1",
    ]);
    expect(controlled.active()).toBe(2);
    expect(controlled.maxActive()).toBe(4);
  });
});

function coverAsset(assetId: string, publicUrl: string) {
  return {
    asset_id: assetId,
    version_id: `${assetId}-version`,
    media_type: "image",
    media_url: publicUrl,
    preview_url: publicUrl,
    status: "ready",
    source_type: "generated",
    semantic_type: "product",
    source_semantic_role: "product_main",
    generation_provenance: { source_asset_version_ids: [] },
  };
}

function coarseProductAsset(assetId: string, sourceNodeId: string, sourceAssetVersionIds: string[]) {
  return {
    ...coverAsset(assetId, `/api/v2/assets/${assetId}/content`),
    source_semantic_role: "product",
    source_node_id: sourceNodeId,
    generation_provenance: { source_asset_version_ids: sourceAssetVersionIds },
  };
}
