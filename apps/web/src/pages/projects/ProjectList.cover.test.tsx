import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectList, __resetProjectCoverResourceForTests, type ProjectListItem } from "./ProjectList.tsx";
import { saveProjectCoverCache } from "../../projects/projectCoverCache.ts";

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
    window.localStorage.clear();
    __resetProjectCoverResourceForTests();
    fixture.agentCanvasWorkflowWithEtag.mockResolvedValue({ value: { nodes: [] }, etag: '"workflow-r1"' });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("keeps cover work bounded to the mounted virtual window", async () => {
    const controlled = installControlledCoverRequests();
    const view = render(
      <ProjectList
        projects={projects(100)}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    await act(async () => {});
    expect(view.container.querySelectorAll(".project-card").length).toBe(16);
    expect(controlled.requests.map((request) => request.workflowId)).toEqual([
      "workflow-0", "workflow-1", "workflow-2", "workflow-3",
    ]);
    expect(controlled.active()).toBe(4);
    expect(controlled.maxActive()).toBe(4);
    expect(view.container.querySelector("[data-project-list-virtualized=\"true\"]")).toBeTruthy();
  });

  it("cancels pending cover requests before opening a project", async () => {
    const controlled = installControlledCoverRequests();
    const onOpenProject = vi.fn();
    const view = render(
      <ProjectList
        projects={projects(5)}
        onOpenProject={onOpenProject}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    await act(async () => {});
    fireEvent.click(view.container.querySelector('[data-project-id="project-0"] .project-card-open') as HTMLElement);

    expect(controlled.aborted).toEqual([
      "workflow-0", "workflow-1", "workflow-2", "workflow-3",
    ]);
    expect(onOpenProject).toHaveBeenCalledWith("project-0", "workflow-0");
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

    await act(async () => {});
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

  it("does not restart a cover request when the project object is recreated unchanged", async () => {
    const controlled = installControlledCoverRequests();
    const initial = projects(1);
    const onOpenProject = vi.fn();
    const onTrashProject = vi.fn();
    const onToggleFavorite = vi.fn();
    const onRenameProject = vi.fn();
    const view = render(
      <ProjectList
        projects={initial}
        onOpenProject={onOpenProject}
        onTrashProject={onTrashProject}
        onToggleFavorite={onToggleFavorite}
        onRenameProject={onRenameProject}
      />,
    );

    await act(async () => {});
    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledTimes(1);

    view.rerender(
      <ProjectList
        projects={[{ ...initial[0] }]}
        onOpenProject={onOpenProject}
        onTrashProject={onTrashProject}
        onToggleFavorite={onToggleFavorite}
        onRenameProject={onRenameProject}
      />,
    );
    await act(async () => {});

    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledTimes(1);
    controlled.resolve("workflow-0");
  });

  it("does not restart cover metadata when only the virtual-row priority changes", async () => {
    const controlled = installControlledCoverRequests();
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback: FrameRequestCallback) => {
      callback(0);
      return 0;
    });
    const view = render(
      <ProjectList
        projects={projects(20)}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    await act(async () => {});
    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledTimes(4);

    const list = view.container.querySelector("[data-project-list-virtualized]");
    if (!list) throw new Error("Expected virtualized project list.");
    Object.defineProperty(list, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ top: -window.scrollY, left: 0, width: 1024, height: 4000 }),
    });
    Object.defineProperty(window, "scrollY", { configurable: true, value: 308 });
    fireEvent.scroll(window);
    await act(async () => {});

    expect(view.container.querySelector(".project-list-virtual__window")?.getAttribute("style")).toContain("translateY(0px)");
    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledTimes(4);
    expect(controlled.aborted).toEqual([]);
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
    await act(async () => {});
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
    await act(async () => {});
    expect(obsoleteRequest?.signal.aborted).toBe(true);
    expect(controlled.aborted).toEqual(["workflow-0"]);
    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledTimes(2);

    await act(async () => {
      controlled.resolve("workflow-0", [coverAsset("fresh", "/media/fresh.webp")]);
    });
    expect((view.container.querySelector(".project-preview-image img") as HTMLImageElement).src).toContain("/api/v2/assets/fresh/content?v=fresh-version");
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

    await act(async () => {});
    await act(async () => {
      controlled.resolve("workflow-0", [coverAsset("product-cover", "/api/v2/assets/product-cover/content")]);
    });

    const image = view.container.querySelector(".project-preview-image img") as HTMLImageElement;
    expect(image.src).toContain("/api/v2/assets/product-cover/content?v=product-cover-version");
    expect(image.src).not.toContain("/media/api/v2/");
    expect(image.getAttribute("loading")).toBe("eager");
    expect(image.getAttribute("fetchpriority")).toBe("high");
  });

  it("does not request project assets when the summary already contains a versioned cover", async () => {
    const project = {
      ...projects(1)[0],
      coverState: "ready" as const,
      cover: {
        assetId: "summary-cover",
        versionId: "summary-version",
        mediaType: "image" as const,
        mediaPath: "/api/v2/assets/summary-cover/preview?v=summary-version",
        posterPath: null,
      },
    };
    const view = render(
      <ProjectList
        projects={[project]}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    await act(async () => {});
    expect(fixture.listAgentCanvasProjectAssets).not.toHaveBeenCalled();
    expect((view.container.querySelector(".project-preview-image img") as HTMLImageElement).src)
      .toContain("/api/v2/assets/summary-cover/preview?v=summary-version");
  });

  it("falls back to workflow assets when the project summary cover is null", async () => {
    const controlled = installControlledCoverRequests();
    const project = { ...projects(1)[0], cover: null };
    const view = render(
      <ProjectList
        projects={[project]}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    await act(async () => {});
    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledWith("workflow-0", {
      signal: expect.any(AbortSignal),
    });

    await act(async () => {
      controlled.resolve("workflow-0", [coverAsset("historical-cover", "/media/historical.webp")]);
    });
    expect((view.container.querySelector(".project-preview-image img") as HTMLImageElement).src)
      .toContain("/api/v2/assets/historical-cover/content?v=historical-cover-version");
  });

  it("falls back to workflow assets when cover authority is unresolved", async () => {
    const controlled = installControlledCoverRequests();
    const project = { ...projects(1)[0], cover: null, coverState: "unresolved" as const };
    render(
      <ProjectList
        projects={[project]}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    await act(async () => {});
    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledTimes(1);
    controlled.resolve("workflow-0");
  });

  it.each(["none", "broken"] as const)(
    "does not infer a cover when backend authority is %s",
    async (coverState) => {
      const project = { ...projects(1)[0], cover: null, coverState };
      render(
        <ProjectList
          projects={[project]}
          onOpenProject={vi.fn()}
          onTrashProject={vi.fn()}
          onToggleFavorite={vi.fn()}
          onRenameProject={vi.fn()}
        />,
      );

      await act(async () => {});
      expect(fixture.listAgentCanvasProjectAssets).not.toHaveBeenCalled();
    },
  );

  it("shows a persisted cover while the background refresh is pending", async () => {
    const controlled = installControlledCoverRequests();
    const project = projects(1)[0];
    if (!project) throw new Error("Expected a project fixture.");
    saveProjectCoverCache(`project:${project.projectId}`, {
      assetId: "cached-cover",
      versionId: "cached-cover-version",
      mediaType: "image",
      mediaPath: "/api/v2/assets/cached-cover/content?v=cached-cover-version",
      posterPath: null,
    });

    const view = render(
      <ProjectList
        projects={[project]}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    await act(async () => {});
    expect((view.container.querySelector(".project-preview-image img") as HTMLImageElement).src)
      .toContain("cached-cover/content?v=cached-cover-version");
    expect(controlled.active()).toBe(1);
  });

  it("keeps the previously resolved cover visible while a refresh is pending", async () => {
    const controlled = installControlledCoverRequests();
    const initial = projects(1)[0];
    if (!initial) throw new Error("Expected a project fixture.");
    const callbacks = {
      onOpenProject: vi.fn(),
      onTrashProject: vi.fn(),
      onToggleFavorite: vi.fn(),
      onRenameProject: vi.fn(),
    };
    const view = render(<ProjectList projects={[initial]} {...callbacks} />);

    await act(async () => {
      controlled.resolve("workflow-0", [coverAsset("first-cover", "/api/v2/assets/first-cover/content")]);
    });
    await waitFor(() => {
      expect((view.container.querySelector(".project-preview-image img") as HTMLImageElement).src)
        .toContain("first-cover/content?v=first-cover-version");
    });

    view.rerender(<ProjectList projects={[{ ...initial, updatedAt: "2026-07-25T08:00:00Z" }]} {...callbacks} />);
    await act(async () => {});

    expect(controlled.active()).toBe(1);
    expect((view.container.querySelector(".project-preview-image img") as HTMLImageElement).src)
      .toContain("first-cover/content?v=first-cover-version");
  });

  it("loads source node authority when product assets have ambiguous public roles", async () => {
    const controlled = installControlledCoverRequests();
    let resolveAuthority: ((value: unknown) => void) | undefined;
    fixture.agentCanvasWorkflowWithEtag.mockImplementationOnce(() => new Promise((resolve) => {
      resolveAuthority = resolve;
    }));
    const view = render(
      <ProjectList
        projects={projects(1)}
        onOpenProject={vi.fn()}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    await act(async () => {});
    await act(async () => {
      controlled.resolve("workflow-0", [
        coverAsset("known-product-main", "/api/v2/assets/known-product-main/content"),
        coarseProductAsset("product-main", "product-main-node", ["reference-version"]),
        coarseProductAsset("product-multiview", "product-multiview-node", ["product-main-version"]),
      ]);
    });

    await waitFor(() => {
      expect((view.container.querySelector(".project-preview-image img") as HTMLImageElement).src).toContain("known-product-main/content");
    });
    expect(fixture.agentCanvasWorkflowWithEtag).toHaveBeenCalledWith("workflow-0", {
      signal: expect.any(AbortSignal),
    });

    await act(async () => {
      resolveAuthority?.({
        value: {
          nodes: [
            { node_id: "product-main-node", metadata: { prompt_recipe_id: "adcraft.agent_canvas.product_main" } },
            { node_id: "product-multiview-node", metadata: { prompt_recipe_id: "adcraft.agent_canvas.product_multiview" } },
          ],
        },
        etag: '"workflow-r1"',
      });
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

    await act(async () => {});
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
    await act(async () => {});

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
