import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { GuidedInteractionV1 } from "../../../types-v2.ts";
import { LocaleProvider, useLocale } from "../../../i18n/locale.tsx";
import { ProductSourceDecisionDock } from "./ProductSourceDecisionDock.tsx";
import type { ProductMainHandoff } from "./productSourceHandoff.ts";

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

function LanguageSwitch() {
  const { setLocale } = useLocale();
  return <>
    <button onClick={() => setLocale("zh-CN")}>中文</button>
    <button onClick={() => setLocale("en-US")}>English</button>
  </>;
}

describe("ProductSourceDecisionDock", () => {
  beforeEach(() => {
    window.localStorage.removeItem("adcraft.locale");
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

  afterEach(() => {
    cleanup();
    window.localStorage.removeItem("adcraft.locale");
  });

  it.each(["character", "scene"] as const)("submits %s images directly with occurrence identity and no Main upload", async (role) => {
    assets.items = Array.from({ length: 9 }, (_, index) => projectImage(`asset-${index}`, `v-${index}`, `View ${index}`));
    const submit = vi.fn().mockResolvedValue(true);
    const source: GuidedInteractionV1 = {
      ...interaction, title: `${role === "character" ? "Character" : "Scene"} image source`,
      content: { content_kind: "product_source", source_role: role,
        occurrence_id: role === "character" ? "character-2" : null, source_label: role === "character" ? "Nurse" : null,
        input_kind: "multiview", min_asset_count: 1, max_asset_count: null,
        question_id: `${role}_multiview_source`, prompt: "Provide one or more existing images, or ask the Agent to design this asset.", expected_guidance_revision: 11 },
    };
    render(<ProductSourceDecisionDock interaction={source} pending={false} issue={null} onSubmit={submit} />);
    expect(screen.getByText("One image is used as-is; multiple images are combined in the selected order.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Select View 0" }));
    expect((screen.getByRole("button", { name: "Use selected images" }) as HTMLButtonElement).disabled).toBe(false);
    for (let index = 1; index < 9; index++) fireEvent.click(screen.getByRole("button", { name: `Select View ${index}` }));
    fireEvent.click(screen.getByRole("button", { name: "Move View 8 up" }));
    fireEvent.click(screen.getByRole("button", { name: "Use selected images" }));
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    const action = submit.mock.calls[0][0].action;
    expect(action.source_role).toBe(role);
    expect(action.occurrence_id).toBe(role === "character" ? "character-2" : null);
    expect(action.input_kind).toBe("multiview");
    expect(action.asset_versions).toHaveLength(9);
    expect(action.asset_versions[7].asset_id).toBe("asset-8");
    expect(assets.uploadFilesWithReceipts).not.toHaveBeenCalled();
  });

  it("can select Agent design for a Scene without supplying any image", async () => {
    const submit = vi.fn().mockResolvedValue(true);
    render(<ProductSourceDecisionDock interaction={{ ...interaction, title: "Scene image source", content: {
      content_kind: "product_source", source_role: "scene", occurrence_id: null, input_kind: "multiview",
      question_id: "scene_multiview_source", prompt: "Choose a source.", expected_guidance_revision: 11, min_asset_count: 1, max_asset_count: null,
    } }} pending={false} issue={null} onSubmit={submit} />);
    fireEvent.click(screen.getByRole("radio", { name: "Agent design and generation" }));
    fireEvent.click(screen.getByRole("button", { name: "Let the Agent design" }));
    await waitFor(() => expect(submit).toHaveBeenCalledWith(expect.objectContaining({ action: expect.objectContaining({ source_role: "scene", choice: "generate", asset_versions: [] }) })));
  });

  it("switches the entire main-image panel live without losing the selected image", async () => {
    assets.items = [projectImage("asset-front", "version-front", "Front.png")];
    const submit = vi.fn().mockResolvedValue(true);
    render(
      <LocaleProvider initialLocale="en-US">
        <LanguageSwitch />
        <ProductSourceDecisionDock interaction={{ ...interaction, title: "Product image source",
          context: "Choose whether to upload or generate the Product source.",
          content: { ...interaction.content, prompt: "Provide one Product Main image." },
        }} pending={false} issue={null} onSubmit={submit} />
      </LocaleProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Select Front.png" }));
    fireEvent.click(screen.getByRole("button", { name: "中文" }));
    expect(screen.getByRole("article", { name: "产品图片来源" })).toBeTruthy();
    expect(screen.getByText("请选择上传产品图片，或由智能助手生成。")).toBeTruthy();
    expect(screen.getByText("请提供 1 张产品主图。")).toBeTruthy();
    expect(screen.getByRole("radio", { name: "使用上传的产品图片" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "生成产品图片" })).toBeTruthy();
    expect(screen.getByText("项目素材")).toBeTruthy();
    expect(screen.getByPlaceholderText("搜索图片")).toBeTruthy();
    expect(screen.getByLabelText("上传产品图片")).toBeTruthy();
    expect(screen.getByText("已选择 1 张图片，需选择 1 张")).toBeTruthy();
    expect(screen.getByRole("button", { name: "移除Front.png" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    expect(screen.getByRole("article", { name: "Product image source" })).toBeTruthy();
    expect(screen.getByText("1 of 1 image selected")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Use selected Product" }));
    await waitFor(() => expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      action: expect.objectContaining({ asset_versions: [{ asset_id: "asset-front", version_id: "version-front" }] }),
    })));
  });

  it("localizes multiview prompts, ordering controls and selection errors", async () => {
    assets.items = [projectImage("front", "v-front", "Front.png"), projectImage("side", "v-side", "Side.png")];
    const submit = vi.fn().mockResolvedValue(true);
    const multi = multiviewInteraction();
    render(
      <LocaleProvider initialLocale="zh-CN">
        <ProductSourceDecisionDock interaction={{ ...multi, title: "Product image source",
          context: "Choose how to provide Product Multiview images.",
          content: { ...multi.content, prompt: "Provide two to eight ordered Product Multiview images." },
        }} pending={false} issue={null} onSubmit={submit} />
      </LocaleProvider>,
    );
    expect(screen.getByText("请选择如何提供产品多视角图片。")).toBeTruthy();
    expect(screen.getByText("请按顺序提供 2–8 张产品多视角图片。")).toBeTruthy();
    expect(screen.getByLabelText("上传多张产品图片")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "选择Front.png" }));
    fireEvent.click(screen.getByRole("button", { name: "选择Front.png" }));
    expect(screen.getByRole("alert").textContent).toContain("已选择这张产品图片。");
    fireEvent.click(screen.getByRole("button", { name: "选择Side.png" }));
    expect(screen.getByText("已选择 2 张图片，需选择 2–8 张")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "将Side.png上移" }));
    fireEvent.click(screen.getByRole("button", { name: "使用所选产品图片" }));
    await waitFor(() => expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      action: expect.objectContaining({ asset_versions: [
        { asset_id: "side", version_id: "v-side" }, { asset_id: "front", version_id: "v-front" },
      ] }),
    })));
  });

  it("localizes empty state and generation failure even when the locale changes after the error", async () => {
    const submit = vi.fn().mockRejectedValue(new Error("Unable to prepare the Product source."));
    render(
      <LocaleProvider initialLocale="en-US">
        <LanguageSwitch />
        <ProductSourceDecisionDock interaction={interaction} pending={false} issue={null} onSubmit={submit} />
      </LocaleProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "中文" }));
    expect(screen.getByText("暂无可用的项目图片")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "生成产品图片" }));
    expect(screen.getByText("智能助手将生成产品图片")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "生成产品图片" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("产品图片准备失败，请重试。"));
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    expect(screen.getByRole("alert").textContent).toContain("The Product source could not be prepared.");
  });

  it("uploads one main Product source and submits the exact immutable handoff", async () => {
    const submit = vi.fn().mockResolvedValue(true);
    const refreshProjects = vi.fn().mockResolvedValue(true);
    render(
      <ProductSourceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        onSubmit={submit}
        onProjectsRefresh={refreshProjects}
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
    expect(refreshProjects).toHaveBeenCalledTimes(1);
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

  it("reuses an explicitly marked Intake Product Main handoff without uploading again", async () => {
    const submit = vi.fn().mockResolvedValue(true);
    const handoff: ProductMainHandoff = {
      workflowId: "workflow-1",
      assetId: "asset-intake-product",
      versionId: "version-intake-product-1",
      pendingHandoffId: "handoff-intake-product-1",
      displayName: "Intake Product Main",
      previewUrl: "/intake-product.png",
    };
    render(
      <ProductSourceDecisionDock
        interaction={interaction}
        pending={false}
        issue={null}
        pendingProductMainHandoff={handoff}
        onSubmit={submit}
        onClearProductMainHandoff={vi.fn()}
      />,
    );

    expect(screen.getByText("Intake Product Main", { selector: ".agent-chat__product-source-selected-name" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Use selected Product" }));

    await waitFor(() => expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      action: expect.objectContaining({
        asset_versions: [{ asset_id: "asset-intake-product", version_id: "version-intake-product-1" }],
        pending_handoff_id: "handoff-intake-product-1",
      }),
    })));
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
