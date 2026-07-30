import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { V2ApiError } from "../../api/v2Client.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../types-v2.ts";
import { V2_AUTHORING_DRAFT_DISCARDED_EVENT } from "../../api/v2AuthoringConflictEvents.ts";
import { AgentCanvasInspector } from "./AgentCanvasInspector.tsx";

function imageNode(prompt: string, revision: number): CanvasNodeV2 {
  return {
    node_id: "image-1",
    workflow_id: "workflow-1",
    node_type: "image",
    creative_role: "general_image",
    role_contract_version: "ad-media-role-v1",
    title: "Image",
    status: "draft",
    summary_prompt: null,
    generation_prompt: prompt,
    structured_content: {},
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position: { x: 0, y: 0 },
    revision,
    error: null,
    variation_draft: null,
    created_at: "2026-07-28T00:00:00Z",
    updated_at: "2026-07-28T00:00:00Z",
  };
}

function workflow(node: CanvasNodeV2): AgentCanvasWorkflowV2 {
  const asset: ProjectAssetSummaryV2 | null = node.output_asset_id
    ? {
        asset_id: node.output_asset_id,
        media_type: node.node_type === "image" ? "image" : "video",
        source_type: "generated",
        display_name: node.title,
        mime_type: node.node_type === "image" ? "image/png" : "video/mp4",
        status: "ready",
        preview_url: "/preview",
        media_url: "/media",
        width: 1024,
        height: 1024,
        duration_seconds: null,
        checksum: "checksum",
      }
    : null;
  return {
    workflow_id: "workflow-1",
    project_id: "project-1",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: node.revision,
    layout_revision: 1,
    nodes: [node],
    bindings: [],
    assets: asset ? [asset] : [],
  };
}

afterEach(cleanup);

