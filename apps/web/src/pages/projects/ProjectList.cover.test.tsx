import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectList, type ProjectListItem } from "./ProjectList.tsx";

const fixture = vi.hoisted(() => ({
  agentCanvasWorkflowWithEtag: vi.fn(),
  listAgentCanvasProjectAssets: vi.fn(),
}));

vi.mock("../../api/agentCanvasApi.ts", () => ({
  agentCanvasApi: fixture,
}));

function projects(count: number): ProjectListItem[] {
  return Array.from({ length: count }, (_, index) => ({
    key: `project-${index}`,
    source: "saved",
    projectId: `project-${index}`,
    name: `Project ${index}`,
    time: "Updated today",
    updatedAt: "2026-09-03T00:00:00Z",
    favorite: false,
    workflowId: `workflow-${index}`,
    coverAssetId: null,
    coverVersionId: null,
    coverState: "unresolved",
    cover: null,
  }));
}

describe("ProjectList authoritative covers", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("keeps the project grid virtualized without starting per-workflow cover discovery", async () => {
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

    expect(view.container.querySelectorAll(".project-card")).toHaveLength(16);
    expect(view.container.querySelector('[data-project-list-virtualized="true"]')).toBeTruthy();
    expect(fixture.listAgentCanvasProjectAssets).not.toHaveBeenCalled();
    expect(fixture.agentCanvasWorkflowWithEtag).not.toHaveBeenCalled();
  });

  it("opens a project immediately from its catalog identity", () => {
    const onOpenProject = vi.fn();
    const view = render(
      <ProjectList
        projects={projects(1)}
        onOpenProject={onOpenProject}
        onTrashProject={vi.fn()}
        onToggleFavorite={vi.fn()}
        onRenameProject={vi.fn()}
      />,
    );

    fireEvent.click(view.container.querySelector(".project-card-open") as HTMLElement);

    expect(onOpenProject).toHaveBeenCalledWith("project-0", "workflow-0");
    expect(fixture.listAgentCanvasProjectAssets).not.toHaveBeenCalled();
  });

  it("renders the exact versioned preview returned by the project summary", async () => {
    const project: ProjectListItem = {
      ...projects(1)[0],
      coverAssetId: "cover-asset",
      coverVersionId: "cover-version",
      coverState: "ready",
      cover: {
        assetId: "cover-asset",
        versionId: "cover-version",
        mediaType: "image",
        mediaPath: "/api/v2/assets/cover-asset/content?v=cover-version",
        previewPath: "/api/v2/assets/cover-asset/preview?v=cover-version&size=320",
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

    const image = view.container.querySelector(".project-preview-image img") as HTMLImageElement;
    expect(image.src).toContain("/api/v2/assets/cover-asset/preview?v=cover-version&size=320");
    expect(image.getAttribute("loading")).toBe("eager");
    expect(image.getAttribute("fetchpriority")).toBe("high");
    expect(fixture.listAgentCanvasProjectAssets).not.toHaveBeenCalled();
  });

  it.each([undefined, "none", "broken", "unresolved"] as const)(
    "shows an empty preview without guessing a cover when authority state is %s",
    async (coverState) => {
      const project: ProjectListItem = {
        ...projects(1)[0],
        coverState,
        cover: null,
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

      expect(view.container.querySelector(".project-preview-image.is-empty")).toBeTruthy();
      expect(view.container.querySelector(".project-preview-image img")).toBeNull();
      expect(fixture.listAgentCanvasProjectAssets).not.toHaveBeenCalled();
      expect(fixture.agentCanvasWorkflowWithEtag).not.toHaveBeenCalled();
    },
  );

  it.each([undefined, "none", "broken", "unresolved"] as const)(
    "ignores a stale cover payload when authority state is %s",
    async (coverState) => {
      const project: ProjectListItem = {
        ...projects(1)[0],
        coverState,
        cover: {
          assetId: "stale-cover",
          versionId: "stale-version",
          mediaType: "image",
          mediaPath: "/api/v2/assets/stale-cover/preview?v=stale-version&size=320",
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

      expect(view.container.querySelector(".project-preview-image img")).toBeNull();
    },
  );

  it("does not revive a stale guessed cover from the retired local cache", async () => {
    window.localStorage.setItem("adcraft-project-cover-cache-v1", JSON.stringify({
      "project:project-0": {
        savedAt: Date.now(),
        cover: {
          assetId: "guessed-cover",
          versionId: "guessed-version",
          mediaType: "image",
          mediaPath: "/api/v2/assets/guessed-cover/content?v=guessed-version",
          posterPath: null,
        },
      },
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

    expect(view.container.querySelector(".project-preview-image img")).toBeNull();
    expect(fixture.listAgentCanvasProjectAssets).not.toHaveBeenCalled();
  });
});
