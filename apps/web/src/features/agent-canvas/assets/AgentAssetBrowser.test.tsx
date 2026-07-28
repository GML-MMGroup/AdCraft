import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { AgentAssetBrowser } from "./AgentAssetBrowser.tsx";

const fixture = vi.hoisted(() => ({
  listAgentCanvasProjectAssets: vi.fn(),
  listAgentCanvasMyAssets: vi.fn(),
  listAgentCanvasRecommendedAssets: vi.fn(),
  uploadAgentCanvasAsset: vi.fn(),
}));

vi.mock("../../../api/v2Client.ts", () => ({
  v2Api: fixture,
}));

function projectAsset(
  assetId: string,
  mediaType: "image" | "video" | "audio",
): ProjectAssetSummaryV2 {
  return {
    asset_id: assetId,
    media_type: mediaType,
    source_type: "upload",
    display_name: `${mediaType} ${assetId}`,
    mime_type: mediaType === "image" ? "image/png" : `${mediaType}/mp4`,
    status: "ready",
    preview_url: mediaType === "image" ? `/media/${assetId}.png` : null,
    media_url: `/media/${assetId}`,
    width: mediaType === "audio" ? null : 1280,
    height: mediaType === "audio" ? null : 720,
    duration_seconds: mediaType === "image" ? null : 9,
    checksum: `${assetId}-checksum`,
  };
}

function libraryAsset(scope: "my" | "recommended", entityId: string) {
  return {
    entity_id: entityId,
    scope,
    entity_type: "character",
    library_category: "characters",
    display_name: `${scope} ${entityId}`,
    tags: ["portrait"],
    is_favorite: false,
    member_count: 1,
    preview_url: `/library/${entityId}.png`,
    preview_member: {
      member_id: `${entityId}-member`,
      semantic_type: "reference",
      asset_id: `${entityId}-asset`,
      version_id: `${entityId}-version`,
      media_type: "image",
      thumbnail_url: `/library/${entityId}.png`,
    },
  };
}