describe("AgentCanvasInspector", () => {
  it("preserves a dirty prompt when SSE refreshes the same node", () => {
    const first = imageNode("Server prompt", 1);
    const props = {
      patchNode: vi.fn(),
      onRun: vi.fn(),
      onSaveVariation: vi.fn(),
      onDiscardVariation: vi.fn(),
      onMaterializeVariation: vi.fn(),
      onSaveImageToLibrary: vi.fn(),
      onDelete: vi.fn(),
      onOpenEditing: vi.fn(),
      onClose: vi.fn(),
    };
    const view = render(
      <AgentCanvasInspector workflow={workflow(first)} node={first} {...props} />,
    );
    const prompt = screen.getByLabelText("Generation prompt");
    fireEvent.change(prompt, { target: { value: "Unsaved local prompt" } });

    const refreshed = imageNode("Refreshed server prompt", 2);
    view.rerender(
      <AgentCanvasInspector workflow={workflow(refreshed)} node={refreshed} {...props} />,
    );
    fireEvent(window, new CustomEvent(V2_AUTHORING_DRAFT_DISCARDED_EVENT, {
      detail: {
        target: { resource: "workflow", id: "workflow-1" },
        operationPath: "/workflows/workflow-1/bindings/binding-2",
        action: "discard",
      },
    }));

    expect((screen.getByLabelText("Generation prompt") as HTMLTextAreaElement).value)
      .toBe("Unsaved local prompt");
  });

  it("discards a dirty prompt after the user resolves a workflow conflict with Discard", () => {
    const first = imageNode("Server prompt", 1);
    const props = {
      patchNode: vi.fn(),
      onRun: vi.fn(),
      onSaveVariation: vi.fn(),
      onDiscardVariation: vi.fn(),
      onMaterializeVariation: vi.fn(),
      onSaveImageToLibrary: vi.fn(),
      onDelete: vi.fn(),
      onOpenEditing: vi.fn(),
      onClose: vi.fn(),
    };
    const view = render(
      <AgentCanvasInspector workflow={workflow(first)} node={first} {...props} />,
    );
    fireEvent.change(screen.getByLabelText("Generation prompt"), {
      target: { value: "Unsaved local prompt" },
    });

    const refreshed = imageNode("Latest server prompt", 2);
    view.rerender(
      <AgentCanvasInspector workflow={workflow(refreshed)} node={refreshed} {...props} />,
    );
    fireEvent(window, new CustomEvent(V2_AUTHORING_DRAFT_DISCARDED_EVENT, {
      detail: {
        target: { resource: "workflow", id: "workflow-1" },
        operationPath: "/workflows/workflow-1/nodes/image-1",
        action: "discard",
      },
    }));

    expect((screen.getByLabelText("Generation prompt") as HTMLTextAreaElement).value)
      .toBe("Latest server prompt");
  });

  it("saves a dirty prompt before running the node", async () => {
    const current = imageNode("Server prompt", 1);
    const patchNode = vi.fn().mockResolvedValue(undefined);
    const onRun = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentCanvasInspector
        workflow={workflow(current)}
        node={current}
        patchNode={patchNode}
        onRun={onRun}
        onSaveVariation={vi.fn()}
        onDiscardVariation={vi.fn()}
        onMaterializeVariation={vi.fn()}
        onSaveImageToLibrary={vi.fn()}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Generation prompt"), {
      target: { value: "Generate with this prompt" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run node" }));

    await waitFor(() => expect(onRun).toHaveBeenCalledOnce());
    expect(patchNode).toHaveBeenCalledWith("image-1", expect.objectContaining({
      generation_prompt: "Generate with this prompt",
    }));
    expect(patchNode.mock.invocationCallOrder[0]).toBeLessThan(onRun.mock.invocationCallOrder[0]!);
  });

  it("edits the generation prompt for a draft Script before running it", async () => {
    const current: CanvasNodeV2 = {
      ...imageNode("Write a concise launch film", 1),
      node_id: "script-1",
      node_type: "script",
      creative_role: "script",
      title: "Script",
      structured_content: {},
    };
    const patchNode = vi.fn().mockResolvedValue(undefined);
    const onRun = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentCanvasInspector
        workflow={workflow(current)}
        node={current}
        patchNode={patchNode}
        onRun={onRun}
        onSaveVariation={vi.fn()}
        onDiscardVariation={vi.fn()}
        onMaterializeVariation={vi.fn()}
        onSaveImageToLibrary={vi.fn()}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Generation prompt"), {
      target: { value: "Write a cinematic 30-second launch script" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run node" }));

    await waitFor(() => expect(onRun).toHaveBeenCalledOnce());
    expect(patchNode).toHaveBeenCalledWith("script-1", expect.objectContaining({
      generation_prompt: "Write a cinematic 30-second launch script",
    }));
  });

  it("saves a ready image to My Assets with an explicit category and display name", async () => {
    const current = {
      ...imageNode("Generated image", 2),
      status: "ready" as const,
      creative_role: "product",
      output_asset_id: "asset-image-1",
    };
    const onSaveImageToLibrary = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentCanvasInspector
        workflow={workflow(current)}
        node={current}
        patchNode={vi.fn()}
        onRun={vi.fn()}
        onSaveVariation={vi.fn()}
        onDiscardVariation={vi.fn()}
        onMaterializeVariation={vi.fn()}
        onSaveImageToLibrary={onSaveImageToLibrary}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect((screen.getByLabelText("Library category") as HTMLSelectElement).value).toBe("prop");
    fireEvent.change(screen.getByLabelText("Library name"), {
      target: { value: "Hero product" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save image to My Assets" }));

    await waitFor(() => expect(onSaveImageToLibrary).toHaveBeenCalledWith(
      "asset-image-1",
      {
        category: "prop",
        display_name: "Hero product",
      },
    ));
  });

  it("saves a compatible provider model selected for a Draft media node", async () => {
    const current = imageNode("Generate product", 1);
    const patchNode = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentCanvasInspector
        workflow={workflow(current)}
        node={current}
        patchNode={patchNode}
        providerCapabilities={[{
          provider: "volcengine",
          model_id: "image-model-v2",
          output_type: "image",
          accepted_input_types: ["text", "image"],
          max_references: 8,
          supported_parameters: ["aspect_ratio"],
          supported_aspect_ratios: ["1:1", "16:9"],
          duration_range_seconds: null,
          pixel_bounds: [512, 4096],
          available: true,
          unavailable_reason: null,
          supports_native_audio: false,
        }]}
        onRun={vi.fn()}
        onSaveVariation={vi.fn()}
        onDiscardVariation={vi.fn()}
        onMaterializeVariation={vi.fn()}
        onSaveImageToLibrary={vi.fn()}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Provider model"), {
      target: { value: "image-model-v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save node" }));

    await waitFor(() => expect(patchNode).toHaveBeenCalledWith(
      "image-1",
      expect.objectContaining({ model_id: "image-model-v2" }),
    ));
  });

  it("shows every persisted input and edits its role and dependency flags", async () => {
    const current = imageNode("Generate product", 1);
    const source = {
      ...imageNode("Reference", 1),
      node_id: "source-image",
      title: "Storyboard Grid",
      status: "ready" as const,
    };
    const currentWorkflow = workflow(current);
    currentWorkflow.nodes.push(source);
    currentWorkflow.bindings.push({
      binding_id: "binding-reference",
      workflow_id: currentWorkflow.workflow_id,
      source: { kind: "node_output", source_node_id: source.node_id },
      target_node_id: current.node_id,
      input_role: "image_reference",
      required: true,
      enabled: true,
      order: 0,
      label: "Image 1",
      metadata: {},
      created_at: "2026-07-30T08:00:00Z",
      updated_at: "2026-07-30T08:00:00Z",
    });
    const patchBinding = vi.fn().mockResolvedValue(undefined);
    const deleteBinding = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentCanvasInspector
        workflow={currentWorkflow}
        node={current}
        patchNode={vi.fn()}
        patchBinding={patchBinding}
        deleteBinding={deleteBinding}
        onRun={vi.fn()}
        onSaveVariation={vi.fn()}
        onDiscardVariation={vi.fn()}
        onMaterializeVariation={vi.fn()}
        onSaveImageToLibrary={vi.fn()}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Image 1")).toBeTruthy();
    expect(screen.getByText("Storyboard Grid")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Input role"), {
      target: { value: "text_context" },
    });
    await waitFor(() => expect(patchBinding).toHaveBeenCalledWith(
      "binding-reference",
      { input_role: "text_context" },
    ));

    fireEvent.click(screen.getByLabelText("Required"));
    await waitFor(() => expect(patchBinding).toHaveBeenCalledWith(
      "binding-reference",
      { required: false },
    ));

    fireEvent.click(screen.getByRole("button", { name: "Remove Image 1" }));
    await waitFor(() => expect(deleteBinding).toHaveBeenCalledWith("binding-reference"));
  });

  it("shows provider_input_unsupported errors returned while saving a Draft", async () => {
    const current = imageNode("Generate product", 1);
    const patchNode = vi.fn().mockRejectedValue(new V2ApiError({
      status: 422,
      code: "provider_input_unsupported",
      message: "The selected model does not accept video input.",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }));
    render(
      <AgentCanvasInspector
        workflow={workflow(current)}
        node={current}
        patchNode={patchNode}
        onRun={vi.fn()}
        onSaveVariation={vi.fn()}
        onDiscardVariation={vi.fn()}
        onMaterializeVariation={vi.fn()}
        onSaveImageToLibrary={vi.fn()}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Save node" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Provider input unsupported: The selected model does not accept video input.",
    );
  });

  it("saves a compatible provider model selected for a Draft Script node", async () => {
    const current: CanvasNodeV2 = {
      ...imageNode("Write the launch script", 1),
      node_id: "script-1",
      node_type: "script",
      creative_role: "script",
      title: "Script",
    };
    const patchNode = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentCanvasInspector
        workflow={workflow(current)}
        node={current}
        patchNode={patchNode}
        providerCapabilities={[{
          provider: "openai",
          model_id: "script-model-v2",
          output_type: "script",
          accepted_input_types: ["text"],
          max_references: 0,
          reference_limits: {},
          supported_parameters: [],
          supported_aspect_ratios: [],
          duration_range_seconds: null,
          pixel_bounds: null,
          available: true,
          unavailable_reason: null,
          supports_native_audio: false,
        }]}
        onRun={vi.fn()}
        onSaveVariation={vi.fn()}
        onDiscardVariation={vi.fn()}
        onMaterializeVariation={vi.fn()}
        onSaveImageToLibrary={vi.fn()}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Provider model"), {
      target: { value: "script-model-v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save node" }));

    await waitFor(() => expect(patchNode).toHaveBeenCalledWith(
      "script-1",
      expect.objectContaining({ model_id: "script-model-v2" }),
    ));
  });

  it("preserves a Video request above 15 seconds and shows the backend effective duration", async () => {
    const current: CanvasNodeV2 = {
      ...imageNode("A city night sequence", 1),
      node_id: "video-1",
      node_type: "video",
      creative_role: "general_video",
      title: "Video",
      parameters: {
        requested_duration_seconds: 20,
        effective_duration_seconds: 15,
        native_audio: true,
      },
    };
    const patchNode = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentCanvasInspector
        workflow={workflow(current)}
        node={current}
        patchNode={patchNode}
        providerCapabilities={[{
          provider: "volcengine",
          model_id: "seedance-v1",
          output_type: "video",
          accepted_input_types: ["text", "image", "video", "audio"],
          max_references: 8,
          reference_limits: { image: 4, video: 1, audio: 1 },
          supported_parameters: ["duration_seconds"],
          supported_aspect_ratios: ["16:9"],
          duration_range_seconds: [1, 15],
          pixel_bounds: null,
          available: true,
          unavailable_reason: null,
          supports_native_audio: true,
        }]}
        onRun={vi.fn()}
        onSaveVariation={vi.fn()}
        onDiscardVariation={vi.fn()}
        onMaterializeVariation={vi.fn()}
        onSaveImageToLibrary={vi.fn()}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect((screen.getByLabelText("Requested duration (seconds)") as HTMLInputElement).value).toBe("20");
    expect(screen.getByText("Effective duration: 15s")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Requested duration (seconds)"), {
      target: { value: "24" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save node" }));

    await waitFor(() => expect(patchNode).toHaveBeenCalledWith(
      "video-1",
      expect.objectContaining({
        parameters: expect.objectContaining({ requested_duration_seconds: 24 }),
      }),
    ));
    expect(screen.queryByText(/BGM/)).toBeNull();
  });

  it("does not offer Run for a Ready Script document", () => {
    const current: CanvasNodeV2 = {
      ...imageNode("", 2),
      node_id: "script-ready",
      node_type: "script",
      creative_role: "script",
      title: "Approved script",
      status: "ready",
      structured_content: { content: "Open on the product at sunrise." },
    };
    render(
      <AgentCanvasInspector
        workflow={workflow(current)}
        node={current}
        patchNode={vi.fn()}
        onRun={vi.fn()}
        onSaveVariation={vi.fn()}
        onDiscardVariation={vi.fn()}
        onMaterializeVariation={vi.fn()}
        onSaveImageToLibrary={vi.fn()}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Run node" })).toBeNull();
  });

  it("rehydrates a canonical Ready variation and saves it before generating only a sibling", async () => {
    const current: CanvasNodeV2 = {
      ...imageNode("Immutable source prompt", 3),
      status: "ready",
      output_asset_id: "asset-source-1",
      variation_draft: {
        source_node_id: "image-1",
        source_node_revision: 3,
        title: "Night variation",
        generation_prompt: "A night-time product portrait.",
        model_id: "image-model-v2",
        parameters: { aspect_ratio: "1:1" },
        variation_revision: 2,
        created_at: "2026-07-29T03:00:00Z",
        updated_at: "2026-07-29T03:02:00Z",
      },
    };
    const onSaveVariation = vi.fn().mockResolvedValue(undefined);
    const onMaterializeVariation = vi.fn().mockResolvedValue(null);
    render(
      <AgentCanvasInspector
        workflow={workflow(current)}
        node={current}
        patchNode={vi.fn()}
        onRun={vi.fn()}
        onSaveVariation={onSaveVariation}
        onDiscardVariation={vi.fn()}
        onMaterializeVariation={onMaterializeVariation}
        onSaveImageToLibrary={vi.fn()}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    const prompt = screen.getByLabelText("Generation prompt") as HTMLTextAreaElement;
    expect(prompt.disabled).toBe(false);
    expect(prompt.value).toBe("A night-time product portrait.");
    fireEvent.change(prompt, { target: { value: "A brighter moonlit portrait." } });
    fireEvent.click(screen.getByRole("button", { name: "Generate variation" }));

    await waitFor(() => expect(onMaterializeVariation).toHaveBeenCalledOnce());
    expect(onSaveVariation).toHaveBeenCalledWith("image-1", {
      title: "Night variation",
      generation_prompt: "A brighter moonlit portrait.",
      model_id: "image-model-v2",
      parameters: { aspect_ratio: "1:1" },
    });
    expect(onMaterializeVariation).toHaveBeenCalledWith(current, "generate");
    expect(onSaveVariation.mock.invocationCallOrder[0])
      .toBeLessThan(onMaterializeVariation.mock.invocationCallOrder[0]!);
    expect(current.generation_prompt).toBe("Immutable source prompt");
    expect(current.output_asset_id).toBe("asset-source-1");
  });

  it("discards a persisted Ready variation without mutating the source node", async () => {
    const current: CanvasNodeV2 = {
      ...imageNode("Immutable source prompt", 3),
      status: "ready",
      output_asset_id: "asset-source-1",
      variation_draft: {
        source_node_id: "image-1",
        source_node_revision: 3,
        title: "Discard me",
        generation_prompt: "Temporary prompt.",
        model_id: null,
        parameters: {},
        variation_revision: 1,
        created_at: "2026-07-29T03:00:00Z",
        updated_at: "2026-07-29T03:00:00Z",
      },
    };
    const onDiscardVariation = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentCanvasInspector
        workflow={workflow(current)}
        node={current}
        patchNode={vi.fn()}
        onRun={vi.fn()}
        onSaveVariation={vi.fn()}
        onDiscardVariation={onDiscardVariation}
        onMaterializeVariation={vi.fn()}
        onSaveImageToLibrary={vi.fn()}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Discard variation draft" }));

    await waitFor(() => expect(onDiscardVariation).toHaveBeenCalledWith("image-1"));
    expect(current.generation_prompt).toBe("Immutable source prompt");
  });
});
