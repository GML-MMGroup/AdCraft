import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { ProductSourceDecisionDock } from "./ProductSourceDecisionDock.tsx";

const assets = vi.hoisted(() => ({
  uploadFilesWithReceipts: vi.fn(),
}));

vi.mock("../assets/useAgentCanvasAssets.ts", () => ({
  useAgentCanvasAssets: () => ({
    items: [],
    loading: false,
    error: null,
    uploading: false,
    uploadError: null,
    retry: vi.fn(),
    uploadFiles: vi.fn(),
    uploadFilesWithReceipts: assets.uploadFilesWithReceipts,
  }),
}));

const interaction: GuidedInteractionV1 = {
  interaction_id: "interaction-product-main-1",
  workflow_id: "workflow-1",
  session_id: "session-1",
  checkpoint_id: "checkpoint-1",
  kind: "product_source",
  status: "open",
  response_locale: "zh-CN",
  expected_session_revision: 7,
  revision: 3,
  title: "Choose the Product source",
  context: "Use the real Product or generate a visual source.",
  content: {
    content_kind: "product_source",
    input_kind: "main",
    question_id: "product_main_source",
    prompt: "Choose one Product main image.",
    expected_guidance_revision: 11,
    min_asset_count: 1,
    max_asset_count: 1,
  },
  allowed_actions: ["select_source"],
  submit_path: "/api/v2/workflows/workflow-1/chat/interactions/interaction-product-main-1/submit",
  created_at: "2026-08-27T08:00:00Z",
  updated_at: "2026-08-27T08:00:00Z",
};

describe("ProductSourceDecisionDock", () => {
  beforeEach(() => {
    assets.uploadFilesWithReceipts.mockReset();
    assets.uploadFilesWithReceipts.mockResolvedValue([{
      workflow_id: "workflow-1",
      asset: {
        asset_id: "asset-product-main",
        version_id: "version-product-main-1",
      },
      pending_handoff_id: "handoff-product-main-1",
    }]);
  });

  afterEach(cleanup);

  it("uploads one main Product source and submits the exact immutable handoff", async () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(
      <ProductSourceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        onSubmit={submit}
      />,
    );
    const file = new File(["product"], "product.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Upload Product source"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Use uploaded Product" }));

    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(assets.uploadFilesWithReceipts).toHaveBeenCalledWith(
      [file],
      { semanticRole: "product_main", metadata: { input_kind: "main" } },
      [expect.stringMatching(/^guided-product-upload-/)],
    );
    expect(submit).toHaveBeenCalledWith({
      submission_kind: "product_source",
      expected_interaction_revision: 3,
      expected_session_revision: 7,
      action: {
        input_kind: "main",
        choice: "upload",
        handoff_mode: "apply",
        asset_versions: [{ asset_id: "asset-product-main", version_id: "version-product-main-1" }],
        pending_handoff_id: "handoff-product-main-1",
        expected_guidance_revision: 11,
        question_id: "product_main_source",
      },
    });
  });

  it("submits Generate without upload identities", async () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(
      <ProductSourceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        onSubmit={submit}
      />,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Generate Product source" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate Product" }));

    await waitFor(() => expect(submit).toHaveBeenCalledWith({
      submission_kind: "product_source",
      expected_interaction_revision: 3,
      expected_session_revision: 7,
      action: {
        input_kind: "main",
        choice: "generate",
        handoff_mode: "apply",
        asset_versions: [],
        pending_handoff_id: null,
        expected_guidance_revision: 11,
        question_id: "product_main_source",
      },
    }));
    expect(assets.uploadFilesWithReceipts).not.toHaveBeenCalled();
  });

  it("requires the backend-provided multiview minimum before enabling Submit", () => {
    render(
      <ProductSourceDecisionDock
        interaction={{
          ...interaction,
          content: {
            ...interaction.content,
            input_kind: "multiview",
            min_asset_count: 2,
            max_asset_count: 8,
          },
        }}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );
    const file = new File(["one"], "one.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Upload Product sources"), {
      target: { files: [file] },
    });

    expect((screen.getByRole("button", { name: "Use uploaded Product" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getAllByText("1 of 2-8 images selected")).toHaveLength(2);
  });
});
