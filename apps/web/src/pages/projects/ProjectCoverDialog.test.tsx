import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectCoverDialog } from "./ProjectCoverDialog.tsx";

vi.mock("../../features/agent-canvas/assets/useAgentCanvasAssets.ts", () => ({
  useAgentCanvasAssets: () => ({
    items: [{
      id: "project:asset-2",
      assetId: "asset-2",
      source: "project",
      mediaType: "image",
      displayName: "Product Main",
      previewUrl: "/api/v2/assets/asset-2/preview?v=version-2",
      mediaUrl: "/api/v2/assets/asset-2/content?v=version-2",
      status: "ready",
      tags: [],
      identity: { source: "project", assetId: "asset-2", entityId: null, versionId: "version-2" },
      projectAsset: null,
    }],
    loading: false,
    error: null,
    uploading: false,
    uploadError: null,
    retry: vi.fn(),
    uploadFiles: vi.fn(),
    uploadFilesWithReceipts: vi.fn(),
  }),
}));

const project = {
  key: "project-1",
  source: "saved" as const,
  projectId: "project-1",
  name: "Curtain campaign",
  time: "Today",
  updatedAt: "2026-08-31T00:00:00Z",
  favorite: false,
  workflowId: "workflow-1",
  coverAssetId: "asset-1",
  coverVersionId: "version-1",
  coverState: "ready" as const,
  cover: {
    assetId: "asset-1",
    versionId: "version-1",
    mediaType: "image" as const,
    mediaPath: "/api/v2/assets/asset-1/content?v=version-1",
    posterPath: null,
  },
};

describe("ProjectCoverDialog", () => {
  afterEach(cleanup);

  it("submits the exact selected asset version", async () => {
    const onUpdateCover = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(<ProjectCoverDialog project={project} onClose={onClose} onUpdateCover={onUpdateCover} />);

    fireEvent.click(screen.getByRole("option", { name: "Product Main" }));
    fireEvent.click(screen.getByRole("button", { name: /Save cover/i }));

    await waitFor(() => expect(onUpdateCover).toHaveBeenCalledWith("project-1", {
      assetId: "asset-2",
      versionId: "version-2",
    }));
    expect(onClose).toHaveBeenCalled();
  });

  it("submits null identities when clearing the current cover", async () => {
    const onUpdateCover = vi.fn().mockResolvedValue(undefined);
    render(<ProjectCoverDialog project={project} onClose={vi.fn()} onUpdateCover={onUpdateCover} />);

    fireEvent.click(screen.getByRole("button", { name: "Clear cover" }));
    fireEvent.click(screen.getByRole("button", { name: /Save cover/i }));

    await waitFor(() => expect(onUpdateCover).toHaveBeenCalledWith("project-1", null));
  });
});
