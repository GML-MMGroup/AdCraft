import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ComposerContextTray } from "./ComposerContextTray.tsx";
import type { ComposerContextView } from "./composerContext.ts";

afterEach(cleanup);

const context: ComposerContextView = {
  skill: { title: "Quiet Product Film", summary: "Restrained product cinematography." },
  assets: [{
    assetId: "asset-1",
    displayName: "Hero bottle reference",
    mediaType: "image",
    thumbnailUrl: "/preview/asset-1",
  }],
  nodes: [{ nodeId: "node-1", title: "Product Main", nodeType: "image" }],
  uploadState: "idle",
};

function renderTray(view = context) {
  return render(
    <ComposerContextTray
      view={view}
      uploadIssue={null}
      onFocusNode={vi.fn()}
      onRemoveNode={vi.fn()}
      onRemoveAsset={vi.fn()}
      onClearUploadIssue={vi.fn()}
    />,
  );
}

describe("ComposerContextTray", () => {
  it("renders nothing for an empty idle context", () => {
    const { container } = renderTray({
      skill: null,
      assets: [],
      nodes: [],
      uploadState: "idle",
    });

    expect(container.firstChild).toBeNull();
  });

  it("summarizes context and expands it without exposing internal IDs", () => {
    renderTray();

    const toggle = screen.getByRole("button", { name: "Show message context" });
    expect(toggle.textContent).toContain("Skill · Quiet Product Film");
    expect(toggle.textContent).toContain("Assets · 1");
    expect(toggle.textContent).toContain("Nodes · 1");
    expect(screen.queryByText("Restrained product cinematography.")).toBeNull();

    fireEvent.click(toggle);
    expect(screen.getByText("Restrained product cinematography.")).toBeTruthy();
    expect(screen.getByText("Hero bottle reference")).toBeTruthy();
    expect(screen.getByText("Product Main")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/asset-1|node-1/);
  });

  it("focuses nodes and removes assets or nodes with separate controls", () => {
    const focus = vi.fn();
    const removeNode = vi.fn();
    const removeAsset = vi.fn();
    render(
      <ComposerContextTray
        view={context}
        uploadIssue={null}
        onFocusNode={focus}
        onRemoveNode={removeNode}
        onRemoveAsset={removeAsset}
        onClearUploadIssue={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show message context" }));
    fireEvent.click(screen.getByRole("button", { name: "Focus Product Main" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove Product Main" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove Hero bottle reference" }));

    expect(focus).toHaveBeenCalledWith("node-1");
    expect(removeNode).toHaveBeenCalledWith("node-1");
    expect(removeAsset).toHaveBeenCalledWith("asset-1");
  });

  it("shows uploading and upload failures inside the tray", () => {
    const { rerender } = render(
      <ComposerContextTray
        view={{ ...context, uploadState: "uploading" }}
        uploadIssue={null}
        onFocusNode={vi.fn()}
        onRemoveNode={vi.fn()}
        onRemoveAsset={vi.fn()}
        onClearUploadIssue={vi.fn()}
      />,
    );
    expect(screen.getByRole("status").textContent).toContain("Uploading");

    rerender(
      <ComposerContextTray
        view={{ ...context, uploadState: "failed" }}
        uploadIssue={{
          scope: "context",
          title: "Context could not be updated",
          message: "Your current message context was preserved.",
          technicalDetail: "upload_failed: Request failed with status 503",
          action: "retry",
        }}
        onFocusNode={vi.fn()}
        onRemoveNode={vi.fn()}
        onRemoveAsset={vi.fn()}
        onClearUploadIssue={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText("Context could not be updated")).toBeTruthy();
  });
});