describe("AgentAssetBrowser", () => {
  beforeEach(() => {
    fixture.listAgentCanvasProjectAssets.mockReset();
    fixture.listAgentCanvasMyAssets.mockReset();
    fixture.listAgentCanvasRecommendedAssets.mockReset();
    fixture.uploadAgentCanvasAsset.mockReset();
    fixture.listAgentCanvasProjectAssets.mockResolvedValue({
      workflow_id: "workflow-1",
      assets: [
        projectAsset("image-a", "image"),
        projectAsset("image-b", "image"),
        projectAsset("video-a", "video"),
        projectAsset("audio-a", "audio"),
      ],
    });
    fixture.listAgentCanvasMyAssets.mockResolvedValue({
      items: [libraryAsset("my", "portrait")],
    });
    fixture.listAgentCanvasRecommendedAssets.mockResolvedValue({
      items: [libraryAsset("recommended", "scene")],
    });
  });

  afterEach(() => cleanup());

  it("offers three scopes, project media filters, search, and project-only upload", async () => {
    render(
      <AgentAssetBrowser
        workflowId="workflow-1"
        onAddReferences={vi.fn()}
        onCreateReadySourceNode={vi.fn()}
      />,
    );
    await screen.findByText("image image-a");

    expect(screen.getByRole("tab", { name: "Project Assets" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "My Assets" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Recommended" })).toBeTruthy();
    expect(screen.getByLabelText("Upload project media").getAttribute("accept"))
      .toBe("image/*,video/*,audio/*");

    fireEvent.click(screen.getByRole("button", { name: "Videos" }));
    expect(screen.getByText("video video-a")).toBeTruthy();
    expect(screen.queryByText("image image-a")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "All media" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search assets" }), {
      target: { value: "audio-a" },
    });
    expect(screen.getByText("audio audio-a")).toBeTruthy();
    expect(screen.queryByText("video video-a")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "My Assets" }));
    await screen.findByText("my portrait");
    expect(screen.queryByLabelText("Upload project media")).toBeNull();
    expect(screen.getByText("Images only")).toBeTruthy();
  });

  it("adds multiple image references with stable identities and does not generate", async () => {
    const onAddReferences = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentAssetBrowser
        workflowId="workflow-1"
        onAddReferences={onAddReferences}
        onCreateReadySourceNode={vi.fn()}
      />,
    );
    await screen.findByText("image image-a");

    fireEvent.click(within(screen.getByTestId("agent-asset-project:image-a")).getByRole("checkbox"));
    fireEvent.click(within(screen.getByTestId("agent-asset-project:image-b")).getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Add 2 references" }));

    await waitFor(() => expect(onAddReferences).toHaveBeenCalledOnce());
    expect(onAddReferences).toHaveBeenCalledWith([
      {
        source: "project",
        assetId: "image-a",
        entityId: null,
        versionId: null,
        mediaType: "image",
        displayName: "image image-a",
      },
      {
        source: "project",
        assetId: "image-b",
        entityId: null,
        versionId: null,
        mediaType: "image",
        displayName: "image image-b",
      },
    ]);
    expect(fixture).not.toHaveProperty("generate");
  });

  it("passes My and Recommended stable asset identities without blobs or base64", async () => {
    const onAddReferences = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentAssetBrowser
        workflowId="workflow-1"
        onAddReferences={onAddReferences}
        onCreateReadySourceNode={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Recommended" }));
    await screen.findByText("recommended scene");
    fireEvent.click(screen.getByRole("checkbox", { name: "Select recommended scene" }));
    fireEvent.click(screen.getByRole("button", { name: "Add 1 reference" }));

    await waitFor(() => expect(onAddReferences).toHaveBeenCalledOnce());
    const selection = onAddReferences.mock.calls[0]?.[0]?.[0];
    expect(selection).toEqual({
      source: "recommended",
      assetId: "scene-asset",
      entityId: "scene",
      versionId: "scene-version",
      mediaType: "image",
      displayName: "recommended scene",
    });
    expect(JSON.stringify(selection)).not.toMatch(/base64|data:/i);
  });

  it("creates Ready source-backed nodes from project video and audio through a callback", async () => {
    const onCreateReadySourceNode = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentAssetBrowser
        workflowId="workflow-1"
        onAddReferences={vi.fn()}
        onCreateReadySourceNode={onCreateReadySourceNode}
      />,
    );
    await screen.findByText("video video-a");

    fireEvent.click(screen.getByRole("button", { name: "Create Ready video node from video video-a" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Ready audio node from audio audio-a" }));

    await waitFor(() => expect(onCreateReadySourceNode).toHaveBeenCalledTimes(2));
    expect(onCreateReadySourceNode.mock.calls.map((call) => call[0])).toEqual([
      expect.objectContaining({
        source: "project",
        assetId: "video-a",
        mediaType: "video",
      }),
      expect.objectContaining({
        source: "project",
        assetId: "audio-a",
        mediaType: "audio",
      }),
    ]);
  });

  it("shows empty, error, and retry states without leaking the old asset library UI", async () => {
    fixture.listAgentCanvasProjectAssets
      .mockRejectedValueOnce(new Error("Could not load project assets"))
      .mockResolvedValueOnce({ workflow_id: "workflow-1", assets: [] });
    render(
      <AgentAssetBrowser
        workflowId="workflow-1"
        onAddReferences={vi.fn()}
        onCreateReadySourceNode={vi.fn()}
      />,
    );

    expect((await screen.findByRole("alert")).textContent).toContain("Could not load project assets");
    fireEvent.click(screen.getByRole("button", { name: "Retry loading assets" }));

    expect(await screen.findByText("No project assets yet")).toBeTruthy();
    expect(screen.queryByText(/Slot|Asset Library/i)).toBeNull();
  });
});
