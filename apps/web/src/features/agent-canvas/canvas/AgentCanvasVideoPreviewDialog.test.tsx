import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { AgentCanvasVideoPreviewDialog } from "./AgentCanvasVideoPreviewDialog.tsx";

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
    preview_url: "/media/campaign-poster.webp",
    media_url: "/media/campaign-cut.mp4",
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

afterEach(() => cleanup());

describe("AgentCanvasVideoPreviewDialog", () => {
  it("renders the generated video in a modal native player without cropping it", () => {
    render(
      <AgentCanvasVideoPreviewDialog
        asset={makeVideoAsset()}
        title="Campaign video"
        onClose={vi.fn()}
      />,
    );

    const dialog = screen.getByRole("dialog", { name: "Campaign video" });
    const player = screen.getByLabelText("Campaign video player");

    expect(document.body.contains(dialog)).toBe(true);
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(player.tagName).toBe("VIDEO");
    expect(player.getAttribute("src")).toBe("/media/campaign-cut.mp4");
    expect(player.getAttribute("poster")).toBe("/media/campaign-poster.webp");
    expect(player.hasAttribute("controls")).toBe(true);
    expect(player.hasAttribute("autoplay")).toBe(true);
    expect(player.classList).toContain("agent-canvas-video-preview__player");
  });

  it("closes from the close control and Escape key", () => {
    const onClose = vi.fn();
    const view = render(
      <AgentCanvasVideoPreviewDialog
        asset={makeVideoAsset()}
        title="Campaign video"
        onClose={onClose}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Close video preview" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    view.rerender(
      <AgentCanvasVideoPreviewDialog
        asset={makeVideoAsset()}
        title="Campaign video"
        onClose={onClose}
      />,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("opens as a native modal and restores focus to the launch control on unmount", () => {
    const launchControl = document.createElement("button");
    launchControl.textContent = "Launch preview";
    document.body.append(launchControl);
    launchControl.focus();
    const showModal = vi.fn(function showModalMock(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    });
    const originalShowModal = HTMLDialogElement.prototype.showModal;
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
      configurable: true,
      value: showModal,
    });

    try {
      const view = render(
        <AgentCanvasVideoPreviewDialog
          asset={makeVideoAsset()}
          title="Campaign video"
          onClose={vi.fn()}
        />,
      );

      expect(showModal).toHaveBeenCalledTimes(1);
      view.unmount();
      expect(document.activeElement).toBe(launchControl);
    } finally {
      if (originalShowModal) {
        Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
          configurable: true,
          value: originalShowModal,
        });
      } else {
        delete HTMLDialogElement.prototype.showModal;
      }
      launchControl.remove();
    }
  });
});
