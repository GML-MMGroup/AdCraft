import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";
import { V2ApiError } from "../../../api/v2Client.ts";
import { SaveIcon } from "../../../icons.tsx";
import type {
  AgentCanvasWorkflowV2,
  CanvasNodeTypeV2,
  CanvasNodeV2,
  NodeRuntimeV2,
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

const descriptorVideoModel: ProviderModelSummaryV1 = {
  model_ref: "volcengine_ark:doubao-seedance-2-0-260128",
  provider_id: "volcengine_ark",
  provider_model_id: "doubao-seedance-2-0-260128",
  display_name: "Seedance 2.0",
  capability: "video",
  capability_metadata: {},
  availability: "available",
  unavailable_reason: null,
  catalog_revision: 4,
  adapter_id: "ark-video-v1",
  transport_kind: "ark_video_native",
  release_tier: "default",
  conformance_status: "compatible",
  accepted_input_modes: ["text"],
  parameter_schema_id: "ark-video-v1",
  parameter_descriptors: [{
    name: "duration_seconds",
    value_type: "integer",
    allowed_values: [],
    minimum: 1,
    maximum: 30,
    default: 5,
  }],
  reference_policy: null,
};

function withDescriptorVideoModel(node: CanvasNodeV2): CanvasNodeV2 {
  return {
    ...node,
    model_summary: {
      model_ref: descriptorVideoModel.model_ref,
      provider_id: descriptorVideoModel.provider_id,
      display_name: descriptorVideoModel.display_name,
      capability: "video",
      availability: "available",
      unavailable_reason: null,
      catalog_revision: descriptorVideoModel.catalog_revision,
    },
  };
}

const audioVideoModel: ProviderModelSummaryV1 = {
  ...descriptorVideoModel,
  parameter_descriptors: [
    ...descriptorVideoModel.parameter_descriptors!,
    { name: "generate_audio", value_type: "boolean", allowed_values: [], minimum: null, maximum: null, default: true },
  ],
};

afterEach(() => cleanup());

describe("AgentCanvasInlineWorkbench", () => {
  it("moves video audio generation to the footer and preserves the default without writing it", async () => {
    const node = { ...makeNode("video"), parameters: { duration_seconds: 8 } };
    const props = renderWorkbench(node, {
      providerModels: [audioVideoModel], providerDefaultModelRef: audioVideoModel.model_ref,
    });
    const toggle = screen.getByRole("button", { name: "Generate audio" });
    expect(toggle.closest("footer")).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: "Generate audio" })).toBeNull();
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(props.patchNode).not.toHaveBeenCalled();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "Run video node" }));
    await waitFor(() => expect(props.patchNode).toHaveBeenCalledWith(node.node_id, expect.objectContaining({
      parameters: { duration_seconds: 8, generate_audio: false },
    })));
  });

  it.each([false, true])("uses explicit video audio %s rather than the model default", (value) => {
    renderWorkbench({ ...makeNode("video"), parameters: { generate_audio: value } }, {
      providerModels: [audioVideoModel], providerDefaultModelRef: audioVideoModel.model_ref,
    });
    const toggle = screen.getByRole("button", { name: "Generate audio" });
    expect(toggle.getAttribute("aria-pressed")).toBe(String(value));
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe(String(!value));
  });

  it("does not materialize an untouched audio default when running", async () => {
    const node = { ...makeNode("video"), parameters: { duration_seconds: 8 } };
    const props = renderWorkbench(node, {
      providerModels: [audioVideoModel], providerDefaultModelRef: audioVideoModel.model_ref,
    });
    fireEvent.click(screen.getByRole("button", { name: "Run video node" }));
    await waitFor(() => expect(props.onRun).toHaveBeenCalledOnce());
    expect(props.patchNode).not.toHaveBeenCalled();
    expect(props.onRun).toHaveBeenCalledWith(expect.objectContaining({ parameters: { duration_seconds: 8 } }));
  });

  it.each([
    { providerModels: [descriptorVideoModel] },
    { providerModels: [audioVideoModel], providerModelsLoading: true },
    { providerModels: [audioVideoModel], providerModelsError: "Unavailable" },
  ])("keeps unsupported or unknown audio capabilities disabled (%j)", (overrides) => {
    const props = renderWorkbench(makeNode("video"), {
      providerDefaultModelRef: descriptorVideoModel.model_ref, ...overrides,
    });
    const toggle = screen.getByRole("button", { name: "Generate audio" }) as HTMLButtonElement;
    expect(toggle.disabled).toBe(true);
    fireEvent.click(toggle);
    expect(props.patchNode).not.toHaveBeenCalled();
  });

  it("uses the current default model's audio support, not a previous output's model summary", () => {
    const unsupported = { ...descriptorVideoModel, model_ref: "mock:no-audio", display_name: "Silent model" };
    renderWorkbench(withDescriptorVideoModel(makeNode("video")), {
      providerModels: [audioVideoModel, unsupported], providerDefaultModelRef: unsupported.model_ref,
    });
    expect((screen.getByRole("button", { name: "Generate audio" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps audio draft values when switching to an unsupported model and back", () => {
    const unsupported = { ...descriptorVideoModel, model_ref: "mock:no-audio", display_name: "Silent model" };
    renderWorkbench({ ...makeNode("video"), parameters: { generate_audio: true } }, {
      providerModels: [audioVideoModel, unsupported], providerDefaultModelRef: audioVideoModel.model_ref,
    });
    const toggle = screen.getByRole("button", { name: "Generate audio" }) as HTMLButtonElement;
    fireEvent.click(screen.getByLabelText("Choose model"));
    fireEvent.click(screen.getByRole("option", { name: "Silent model", exact: true }));
    expect(toggle.disabled).toBe(true);
    fireEvent.click(toggle);
    fireEvent.click(screen.getByLabelText("Choose model"));
    fireEvent.click(screen.getByRole("option", { name: "Seedance 2.0", exact: true }));
    expect(toggle.disabled).toBe(false);
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
  });

  it.each(["image", "audio"] as const)("does not move %s audio descriptors to the video toolbar", (type) => {
    renderWorkbench(makeNode(type), {
      providerModels: [{ ...audioVideoModel, capability: type }], providerDefaultModelRef: audioVideoModel.model_ref,
    });
    expect(screen.queryByRole("button", { name: "Generate audio" })).toBeNull();
    expect(Boolean(screen.queryByRole("checkbox", { name: "Generate audio" }))).toBe(type === "audio");
  });

  it("keeps image parameters out of the panel without rewriting them or disabling Run for hidden inputs", async () => {
    const node = { ...makeNode("image"), parameters: { duration_seconds: 999, generate_audio: true } };
    const props = renderWorkbench(node, {
      providerModels: [{ ...audioVideoModel, capability: "image" }], providerDefaultModelRef: audioVideoModel.model_ref,
    });
    expect(screen.queryByLabelText("Duration seconds")).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "Generate audio" })).toBeNull();
    expect(screen.queryByText(/Prompt ready/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Run image node" }));
    await waitFor(() => expect(props.onRun).toHaveBeenCalledWith(expect.objectContaining({ parameters: node.parameters })));
    expect(props.patchNode).not.toHaveBeenCalled();
  });

  it("preserves real image Run errors outside the fixed editor layout", async () => {
    renderWorkbench(makeNode("image"), { onRun: vi.fn().mockRejectedValue(new Error("Provider request failed")) });
    fireEvent.click(screen.getByRole("button", { name: "Run image node" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Provider request failed"));
    expect(screen.getByRole("alert").closest(".agent-node-workbench__image-feedback")).toBeTruthy();
    expect(screen.getByLabelText("Generation prompt")).toBeTruthy();
  });

  it.each(["image", "text"] as const)("preserves %s prompt text and conflict recovery without adding status rows", async (type) => {
    const patchNode = vi.fn().mockRejectedValueOnce(new V2ApiError({
      status: 412, code: "workflow_state_conflict", message: "Workflow changed elsewhere.",
      details: {}, violations: [], suggestedActions: [], payload: null,
    })).mockResolvedValue(undefined);
    const props = renderWorkbench(makeNode(type), { patchNode });
    const editor = screen.getByLabelText(type === "image" ? "Generation prompt" : "Text prompt") as HTMLTextAreaElement;
    fireEvent.change(editor, { target: { value: "Keep my local prompt" } });
    fireEvent.blur(editor);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("changed elsewhere"));
    expect(editor.value).toBe("Keep my local prompt");
    expect(screen.getByRole("alert").closest(`.agent-node-workbench__${type}-feedback`)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry local prompt" }));
    await waitFor(() => expect(patchNode).toHaveBeenCalledTimes(2));
    const savedNode = { ...props.node, generation_prompt: "Keep my local prompt", revision: 2 };
    render(<AgentCanvasInlineWorkbench {...props} node={savedNode} workflow={makeWorkflow(savedNode)} />, {
      container: editor.closest("section")!.parentElement!,
    });
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(editor.value).toBe("Keep my local prompt");
    expect(screen.queryByText(/Prompt ready/)).toBeNull();
  });

  it.each(["image", "video", "audio"] as const)("shares the monochrome model picker between image and video nodes (%s)", (type) => {
    renderWorkbench(makeNode(type));
    const trigger = screen.getByLabelText("Choose model");
    const footer = trigger.closest("footer");
    expect(footer?.classList.contains("agent-node-workbench__footer--image")).toBe(type === "image");
    expect(Boolean(trigger.closest(".agent-node-workbench__model-picker--monochrome"))).toBe(type !== "audio");
  });

  it("uses a solid black-gray surface without gradients or backdrop blur", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/workbench/agent-canvas-inline-workbench.css");
    const css = readFileSync(cssPath, "utf8");
    const shellRule = css.match(/^\.agent-node-workbench\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(shellRule).toContain("background: #2a2a2a");
    expect(shellRule).not.toContain("gradient");
    expect(shellRule).toContain("backdrop-filter: none");
  });

  it("expands the outer panel and keeps overflow scrolling inside the prompt editor", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/workbench/agent-canvas-inline-workbench.css");
    const css = readFileSync(cssPath, "utf8");
    const shellRule = css.match(/^\.agent-node-workbench\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(shellRule).toBeDefined();
    expect(shellRule).toContain("height: auto;");
    expect(shellRule).toContain("min-height: 217px;");
    expect(shellRule).toContain("overflow: visible;");
    expect(shellRule).not.toMatch(/overflow-[xy]:\s*(auto|scroll)/);

    const editorRule = css.match(/\.agent-node-workbench__four-line-editor\s*\{([\s\S]*?)\n\}/)?.[1];
    expect(editorRule).toContain("height: 88px;");
    expect(editorRule).toContain("overflow-y: auto;");
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

    expect(screen.queryByText("A warm product portrait for the campaign opening.")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByLabelText("Generation prompt")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Run image node" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it.each([
    ["queued", "Preparing generation prompt"],
    ["working", "Preparing generation prompt"],
    ["failed", "Prompt preparation needs attention"],
    ["superseded", "Prompt preparation was replaced"],
  ] as const)(
    "keeps the generation prompt editable while preparation is %s",
    (preparationStatus, expectedLabel) => {
      const node = {
        ...makeNode("image"),
        generation_prompt: "Keep this user prompt",
        prompt_preparation: {
          status: preparationStatus,
          operation_id: "prompt-operation-1",
          attempt_no: 1,
          context_snapshot_id: "snapshot-1",
          prompt_digest: null,
          error: preparationStatus === "failed"
            ? { code: "prompt_preparation_failed", message: "Preparation failed.", retryable: true }
            : null,
          updated_at: "2026-08-11T10:00:00Z",
        },
      } as CanvasNodeV2;

      renderWorkbench(node);

      const editor = screen.getByLabelText("Generation prompt") as HTMLTextAreaElement;
      expect(editor.value).toBe("Keep this user prompt");
      expect(editor.disabled).toBe(false);
      expect(screen.queryByLabelText("Prompt preparation status")).toBeNull();
      expect(screen.queryByText(expectedLabel)).toBeNull();
    },
  );

  it("keeps a blank manual Draft editable while it waits for user input", () => {
    const node = {
      ...makeNode("image"),
      generation_prompt: null,
      prompt_preparation: {
        status: "waiting_user",
        operation_id: null,
        attempt_no: 0,
        context_snapshot_id: null,
        prompt_digest: null,
        error: null,
        updated_at: "2026-08-11T10:00:00Z",
      },
    } as CanvasNodeV2;

    renderWorkbench(node);

    expect((screen.getByLabelText("Generation prompt") as HTMLTextAreaElement).disabled).toBe(false);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Run image node" })).toBeTruthy();
  });

  it("keeps a waiting-user media node editable without presenting a provider failure", () => {
    const node = {
      ...makeNode("video"),
      summary_prompt: "Please enter a prompt for this generated video.",
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

  it("does not show a prompt hint for a manually created blank Draft", () => {
    const node = {
      ...makeNode("image"),
      summary_prompt: null,
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
    expect(screen.queryByText("Prompt input needed")).toBeNull();
    expect(screen.queryByText("Enter a prompt to continue.")).toBeNull();
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

  it("keeps preparation error presentation for video nodes", () => {
    const node = {
      ...makeNode("video"),
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
    expect(screen.getByRole("alert").textContent).not.toContain("Retryable");
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

  it("uses the persisted Working status to prevent editing a Script", () => {
    const node = makeNode("script", "working");
    const props = renderWorkbench(node);

    expect(screen.getByLabelText("Script content")).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Script node is working" }))
      .toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Script node is working" }));

    expect(props.patchNode).not.toHaveBeenCalled();
    expect(props.onRun).not.toHaveBeenCalled();
  });

  it("uses the persisted Ready status when saving a Script", async () => {
    const node = {
      ...makeNode("script", "ready"),
      structured_content: {},
    } as CanvasNodeV2;
    const props = renderWorkbench(node);

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

  it("uses the persisted Failed status when retrying a Script", async () => {
    const node = {
      ...makeNode("script", "failed"),
      structured_content: {},
      error: {
        code: "provider_timeout",
        message: "The provider timed out.",
        retryable: true,
        actionable_failure: {
          failure_class: "external",
          retry_scope: "execution",
          user_action: "retry",
          retryable: true,
        },
      },
    } as CanvasNodeV2;
    const props = renderWorkbench(node);

    fireEvent.click(screen.getByRole("button", { name: "Retry script node" }));

    await waitFor(() => expect(props.onRun).toHaveBeenCalledWith(
      expect.objectContaining({
        node_id: node.node_id,
        status: "failed",
      }),
    ));
  });

  it("keeps video Prompt Preparation revision actions", () => {
    const node = {
      ...makeNode("video", "draft"),
      prompt_preparation: {
        ...makeNode("image", "draft").prompt_preparation!,
        status: "failed" as const,
        attempt_stage: "failed",
        error: {
          code: "node_prompt_role_contract_invalid",
          message: "Revise the role-specific prompt.",
          retryable: false,
          actionable_failure: {
            failure_class: "deterministic" as const,
            retry_scope: "none" as const,
            user_action: "revise" as const,
            retryable: false,
          },
        },
      },
    } as CanvasNodeV2;
    renderWorkbench(node);

    fireEvent.click(screen.getByRole("button", { name: "Revise generation prompt" }));

    expect(document.activeElement).toBe(screen.getByLabelText("Generation prompt"));
  });

  it("does not invent a Prompt Preparation retry endpoint", () => {
    const node = {
      ...makeNode("image", "draft"),
      prompt_preparation: {
        ...makeNode("image", "draft").prompt_preparation!,
        status: "failed" as const,
        attempt_stage: "failed",
        error: {
          code: "prompt_preparation_failed",
          message: "Prompt preparation failed transiently.",
          retryable: true,
          actionable_failure: {
            failure_class: "external" as const,
            retry_scope: "prompt_preparation" as const,
            user_action: "retry" as const,
            retryable: true,
          },
        },
      },
    } as CanvasNodeV2;
    renderWorkbench(node);

    expect(screen.queryByRole("button", { name: /retry prompt preparation/i })).toBeNull();
    expect(screen.queryByRole("button", { name: "Revise generation prompt" })).toBeNull();
  });

  it("regenerates the same failed Node when the typed action requests regeneration", async () => {
    const node = {
      ...makeNode("image", "failed"),
      error: {
        code: "generated_result_rejected",
        message: "Generate a new result.",
        retryable: false,
        actionable_failure: {
          failure_class: "deterministic" as const,
          retry_scope: "none" as const,
          user_action: "regenerate" as const,
          retryable: false,
        },
      },
    } as CanvasNodeV2;
    const props = renderWorkbench(node);

    fireEvent.click(screen.getByRole("button", { name: "Regenerate image node" }));

    await waitFor(() => expect(props.onRun).toHaveBeenCalledWith(expect.objectContaining({
      node_id: node.node_id,
    })));
  });

  it("prefers exact Execution retry over generic Ready-node regeneration", async () => {
    const node = {
      ...makeNode("video", "ready"),
      output_asset_id: "asset-previous-video",
      latest_attempt: {
        execution_id: "execution-regeneration-2",
        attempt_no: 2,
        status: "failed" as const,
        error: {
          code: "provider_delivery_failed",
          message: "The latest regeneration failed.",
          retryable: true,
          actionable_failure: {
            failure_class: "external" as const,
            retry_scope: "execution" as const,
            user_action: "retry" as const,
            retryable: true,
          },
        },
        updated_at: "2026-09-05T00:00:00Z",
      },
    } as CanvasNodeV2;
    const props = renderWorkbench(node);

    fireEvent.click(screen.getByRole("button", { name: "Retry video node" }));

    await waitFor(() => expect(props.onRun).toHaveBeenCalledWith(expect.objectContaining({
      node_id: node.node_id,
      output_asset_id: "asset-previous-video",
    })));
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

  it.each(["draft", "failed"] as const)("uses a save icon but still generates a %s Text node after flushing", async (status) => {
    const node = makeNode("text", status);
    const props = renderWorkbench(node);
    const button = screen.getByRole("button", { name: "Run text node" });
    expect(button.innerHTML).toBe(renderToStaticMarkup(<SaveIcon />));
    fireEvent.change(screen.getByLabelText("Text prompt"), { target: { value: "Updated text prompt" } });
    fireEvent.click(button);
    await waitFor(() => expect(props.onRun).toHaveBeenCalledTimes(1));
    expect(props.patchNode).toHaveBeenCalledWith(node.node_id, { generation_prompt: "Updated text prompt" }, { coalesce: true });
    expect(props.patchNode.mock.invocationCallOrder[0]).toBeLessThan(props.onRun.mock.invocationCallOrder[0]);
  });

  it("uses a save icon and only saves content for ready Text", async () => {
    const node = makeNode("text", "ready");
    const props = renderWorkbench(node);
    const button = screen.getByRole("button", { name: "Save text changes" });
    expect(button.innerHTML).toBe(renderToStaticMarkup(<SaveIcon />));
    fireEvent.change(screen.getByLabelText("Text content"), { target: { value: "Updated content" } });
    fireEvent.click(button);
    await waitFor(() => expect(props.patchNode).toHaveBeenCalledWith(node.node_id, expect.objectContaining({
      structured_content: { content: "Updated content" },
    })));
    expect(props.onRun).not.toHaveBeenCalled();
  });

  it.each(["queued", "working", "failed", "superseded"] as const)("keeps Text preparation %s out of the editable panel", (status) => {
    const node = makeNode("text");
    renderWorkbench({ ...node, prompt_preparation: { ...node.prompt_preparation!, status } });
    expect(screen.queryByLabelText("Prompt preparation status")).toBeNull();
    expect((screen.getByLabelText("Text prompt") as HTMLTextAreaElement).disabled).toBe(false);
  });

  it("uses the image model menu appearance and default label for Text", () => {
    const model = { ...descriptorVideoModel, capability: "text" as const, display_name: "Text model" };
    renderWorkbench(makeNode("text"), { providerModels: [model], providerDefaultModelRef: model.model_ref });
    const trigger = screen.getByLabelText("Choose model");
    expect(trigger.closest(".agent-node-workbench__model-picker--monochrome")).toBeTruthy();
    expect(trigger.textContent).toBe("Default model · Text model");
    fireEvent.click(trigger);
    expect(screen.getByRole("listbox").classList.contains("agent-node-workbench__model-menu--monochrome")).toBe(true);
    expect(screen.getByRole("option", { name: "Text model" }).querySelector("small")).toBeNull();
  });

  it("keeps real Text Run errors outside the fixed panel body", async () => {
    renderWorkbench(makeNode("text"), { onRun: vi.fn().mockRejectedValue(new Error("Text generation failed")) });
    fireEvent.click(screen.getByRole("button", { name: "Run text node" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Text generation failed"));
    expect(screen.getByRole("alert").closest(".agent-node-workbench__text-feedback")).toBeTruthy();
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
    expect(screen.getByRole("button", { name: "Save World Setting changes" }).innerHTML).toBe(renderToStaticMarkup(<SaveIcon />));
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

  it("flushes a ready media prompt before regenerating the same node", async () => {
    const node = makeNode("image", "ready");
    const props = renderWorkbench(node);

    fireEvent.change(screen.getByLabelText("Generation prompt"), {
      target: { value: "A cinematic amber fragrance film" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Regenerate image node" }));

    await waitFor(() => {
      expect(props.patchNode).toHaveBeenCalledWith(node.node_id, {
        generation_prompt: "A cinematic amber fragrance film",
      }, { coalesce: true });
    });
    expect(props.onRun).toHaveBeenCalledWith(expect.objectContaining({
      node_id: node.node_id,
      generation_prompt: "A cinematic amber fragrance film",
    }));
  });

  it("keeps a ready media node non-runnable while its result is publishing", () => {
    const node = makeNode("image", "ready");
    const runtime: NodeRuntimeV2 = {
      node_id: node.node_id,
      visible_status: "working",
      phase: "publishing",
      execution_id: "execution-rerun",
      provider_task_id: null,
      run_intent_snapshot_id: "snapshot-rerun",
      parameter_compilation_snapshot_id: null,
      effective_parameters: {},
      normalizations: [],
      omitted_optional_inputs: [],
      waiting_reason: null,
      missing_required_source_node_ids: [],
      waiting_for_node_ids: [],
      blocked_by_node_ids: [],
      attempt_no: 2,
      updated_at: "2026-09-04T00:00:00Z",
      error: null,
    };
    const props = renderWorkbench(node, { runtime });

    const regenerate = screen.getByRole("button", { name: "Regenerate image node" });
    expect((regenerate as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(regenerate);
    expect(props.onRun).not.toHaveBeenCalled();
  });

  it("keeps a working media prompt editable and autosaves without allowing another run", async () => {
    const node = makeNode("video", "working");
    const props = renderWorkbench(node);
    const editor = screen.getByLabelText("Generation prompt");

    expect((editor as HTMLTextAreaElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Run video node" }) as HTMLButtonElement).disabled)
      .toBe(true);

    fireEvent.change(editor, {
      target: { value: "Keep the prior framing and add a slower camera move." },
    });
    fireEvent.blur(editor);

    await waitFor(() => expect(props.patchNode).toHaveBeenCalledWith(node.node_id, {
      generation_prompt: "Keep the prior framing and add a slower camera move.",
    }, { coalesce: true }));
    expect(props.onRun).not.toHaveBeenCalled();
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

  it("groups video duration, resolution and ratio beside assets without moving other parameters", async () => {
    const node = withDescriptorVideoModel({ ...makeNode("video"), parameters: { audio_mode: "native" } });
    const props = renderWorkbench(node, {
      providerModels: [{
        ...descriptorVideoModel,
        parameter_descriptors: [
          ...descriptorVideoModel.parameter_descriptors!,
          { name: "resolution", value_type: "enum", allowed_values: ["720p", "1080p"], minimum: null, maximum: null, default: null },
          { name: "aspect_ratio", value_type: "enum", allowed_values: ["16:9", "9:16"], minimum: null, maximum: null, default: null },
          { name: "audio_mode", value_type: "enum", allowed_values: ["native", "silent"], minimum: null, maximum: null, default: null },
        ],
      }],
    });
    const toolbar = screen.getByRole("button", { name: "Choose asset references" }).closest(".agent-node-workbench__video-toolbar");
    expect(toolbar).toBeTruthy();
    const model = screen.getByLabelText("Choose model");
    expect(toolbar?.contains(model)).toBe(true);
    expect(model.compareDocumentPosition(screen.getByLabelText("Duration seconds")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    for (const name of ["Duration seconds", "Resolution", "Aspect ratio"]) {
      expect(screen.getAllByLabelText(name)).toHaveLength(1);
      expect(toolbar?.contains(screen.getByLabelText(name))).toBe(true);
    }
    expect(screen.getByLabelText("Audio mode").closest("footer")).toBeNull();
    fireEvent.change(screen.getByLabelText("Duration seconds"), { target: { value: "8" } });
    fireEvent.click(screen.getByLabelText("Resolution"));
    fireEvent.click(screen.getByRole("option", { name: "1080p" }));
    fireEvent.click(screen.getByLabelText("Aspect ratio"));
    fireEvent.click(screen.getByRole("option", { name: "9:16" }));
    fireEvent.click(screen.getByRole("button", { name: "Run video node" }));
    await waitFor(() => expect(props.patchNode).toHaveBeenCalledWith(node.node_id, expect.objectContaining({
      parameters: { duration_seconds: 8, resolution: "1080p", aspect_ratio: "9:16", audio_mode: "native" },
    })));
  });

  it("migrates legacy video duration parameters before running an existing node", async () => {
    const node = withDescriptorVideoModel({
      ...makeNode("video"),
      generation_prompt: "Animate the supplied references.",
      parameters: {
        requested_duration_seconds: 0,
        effective_duration_seconds: 15,
      },
    });
    const props = renderWorkbench(node, { providerModels: [descriptorVideoModel] });

    expect((screen.getByLabelText("Duration seconds") as HTMLInputElement).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Run video node" }));

    await waitFor(() => {
      expect(props.patchNode).toHaveBeenCalledWith(node.node_id, expect.objectContaining({
        parameters: {},
      }));
    });
    expect(props.onRun).toHaveBeenCalledWith(node);
  });

  it("preserves requested video durations above the provider limit under the canonical key", async () => {
    const node = withDescriptorVideoModel({
      ...makeNode("video"),
      generation_prompt: "Animate the supplied references.",
      parameters: { requested_duration_seconds: 30 },
    });
    const props = renderWorkbench(node, { providerModels: [descriptorVideoModel] });
    const duration = screen.getByLabelText("Duration seconds");

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

  it("preserves a fractional integer parameter for correction and blocks the run", async () => {
    const node = withDescriptorVideoModel({
      ...makeNode("video"),
      generation_prompt: "Animate the supplied references.",
    });
    const props = renderWorkbench(node, { providerModels: [descriptorVideoModel] });
    const duration = screen.getByLabelText("Duration seconds");

    fireEvent.change(duration, { target: { value: "20.5" } });
    const run = screen.getByRole("button", { name: "Run video node" });

    expect(screen.getByText("Enter a whole number.")).toBeTruthy();
    expect(run).toHaveProperty("disabled", true);
    expect(props.patchNode).not.toHaveBeenCalled();
    expect(props.onRun).not.toHaveBeenCalled();
  });

  it("does not invent a duration control when the selected model declares no descriptor", () => {
    const node = makeNode("video");
    renderWorkbench(node, { providerModels: [] });

    expect(screen.queryByLabelText("Duration seconds")).toBeNull();
    expect(screen.queryByLabelText("Requested video duration")).toBeNull();
  });

  it("uses the authoritative installation default to render model descriptors", () => {
    renderWorkbench(makeNode("video"), {
      providerModels: [descriptorVideoModel],
      providerDefaultModelRef: descriptorVideoModel.model_ref,
    });

    expect(screen.getByLabelText("Duration seconds")).toBeTruthy();
  });

  it.each(["image", "video", "audio"] as const)("omits model reference policy information from the %s workbench", (type) => {
    const node = makeNode(type);
    const model: ProviderModelSummaryV1 = {
      ...descriptorVideoModel,
      capability: type,
      reference_policy: {
        max_images: 0,
        modes: [{ mode: "text_only", max_references: 0, allowed_roles: [] }],
      },
    };
    renderWorkbench(node, {
      workflow: makeReferenceWorkflow(node),
      providerModels: [model],
      providerDefaultModelRef: model.model_ref,
    });

    expect(screen.queryByRole("region", { name: "Model reference policy" })).toBeNull();
    expect(screen.queryByText("Reference inputs")).toBeNull();
    expect(screen.queryByText("Text only")).toBeNull();
    expect(screen.getByRole("textbox", { name: "Generation prompt" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Character board reference" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Choose asset references" })).toBeTruthy();
    expect(screen.getByRole("button", { name: `Run ${type} node` })).toBeTruthy();
    expect(Boolean(screen.queryByLabelText("Duration seconds"))).toBe(type !== "image");
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
