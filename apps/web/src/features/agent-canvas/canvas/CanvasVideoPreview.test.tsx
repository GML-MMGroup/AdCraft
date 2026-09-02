import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { CanvasVideoPreview } from "./CanvasVideoPreview.tsx";

vi.mock("./useAgentCanvasVideoPoster.ts", () => ({
  useAgentCanvasVideoPoster: vi.fn(() => null),
}));

function makeVideoAsset(): ProjectAssetSummaryV2 {
  return {
    asset_id: "video-asset",
    project_id: "project-1",
    workflow_id: "workflow-1",
    media_type: "video",
    source_type: "generated",
    display_name: "Campaign cut",
    mime_type: "video/mp4",
    status: "ready",
    size_bytes: 0,
    storage_key: null,
    preview_url: "/api/v2/assets/video-asset/poster?v=version-1",
    media_url: "/api/v2/assets/video-asset/content?v=version-1",
    width: 1920,
    height: 1080,
    duration_seconds: 15,
    checksum: "video-checksum",
    source_semantic_role: null,
    source_node_id: "video-node",
    source_execution_id: "execution-1",
    provider: null,
    model_id: null,
    prompt_provenance: {},
    quality_metadata: {},
    created_at: "2026-08-05T09:00:00Z",
  };
}

afterEach(() => {
  cleanup();
});

describe("CanvasVideoPreview", () => {
  it("renders the poster rendition directly in the canvas", () => {
    render(<CanvasVideoPreview asset={makeVideoAsset()} label="Video output" />);

    const image = screen.getByRole("img", { name: "Campaign cut" });

    expect(image.getAttribute("src")).toBe("/api/v2/assets/video-asset/poster?v=version-1");
    expect(image.getAttribute("loading")).toBe("eager");
    expect(image.getAttribute("decoding")).toBe("async");
    expect(image.getAttribute("draggable")).toBe("false");
  });
});
