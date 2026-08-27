import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { ProductSourceDecisionDock } from "./ProductSourceDecisionDock.tsx";

const assets = vi.hoisted(() => ({
  uploadFilesWithReceipts: vi.fn(),
  retry: vi.fn(),
  items: [] as Array<Record<string, unknown>>,
}));

vi.mock("../assets/useAgentCanvasAssets.ts", () => ({
  useAgentCanvasAssets: () => ({
    items: assets.items,
    loading: false,
    error: null,
    uploading: false,
    uploadError: null,
    retry: assets.retry,
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
    assets.items = [];
    assets.retry.mockReset();
    assets.retry.mockResolvedValue(undefined);
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
    fireEvent.click(screen.getByRole("button", { name: "Use selected Product" }));

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

    expect((screen.getByRole("button", { name: "Use selected Product" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("1 of 2-8 images selected")).toBeTruthy();
  });

  it("submits an existing Ready Project AssetVersion without uploading it", async () => {
    assets.items = [projectImage("asset-front", "version-front", "Existing Front")];
    const submit = vi.fn().mockResolvedValue(true);
    render(
      <ProductSourceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        onSubmit={submit}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Select Existing Front" }));
    fireEvent.click(screen.getByRole("button", { name: "Use selected Product" }));

    await waitFor(() => expect(submit).toHaveBeenCalledWith({
      submission_kind: "product_source",
      expected_interaction_revision: 3,
      expected_session_revision: 7,
      action: {
        input_kind: "main",
        choice: "upload",
        handoff_mode: "apply",
        asset_versions: [{ asset_id: "asset-front", version_id: "version-front" }],
        pending_handoff_id: null,
        expected_guidance_revision: 11,
        question_id: "product_main_source",
      },
    }));
    expect(assets.uploadFilesWithReceipts).not.toHaveBeenCalled();
  });

  it("replaces a Main selection with the most recently chosen source", () => {
    assets.items = [
      projectImage("asset-front", "version-front", "Existing Front"),
      projectImage("asset-side", "version-side", "Existing Side"),
    ];
    render(
      <ProductSourceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Select Existing Front" }));
    fireEvent.click(screen.getByRole("button", { name: "Select Existing Side" }));

    expect(screen.queryByText("Existing Front", { selector: ".agent-chat__product-source-selected-name" })).toBeNull();
    expect(screen.getByText("Existing Side", { selector: ".agent-chat__product-source-selected-name" })).toBeTruthy();
  });

  it("orders Multiview AssetVersions from the visible selected-source list", async () => {
    assets.items = [
      projectImage("asset-front", "version-front", "Existing Front"),
      projectImage("asset-side", "version-side", "Existing Side"),
    ];
    const submit = vi.fn().mockResolvedValue(true);
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
        onSubmit={submit}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Select Existing Front" }));
    fireEvent.click(screen.getByRole("button", { name: "Select Existing Side" }));
    fireEvent.click(screen.getByRole("button", { name: "Move Existing Side up" }));
    fireEvent.click(screen.getByRole("button", { name: "Use selected Product" }));

    await waitFor(() => expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      action: expect.objectContaining({
        asset_versions: [
          { asset_id: "asset-side", version_id: "version-side" },
          { asset_id: "asset-front", version_id: "version-front" },
        ],
      }),
    })));
  });

  it("does not admit unavailable or versionless Project assets", () => {
    assets.items = [
      { ...projectImage("asset-unavailable", "version-unavailable", "Unavailable"), status: "unavailable" },
      projectImage("asset-versionless", null, "Versionless"),
    ];
    render(
      <ProductSourceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        onSubmit={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect((screen.getByRole("button", { name: "Select Unavailable" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Select Versionless" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("preserves mixed uploaded and existing Multiview order", async () => {
    assets.items = [projectImage("asset-front", "version-front", "Existing Front")];
    assets.uploadFilesWithReceipts.mockResolvedValueOnce([{
      workflow_id: "workflow-1",
      asset: { asset_id: "asset-side", version_id: "version-side" },
      pending_handoff_id: null,
    }]);
    const submit = vi.fn().mockResolvedValue(true);
    render(
      <ProductSourceDecisionDock
        interaction={multiviewInteraction()}
        pending={false}
        issue={null}
        onSubmit={submit}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Select Existing Front" }));
    const side = new File(["side"], "side.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Upload Product sources"), {
      target: { files: [side] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Move side.png up" }));
    fireEvent.click(screen.getByRole("button", { name: "Use selected Product" }));

    await waitFor(() => expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      action: expect.objectContaining({
        asset_versions: [
          { asset_id: "asset-side", version_id: "version-side" },
          { asset_id: "asset-front", version_id: "version-front" },
        ],
      }),
    })));
  });

  it("reuses the same upload idempotency key when a guided submit must be confirmed again", async () => {
    const submit = vi.fn()
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(true);
    render(
      <ProductSourceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        onSubmit={submit}
      />,
    );
    const file = new File(["product"], "product.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Upload Product source"), { target: { files: [file] } });

    fireEvent.click(screen.getByRole("button", { name: "Use selected Product" }));
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Use selected Product" }));
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(2));

    expect(assets.uploadFilesWithReceipts).toHaveBeenCalledTimes(2);
    const firstKey = assets.uploadFilesWithReceipts.mock.calls[0][2][0];
    const secondKey = assets.uploadFilesWithReceipts.mock.calls[1][2][0];
    expect(secondKey).toBe(firstKey);
  });

  it("rejects conflicting pending handoffs without submitting", async () => {
    assets.uploadFilesWithReceipts.mockResolvedValueOnce([
      {
        workflow_id: "workflow-1",
        asset: { asset_id: "asset-front", version_id: "version-front" },
        pending_handoff_id: "handoff-front",
      },
      {
        workflow_id: "workflow-1",
        asset: { asset_id: "asset-side", version_id: "version-side" },
        pending_handoff_id: "handoff-side",
      },
    ]);
    const submit = vi.fn().mockResolvedValue(true);
    render(
      <ProductSourceDecisionDock
        interaction={multiviewInteraction()}
        pending={false}
        issue={null}
        onSubmit={submit}
      />,
    );
    fireEvent.change(screen.getByLabelText("Upload Product sources"), {
      target: {
        files: [
          new File(["front"], "front.png", { type: "image/png" }),
          new File(["side"], "side.png", { type: "image/png" }),
        ],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Use selected Product" }));

    expect(await screen.findByText("The Product uploads returned conflicting pending handoffs.")).toBeTruthy();
    expect(submit).not.toHaveBeenCalled();
  });

  it("allows only one in-flight submit for one confirmation", async () => {
    assets.items = [projectImage("asset-front", "version-front", "Existing Front")];
    let finishSubmit: ((value: boolean) => void) | null = null;
    const submit = vi.fn(() => new Promise<boolean>((resolve) => {
      finishSubmit = resolve;
    }));
    render(
      <ProductSourceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        onSubmit={submit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Select Existing Front" }));
    const confirm = screen.getByRole("button", { name: "Use selected Product" });

    act(() => {
      confirm.click();
      confirm.click();
    });

    expect(submit).toHaveBeenCalledTimes(1);
    finishSubmit?.(true);
  });

  it("refreshes Project Assets after the guided Product source is accepted", async () => {
    assets.items = [projectImage("asset-front", "version-front", "Existing Front")];
    const submit = vi.fn().mockResolvedValue(true);
    render(
      <ProductSourceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        onSubmit={submit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Select Existing Front" }));
    fireEvent.click(screen.getByRole("button", { name: "Use selected Product" }));

    await waitFor(() => expect(assets.retry).toHaveBeenCalledTimes(1));
  });
});

function projectImage(
  assetId: string,
  versionId: string | null,
  displayName: string,
) {
  return {
    id: `project:${assetId}`,
    assetId,
    source: "project",
    mediaType: "image",
    displayName,
    previewUrl: `/${assetId}.png`,
    mediaUrl: `/${assetId}.png`,
    status: "ready",
    tags: [],
    identity: {
      source: "project",
      assetId,
      entityId: null,
      versionId,
    },
    projectAsset: null,
  };
}

function multiviewInteraction(): GuidedInteractionV1 {
  return {
    ...interaction,
    content: {
      ...interaction.content,
      input_kind: "multiview",
      min_asset_count: 2,
      max_asset_count: 8,
    },
  };
}
