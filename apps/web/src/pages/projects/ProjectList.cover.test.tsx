import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectList, __resetProjectCoverResourceForTests, type ProjectListItem } from "./ProjectList.tsx";

const fixture = vi.hoisted(() => ({ listWorkflowAssets: vi.fn() }));

vi.mock("../../api/v2Client.ts", () => ({
  v2Api: { listWorkflowAssets: fixture.listWorkflowAssets },
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

describe("ProjectList covers", () => {
  beforeEach(() => {
    vi.stubGlobal("IntersectionObserver", TestIntersectionObserver);
    TestIntersectionObserver.instances = [];
    __resetProjectCoverResourceForTests();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("waits for visibility and starts no more than four shared cover requests", async () => {
    const resolvers: Array<() => void> = [];
    fixture.listWorkflowAssets.mockImplementation(() => new Promise((resolve) => {
      resolvers.push(() => resolve({ assets: [] }));
    }));
    render(
      <ProjectList
        projects={projects(5)}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    expect(fixture.listWorkflowAssets).not.toHaveBeenCalled();
    await act(async () => { TestIntersectionObserver.revealAll(); });
    expect(fixture.listWorkflowAssets).toHaveBeenCalledTimes(4);

    await act(async () => { resolvers.shift()?.(); });
    expect(fixture.listWorkflowAssets).toHaveBeenCalledTimes(5);
  });

  it("does not let an obsolete card response replace the current cover", async () => {
    let resolveOld: ((value: { assets: unknown[] }) => void) | undefined;
    let resolveFresh: ((value: { assets: unknown[] }) => void) | undefined;
    fixture.listWorkflowAssets
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFresh = resolve; }));
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
    await act(async () => {
      resolveFresh?.({ assets: [coverAsset("fresh", "/media/fresh.webp")] });
    });
    expect((view.container.querySelector(".project-preview-image img") as HTMLImageElement).src).toContain("fresh.webp");

    await act(async () => {
      resolveOld?.({ assets: [coverAsset("old", "/media/old.webp")] });
    });
    expect((view.container.querySelector(".project-preview-image img") as HTMLImageElement).src).toContain("fresh.webp");
  });

  it("drops queued covers on unmount so a new page gets queue slots", async () => {
    const started: string[] = [];
    fixture.listWorkflowAssets.mockImplementation((workflowId: string, _filters: unknown, options?: { signal?: AbortSignal }) => {
      started.push(workflowId);
      return new Promise((_, reject) => {
        options?.signal?.addEventListener("abort", () => reject(abortError()), { once: true });
      });
    });
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
    expect(started).toEqual(["workflow-0", "workflow-1", "workflow-2", "workflow-3"]);

    oldPage.unmount();
    await act(async () => {});
    expect(started).toHaveLength(4);

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

    expect(started).toEqual([
      "workflow-0", "workflow-1", "workflow-2", "workflow-3",
      "new-workflow-0", "new-workflow-1",
    ]);
  });
});

function coverAsset(assetId: string, publicUrl: string) {
  return {
    asset_id: assetId,
    version_id: `${assetId}-version`,
    media_type: "image",
    public_url: publicUrl,
    state: "selected",
    status: "ready",
    source_type: "generated",
    node_id: "product",
    semantic_type: "product_main",
  };
}
