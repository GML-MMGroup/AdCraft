import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodeTypeV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";
import { AgentCanvasInlineWorkbench } from "./AgentCanvasInlineWorkbench.tsx";

function makeNode(type: CanvasNodeTypeV2, status: CanvasNodeV2["status"] = "draft"): CanvasNodeV2 {
  return {
    node_id: `${type}-node`,
    workflow_id: "workflow-1",
    node_type: type,
    creative_role: type === "text" ? "general_text" : type === "script" ? "script" : type === "image" ? "general_image" : type === "video" ? "general_video" : type === "audio" ? "general_audio" : "editing",
    role_contract_version: "ad-media-role-v1",
    title: `${type} node`,
    status,
    summary_prompt: null,
    generation_prompt: type === "image" ? "A quiet fragrance film" : null,
    structured_content: type === "text" ? { content: "Initial brief" } : type === "script" ? { script_text: "Open on dawn." } : {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position: { x: 120, y: 140 },
    revision: 1,
    error: null,
    variation_draft: null,
    created_at: "2026-07-31T00:00:00Z",
    updated_at: "2026-07-31T00:00:00Z",
  };
}

function makeWorkflow(node: CanvasNodeV2): AgentCanvasWorkflowV2 {
  return {
    workflow_id: "workflow-1",
    project_id: "project-1",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 1,
    layout_revision: 1,
    nodes: [node],
    bindings: [],
    assets: [],
  };
}

function makeReferenceWorkflow(target: CanvasNodeV2): AgentCanvasWorkflowV2 {
  const source = {
    ...makeNode("image", "ready"),
    node_id: "source-image",
    title: "Character board",
    output_asset_id: "source-image-asset",
  };
  return {
    ...makeWorkflow(target),
    nodes: [source, target],
    bindings: [{
      binding_id: "source-binding",
      workflow_id: "workflow-1",
      source: { kind: "node_output", source_node_id: source.node_id },
      target_node_id: target.node_id,
      input_role: "visual_reference",
      required: true,
      enabled: true,
      order: 0,
      label: null,
      metadata: {},
      created_at: "2026-07-31T00:00:00Z",
      updated_at: "2026-07-31T00:00:00Z",
    }],
    assets: [{
      asset_id: "source-image-asset",
      project_id: "project-1",
      workflow_id: "workflow-1",
      media_type: "image",
      source_type: "generated",
      display_name: "Character board",
      mime_type: "image/webp",
      status: "ready",
      size_bytes: 0,
      storage_key: null,
      preview_url: "/assets/character-board.webp",
      media_url: "/assets/character-board.webp",
      width: 1024,
      height: 1024,
      duration_seconds: null,
      checksum: "source-image-checksum",
      source_semantic_role: null,
      source_node_id: source.node_id,
      source_execution_id: null,
      provider: null,
      model_id: null,
      prompt_provenance: {},
      quality_metadata: {},
      created_at: "2026-07-31T00:00:00Z",
    }],
  } as AgentCanvasWorkflowV2;
}

function makeTextReferenceWorkflow(target: CanvasNodeV2): AgentCanvasWorkflowV2 {
  const source = {
    ...makeNode("text", "ready"),
    node_id: "source-text",
    title: "World Setting",
    structured_content: { content: "A calm morning in a riverside park." },
  };
  return {
    ...makeWorkflow(target),
    nodes: [source, target],
    bindings: [{
      binding_id: "text-binding",
      workflow_id: "workflow-1",
      source: { kind: "node_output", source_node_id: source.node_id },
      target_node_id: target.node_id,
      input_role: "text_context",
      required: true,
      enabled: true,
      order: 0,
      label: null,
      metadata: {},
      created_at: "2026-07-31T00:00:00Z",
      updated_at: "2026-07-31T00:00:00Z",
    }],
    assets: [],
  } as AgentCanvasWorkflowV2;
}

function renderWorkbench(node: CanvasNodeV2, overrides: Record<string, unknown> = {}) {
  const props = {
    workflow: makeWorkflow(node),
    node,
    patchNode: vi.fn().mockResolvedValue(undefined),
    patchBinding: vi.fn().mockResolvedValue(undefined),
    deleteBinding: vi.fn().mockResolvedValue(undefined),
    onRun: vi.fn().mockResolvedValue(undefined),
    onSaveVariation: vi.fn().mockResolvedValue(undefined),
    onDiscardVariation: vi.fn().mockResolvedValue(undefined),
    onMaterializeVariation: vi.fn().mockResolvedValue(null),
    onSaveImageToLibrary: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn().mockResolvedValue(undefined),
    onOpenEditing: vi.fn(),
    onOpenAssets: vi.fn(),
    onUploadReferences: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  render(<AgentCanvasInlineWorkbench {...props} />);
  return props;
}

afterEach(() => cleanup());

describe("AgentCanvasInlineWorkbench", () => {
  it("uses a solid black-gray surface without gradients or backdrop blur", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/workbench/agent-canvas-inline-workbench.css");
    const css = readFileSync(cssPath, "utf8");
    const shellRule = css.match(/^\.agent-node-workbench\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(shellRule).toContain("background: #2a2a2a");
    expect(shellRule).not.toContain("gradient");
    expect(shellRule).toContain("backdrop-filter: none");
  });

  it.each<[CanvasNodeTypeV2, string]>([
    ["text", "Text content"],
    ["image", "Generation prompt"],
  ])("uses a compact prompt composer for %s without node name chrome", (nodeType, textareaLabel) => {
    const node = makeNode(nodeType);
    renderWorkbench(node);

    expect(screen.getByLabelText(textareaLabel)).toBeTruthy();
    expect(screen.queryByText("Name")).toBeNull();
    expect(screen.queryByText(node.title)).toBeNull();
    expect(screen.queryByText(nodeType.toUpperCase())).toBeNull();
  });

  it("keeps a guided Draft visible while its generation prompt is being prepared and disables only that node Run action", () => {
    const node = {
      ...makeNode("image"),
      summary_prompt: "A warm product portrait for the campaign opening.",
      generation_prompt: null,
      prompt_preparation: {
        status: "working",
        operation_id: "prompt-operation-1",
        attempt_no: 1,
        context_snapshot_id: "snapshot-1",
        prompt_digest: null,
        error: null,
        updated_at: "2026-08-11T10:00:00Z",
      },
    } as CanvasNodeV2;

    renderWorkbench(node);

    expect(screen.getByText("A warm product portrait for the campaign opening.")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Preparing generation prompt");
    expect(screen.queryByLabelText("Generation prompt")).toBeNull();
    expect(screen.queryByRole("button", { name: "Run image node" })).toBeNull();
  });

  it("renders the prepared generation prompt and enables the existing Run action once preparation is ready", () => {
    const node = {
      ...makeNode("image"),
      summary_prompt: "A warm product portrait for the campaign opening.",
      generation_prompt: "Create a warm product portrait for the campaign opening.",
      prompt_preparation: {
        status: "ready",
        operation_id: "prompt-operation-1",
        attempt_no: 1,
        context_snapshot_id: "snapshot-1",
        prompt_digest: "a".repeat(64),
        error: null,
        updated_at: "2026-08-11T10:00:00Z",
      },
    } as CanvasNodeV2;

    renderWorkbench(node);

    expect((screen.getByLabelText("Generation prompt") as HTMLTextAreaElement).value).toBe(
      "Create a warm product portrait for the campaign opening.",
    );
    expect((screen.getByRole("button", { name: "Run image node" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows a retryable prompt preparation error without presenting it as media generation failure", () => {
    const node = {
      ...makeNode("image"),
      summary_prompt: "A warm product portrait for the campaign opening.",
      generation_prompt: null,
      prompt_preparation: {
        status: "failed",
        operation_id: "prompt-operation-1",
        attempt_no: 2,
        context_snapshot_id: "snapshot-1",
        prompt_digest: null,
        error: {
          code: "prompt_preparation_failed",
          message: "Node prompt preparation failed.",
          retryable: true,
        },
        updated_at: "2026-08-11T10:00:00Z",
      },
    } as CanvasNodeV2;

    renderWorkbench(node);

    expect(screen.getByRole("alert").textContent).toContain("Node prompt preparation failed.");
    expect(screen.getByRole("alert").textContent).toContain("Retryable");
    expect(screen.queryByRole("button", { name: "Retry image node" })).toBeNull();
  });

  it("saves a Script direction before running the canonical Script node", async () => {
    const node = { ...makeNode("script"), generation_prompt: null };
    const props = renderWorkbench(node);

    const run = screen.getByRole("button", { name: "Run script node" }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Script direction"), {
      target: { value: "Write a thirty-second fragrance film with three short scenes." },
    });
    fireEvent.click(run);

    await waitFor(() => expect(props.patchNode).toHaveBeenCalledWith(node.node_id, expect.objectContaining({
      generation_prompt: "Write a thirty-second fragrance film with three short scenes.",
    })));
    expect(props.onRun).toHaveBeenCalledWith(node);
  });

  it("saves structured text before running a Text node", async () => {
    const node = makeNode("text");
    const props = renderWorkbench(node);

    fireEvent.change(screen.getByLabelText("Text content"), {
      target: { value: "A revised campaign brief" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run text node" }));

    await waitFor(() => {
      expect(props.patchNode).toHaveBeenCalledWith(node.node_id, expect.objectContaining({
        structured_content: { content: "A revised campaign brief" },
      }));
    });
    expect(props.onRun).toHaveBeenCalledWith(node);
  });

  it("edits a World Setting in place without model or Run controls", async () => {
    const provenance = {
      source_proposal_id: "proposal-world-1",
      source_option_id: "option-world-1",
      materialization_run_id: "materialization-1",
      style_skill_run_id: "style-run-1",
      creative_direction_snapshot_id: "direction-1",
    };
    const core = {
      premise: "Living craft quietly shapes modern life.",
      era_and_place: "A contemporary coastal city.",
      world_rules: ["Technology remains visually unobtrusive."],
      visual_continuity: ["Pale stone and warm practical light recur."],
    };
    const node: CanvasNodeV2 = {
      ...makeNode("text", "ready"),
      node_id: "world-setting-node",
      creative_role: "world_setting",
      title: "World Setting",
      structured_content: {
        document_kind: "world_setting",
        contract_version: "world-setting-v2",
        content: "A quiet contemporary city.",
        core,
        authoring_provenance: provenance,
      },
    };
    const props = renderWorkbench(node);

    expect(screen.queryByLabelText("Choose model")).toBeNull();
    expect(screen.queryByRole("button", { name: "Run text node" })).toBeNull();
    fireEvent.change(screen.getByLabelText("World Setting content"), {
      target: { value: "A quiet contemporary city shaped by living craft traditions." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save World Setting changes" }));

    await waitFor(() => expect(props.patchNode).toHaveBeenCalledWith(
      "world-setting-node",
      expect.objectContaining({
        structured_content: {
          document_kind: "world_setting",
          contract_version: "world-setting-v2",
          content: "A quiet contemporary city shaped by living craft traditions.",
          core,
          authoring_provenance: provenance,
        },
      }),
    ));
    expect(props.onRun).not.toHaveBeenCalled();
  });

  it("saves a ready media prompt before creating a sibling variation", async () => {
    const node = makeNode("image", "ready");
    const props = renderWorkbench(node);

    fireEvent.change(screen.getByLabelText("Generation prompt"), {
      target: { value: "A cinematic amber fragrance film" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate image variation" }));

    await waitFor(() => {
      expect(props.onSaveVariation).toHaveBeenCalledWith(node.node_id, expect.objectContaining({
        generation_prompt: "A cinematic amber fragrance film",
      }));
    });
    expect(props.onMaterializeVariation).toHaveBeenCalledWith(node, "generate");
  });

  it("pins a catalog model through canonical selection fields without sending model_id", async () => {
    const node = makeNode("image");
    const props = renderWorkbench(node, {
      providerModels: [{
        model_ref: "siliconflow:stable-image",
        provider_id: "siliconflow",
        provider_model_id: "stable-image",
        display_name: "Stable Image",
        capability: "image",
        capability_metadata: {},
        availability: "available",
        unavailable_reason: null,
        catalog_revision: 4,
      }],
    });

    fireEvent.click(screen.getByLabelText("Choose model"));
    fireEvent.click(screen.getByRole("option", { name: /Stable Image/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run image node" }));

    await waitFor(() => expect(props.patchNode).toHaveBeenCalledWith(node.node_id, expect.objectContaining({
      model_selection_mode: "explicit",
      model_ref: "siliconflow:stable-image",
    })));
    const request = (props.patchNode as ReturnType<typeof vi.fn>).mock.calls[0][1] as Record<string, unknown>;
    expect(request).not.toHaveProperty("model_id");
  });

  it("opens the shared assets browser from the media workbench", () => {
    const props = renderWorkbench(makeNode("video"));

    fireEvent.click(screen.getByRole("button", { name: "Choose asset references" }));

    expect(props.onOpenAssets).toHaveBeenCalledOnce();
  });

  it("migrates legacy video duration parameters before running an existing node", async () => {
    const node = {
      ...makeNode("video"),
      generation_prompt: "Animate the supplied references.",
      parameters: {
        requested_duration_seconds: 0,
        effective_duration_seconds: 15,
      },
    };
    const props = renderWorkbench(node);

    expect((screen.getByLabelText("Requested video duration") as HTMLInputElement).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Run video node" }));

    await waitFor(() => {
      expect(props.patchNode).toHaveBeenCalledWith(node.node_id, expect.objectContaining({
        parameters: {},
      }));
    });
    expect(props.onRun).toHaveBeenCalledWith(node);
  });

  it("preserves requested video durations above the provider limit under the canonical key", async () => {
    const node = {
      ...makeNode("video"),
      generation_prompt: "Animate the supplied references.",
      parameters: { requested_duration_seconds: 30 },
    };
    const props = renderWorkbench(node);
    const duration = screen.getByLabelText("Requested video duration");

    expect((duration as HTMLInputElement).value).toBe("30");
    fireEvent.change(duration, { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Run video node" }));

    await waitFor(() => {
      expect(props.patchNode).toHaveBeenCalledWith(node.node_id, expect.objectContaining({
        parameters: { duration_seconds: 20 },
      }));
    });
    expect(props.onRun).toHaveBeenCalledWith(node);
  });

  it("does not persist fractional video durations that the provider contract rejects", async () => {
    const node = {
      ...makeNode("video"),
      generation_prompt: "Animate the supplied references.",
    };
    const props = renderWorkbench(node);
    const duration = screen.getByLabelText("Requested video duration");

    fireEvent.change(duration, { target: { value: "20.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Run video node" }));

    await waitFor(() => {
      expect(props.patchNode).toHaveBeenCalledWith(node.node_id, expect.objectContaining({
        parameters: {},
      }));
    });
    expect(props.onRun).toHaveBeenCalledWith(node);
  });

  it("renders upstream media as removable thumbnails without generic workbench chrome", () => {
    const node = makeNode("image");
    const props = renderWorkbench(node, { workflow: makeReferenceWorkflow(node) });

    expect(screen.getByRole("img", { name: "Character board reference" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove Character board reference" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete node" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Close node workbench" })).toBeNull();
    expect(screen.queryByText("References")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Remove Character board reference" }));
    expect(props.deleteBinding).toHaveBeenCalledWith("source-binding");
  });

  it("uses the asset library as the only visible reference entry point", () => {
    renderWorkbench(makeNode("image"));

    expect(screen.getByRole("button", { name: "Choose asset references" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Upload image reference" })).toBeNull();
  });

  it("renders upstream text as a labelled reference chip", () => {
    const node = makeNode("image");
    renderWorkbench(node, { workflow: makeTextReferenceWorkflow(node) });

    expect(screen.getByText("World Setting")).toBeTruthy();
  });

  it("keeps the Text node model control in the composer footer", () => {
    const props = {
      workflow: makeWorkflow(makeNode("text")),
      node: makeNode("text"),
      patchNode: vi.fn().mockResolvedValue(undefined),
      patchBinding: vi.fn().mockResolvedValue(undefined),
      deleteBinding: vi.fn().mockResolvedValue(undefined),
      onRun: vi.fn().mockResolvedValue(undefined),
      onSaveVariation: vi.fn().mockResolvedValue(undefined),
      onDiscardVariation: vi.fn().mockResolvedValue(undefined),
      onMaterializeVariation: vi.fn().mockResolvedValue(null),
      onSaveImageToLibrary: vi.fn().mockResolvedValue(undefined),
      onDelete: vi.fn().mockResolvedValue(undefined),
      onOpenEditing: vi.fn(),
      onOpenAssets: vi.fn(),
      onUploadReferences: vi.fn(),
      onClose: vi.fn(),
    };
    const { container } = render(<AgentCanvasInlineWorkbench {...props} />);

    expect(container.querySelector(
      ".agent-node-workbench__footer .agent-node-workbench__model-picker",
    )).toBeTruthy();
  });
});
