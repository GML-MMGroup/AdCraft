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
    generation_prompt: type === "editing" ? null : `Prepare the ${type} node.`,
    structured_content: type === "text" ? { content: "Initial brief" } : type === "script" ? { script_text: "Open on dawn." } : {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position: { x: 120, y: 140 },
    revision: 1,
    error: null,
    prompt_preparation: type === "editing" ? null : {
      status: "ready",
      operation_id: `prepare-${type}`,
      attempt_no: 1,
      context_snapshot_id: `snapshot-${type}`,
      prompt_digest: "a".repeat(64),
      role_variant: null,
      recipe_id: null,
      recipe_version: null,
      recipe_digest: null,
      requirement_revision_id: null,
      requirement_revision_no: null,
      document_revisions: {},
      binding_digest: null,
      style_projection_digest: null,
      brief_digest: null,
      parameter_origins: [],
      attempt_stage: "ready",
      error: null,
      updated_at: "2026-07-31T00:00:00Z",
    },
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

  it("keeps the Script editor on the shared workbench font", () => {
    const css = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/workbench/agent-canvas-inline-workbench.css"),
      "utf8",
    );
    const scriptComposerRule = css.match(
      /\.agent-node-workbench__composer--script textarea\s*\{([\s\S]*?)\n\}/,
    )?.[1];

    expect(scriptComposerRule).toBeTruthy();
    expect(scriptComposerRule).not.toContain("font-family");
  });

  it.each<[CanvasNodeTypeV2, string]>([
    ["text", "Text prompt"],
    ["image", "Generation prompt"],
  ])("uses a compact prompt composer for %s without node name chrome", (nodeType, textareaLabel) => {
    const node = makeNode(nodeType);
    renderWorkbench(node);

    expect(screen.getByLabelText(textareaLabel)).toBeTruthy();
    expect(screen.queryByText("Name")).toBeNull();
    expect(screen.queryByText(node.title)).toBeNull();
    expect(screen.queryByText(nodeType.toUpperCase())).toBeNull();
  });

  it("does not expose generation controls for a source-only Video node", () => {
    const node = {
      ...makeNode("video", "ready"),
      execution_mode: "source_only" as const,
      generation_prompt: "This prompt must not become an editable source-only control.",
      output_asset_id: "editing-export-asset",
    };

    renderWorkbench(node);

    expect(screen.queryByLabelText("Generation prompt")).toBeNull();
    expect(screen.queryByLabelText("Choose model")).toBeNull();
    expect(screen.queryByRole("button", { name: "Run video node" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Generate video variation" })).toBeNull();
  });

  it("does not expose generation controls for a source-only Product node", () => {
    const node = {
      ...makeNode("image", "ready"),
      creative_role: "product" as const,
      execution_mode: "source_only" as const,
      generation_prompt: "This source provenance is not a generation prompt.",
      output_asset_id: "product-source-asset",
    };

    renderWorkbench(node);

    expect(screen.queryByLabelText("Generation prompt")).toBeNull();
    expect(screen.queryByLabelText("Choose model")).toBeNull();
    expect(screen.queryByRole("button", { name: "Run image node" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Generate image variation" })).toBeNull();
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
    expect(screen.getByLabelText("Generation prompt")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Run image node" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps a waiting-user media node editable without presenting a provider failure", () => {
    const node = {
      ...makeNode("video"),
      generation_prompt: null,
      prompt_preparation: {
        status: "waiting_user",
        operation_id: null,
        presentation_stream_id: null,
        attempt_no: 0,
        context_snapshot_id: null,
        occurrence_id: null,
        character_phase: null,
        prompt_digest: null,
        role_variant: null,
        recipe_id: null,
        recipe_version: null,
        recipe_digest: null,
        requirement_revision_id: null,
        requirement_revision_no: null,
        document_revisions: {},
        binding_digest: null,
        style_projection_digest: null,
        brief_digest: null,
        parameter_origins: [],
        compaction_policy_version: null,
        compaction_policy_digest: null,
        compaction_decisions: [],
        assertion_evidence: null,
        attempt_stage: null,
        error: null,
        updated_at: "2026-08-31T10:00:00Z",
      },
    } as CanvasNodeV2;

    renderWorkbench(node);

    expect(screen.getByLabelText("Generation prompt")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Prompt input needed");
    expect(screen.getByRole("status").textContent).toContain("Enter a prompt to continue.");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps a new V2 Text node editable without a preparation warning", () => {
    const node = {
      ...makeNode("text"),
      prompt_preparation: null,
    } as CanvasNodeV2;

    renderWorkbench(node);

    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByLabelText("Text prompt")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Run text node" }) as HTMLButtonElement).disabled).toBe(false);
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

  it("saves a Draft Script prompt without materializing content before running it", async () => {
    const node = {
      ...makeNode("script"),
      generation_prompt: "Write a concise launch script.",
      structured_content: {},
    } as CanvasNodeV2;
    const props = renderWorkbench(node);

    expect((screen.getByLabelText("Script prompt") as HTMLTextAreaElement).value)
      .toBe("Write a concise launch script.");

    fireEvent.change(screen.getByLabelText("Script prompt"), {
      target: { value: "Write a quiet office story before the first meeting." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run script node" }));

    await waitFor(() => expect(props.patchNode).toHaveBeenCalled());
    const patch = (props.patchNode as ReturnType<typeof vi.fn>).mock.calls[0]?.[1];
    expect(patch).toEqual(expect.objectContaining({
      generation_prompt: "Write a quiet office story before the first meeting.",
    }));
    expect(patch).not.toHaveProperty("structured_content");
    expect(props.onRun).toHaveBeenCalledWith(expect.objectContaining({
      node_id: node.node_id,
      generation_prompt: "Write a quiet office story before the first meeting.",
    }));
  });

  it("waits for the manual prompt PATCH before running a Draft media node", async () => {
    let resolvePatch!: () => void;
    const patchNode = vi.fn(() => new Promise<void>((resolve) => {
      resolvePatch = resolve;
    }));
    const node = {
      ...makeNode("image"),
      generation_prompt: null,
      prompt_preparation: null,
    } as CanvasNodeV2;
    const props = renderWorkbench(node, { patchNode });

    fireEvent.change(screen.getByLabelText("Generation prompt"), {
      target: { value: "A clean studio product shot" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run image node" }));

    await waitFor(() => expect(patchNode).toHaveBeenCalledTimes(1));
    expect(props.onRun).not.toHaveBeenCalled();
    resolvePatch();
    await waitFor(() => expect(props.onRun).toHaveBeenCalledWith(expect.objectContaining({
      generation_prompt: "A clean studio product shot",
    })));
  });

  it("saves a ready Script node without running it again", async () => {
    const node = {
      ...makeNode("script", "ready"),
      structured_content: {
        document_kind: "script",
        script_text: "Open on dawn.",
        authoring_provenance: { source_option_id: "option-script-1" },
      },
    } as CanvasNodeV2;
    const props = renderWorkbench(node);

    fireEvent.change(screen.getByLabelText("Script content"), {
      target: { value: "A refined ready script." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save script node" }));

    await waitFor(() => expect(props.patchNode).toHaveBeenCalledWith(
      node.node_id,
      expect.objectContaining({
        structured_content: {
          document_kind: "script",
          script_text: "Open on dawn.",
          authoring_provenance: { source_option_id: "option-script-1" },
          content: "A refined ready script.",
        },
      }),
    ));
    expect(props.onRun).not.toHaveBeenCalled();
  });

  it("uses the live Working status to prevent editing a canonically Draft Script", () => {
    const node = makeNode("script", "draft");
    const props = renderWorkbench(node, { visibleStatus: "working" });

    expect(screen.getByLabelText("Script content")).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Script node is working" }))
      .toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Script node is working" }));

    expect(props.patchNode).not.toHaveBeenCalled();
    expect(props.onRun).not.toHaveBeenCalled();
  });

  it("uses the live Ready status when saving a canonically Draft Script", async () => {
    const node = {
      ...makeNode("script", "draft"),
      structured_content: {},
    } as CanvasNodeV2;
    const props = renderWorkbench(node, { visibleStatus: "ready" });

    fireEvent.change(screen.getByLabelText("Script content"), {
      target: { value: "A recovered Script result." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save script node" }));

    await waitFor(() => expect(props.patchNode).toHaveBeenCalledWith(
      node.node_id,
      expect.objectContaining({
        structured_content: { content: "A recovered Script result." },
      }),
    ));
    expect(props.onRun).not.toHaveBeenCalled();
  });

  it("uses the live Failed status when retrying a canonically Draft Script", async () => {
    const node = {
      ...makeNode("script", "draft"),
      structured_content: {},
    } as CanvasNodeV2;
    const props = renderWorkbench(node, { visibleStatus: "failed" });

    fireEvent.click(screen.getByRole("button", { name: "Retry script node" }));

    await waitFor(() => expect(props.onRun).toHaveBeenCalledWith(
      expect.objectContaining({
        node_id: node.node_id,
        status: "failed",
      }),
    ));
  });

  it("saves structured text before running a Text node", async () => {
    const node = makeNode("text");
    const props = renderWorkbench(node);

    fireEvent.change(screen.getByLabelText("Text prompt"), {
      target: { value: "A revised campaign brief" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run text node" }));

    await waitFor(() => {
      expect(props.patchNode).toHaveBeenCalledWith(node.node_id, {
        generation_prompt: "A revised campaign brief",
      }, { coalesce: true });
    });
    expect(props.onRun).toHaveBeenCalledWith(expect.objectContaining({
      node_id: node.node_id,
      generation_prompt: "A revised campaign brief",
    }));
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

  it("renders upstream text as a generic document SVG without exposing its content", () => {
    const node = makeNode("image");
    renderWorkbench(node, { workflow: makeTextReferenceWorkflow(node) });

    const reference = screen.getByLabelText("World Setting text reference");
    expect(reference.querySelector("svg")).toBeTruthy();
    expect(reference.textContent).toBe("");
    expect(document.body.textContent).not.toContain("A calm morning in a riverside park.");
  });

  it("wraps upstream references without a constrained scrolling strip", () => {
    const css = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/workbench/agent-canvas-inline-workbench.css"),
      "utf8",
    );
    const referencesRule = css.match(
      /\.agent-node-workbench__references\s*\{([\s\S]*?)\n\}/,
    )?.[1];
    const listRule = css.match(
      /\.agent-node-workbench__reference-list\s*\{([\s\S]*?)\n\}/,
    )?.[1];

    expect(referencesRule).toContain("align-items: flex-start");
    expect(listRule).toContain("flex-wrap: wrap");
    expect(listRule).toContain("overflow: visible");
    expect(listRule).not.toContain("overflow-x: auto");
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
