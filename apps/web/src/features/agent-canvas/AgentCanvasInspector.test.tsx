import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../types-v2.ts";
import type { ProviderInputsResolvedState } from "./runtime/providerInputsResolved.ts";
import { AgentCanvasInspector } from "./AgentCanvasInspector.tsx";

function imageNode(prompt: string, revision: number): CanvasNodeV2 {
  return {
    node_id: "image-1",
    workflow_id: "workflow-1",
    node_type: "image",
    semantic_role: "generic_image",
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
    video_skill_run_id: null,
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

    expect((screen.getByLabelText("Generation prompt") as HTMLTextAreaElement).value)
      .toBe("Unsaved local prompt");
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
      semantic_role: "advertising_script",
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
      semantic_role: "product",
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

  it("does not offer Run for a Ready Script document", () => {
    const current: CanvasNodeV2 = {
      ...imageNode("", 2),
      node_id: "script-ready",
      node_type: "script",
      semantic_role: "advertising_script",
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

  it("shows complete ordered Storyboard and Scene Design Board inputs", () => {
    const target: CanvasNodeV2 = {
      ...imageNode("Animate the storyboard", 3),
      node_id: "video-1",
      node_type: "video",
      semantic_role: "storyboard_video_segment",
      title: "Storyboard video",
    };
    const storyboard: CanvasNodeV2 = {
      ...imageNode("Storyboard grid", 2),
      node_id: "image-storyboard",
      semantic_role: "storyboard_grid",
      title: "Storyboard Grid",
      status: "ready",
      output_asset_id: "asset-storyboard",
    };
    const scene: CanvasNodeV2 = {
      ...imageNode("Scene board", 2),
      node_id: "image-scene",
      semantic_role: "scene_design_board",
      title: "Scene Design Board",
      status: "ready",
      output_asset_id: "asset-scene",
    };
    const currentWorkflow: AgentCanvasWorkflowV2 = {
      ...workflow(target),
      nodes: [target, scene, storyboard],
      bindings: [
        {
          binding_id: "binding-scene",
          workflow_id: "workflow-1",
          source: { kind: "node", node_id: scene.node_id },
          target_node_id: target.node_id,
          binding_kind: "image_reference",
          input_role: "visual_reference",
          required: false,
          display_order: 2,
          created_at: "2026-07-30T00:00:00Z",
        },
        {
          binding_id: "binding-storyboard",
          workflow_id: "workflow-1",
          source: { kind: "node", node_id: storyboard.node_id },
          target_node_id: target.node_id,
          binding_kind: "image_reference",
          input_role: "visual_reference",
          required: true,
          display_order: 1,
          created_at: "2026-07-30T00:00:00Z",
        },
      ],
      assets: [
        {
          asset_id: "asset-storyboard",
          media_type: "image",
          source_type: "generated",
          display_name: "Storyboard Grid",
          mime_type: "image/png",
          status: "ready",
          preview_url: "/storyboard-grid.png",
          media_url: "/storyboard-grid.png",
          width: 1536,
          height: 1024,
          duration_seconds: null,
          checksum: "storyboard-checksum",
          source_semantic_role: "storyboard_grid",
        },
        {
          asset_id: "asset-scene",
          media_type: "image",
          source_type: "generated",
          display_name: "Scene Design Board",
          mime_type: "image/png",
          status: "ready",
          preview_url: "/scene-board.png",
          media_url: "/scene-board.png",
          width: 1536,
          height: 1024,
          duration_seconds: null,
          checksum: "scene-checksum",
          source_semantic_role: "scene_design_board",
        },
      ],
    };
    const resolvedInputs: ProviderInputsResolvedState = {
      node_id: target.node_id,
      model_id: "seedance-2",
      input_counts: { image: 2 },
      inputs: [
        {
          binding_id: "binding-storyboard",
          asset_id: "asset-storyboard",
          source_node_id: null,
          source_type: null,
          media_type: "image",
          input_role: "visual_reference",
          source_semantic_role: "storyboard_grid",
          reference_purpose: "storyboard_sequence",
          required: true,
          display_order: 1,
          label: "Image 1",
        },
        {
          binding_id: "binding-scene",
          asset_id: "asset-scene",
          source_node_id: null,
          source_type: null,
          media_type: "image",
          input_role: "visual_reference",
          source_semantic_role: "scene_design_board",
          reference_purpose: "scene_reference",
          required: false,
          display_order: 2,
          label: "Image 2",
        },
      ],
      requested_duration_seconds: 30,
      effective_duration_seconds: 15,
      normalizations: ["duration_clamped_to_provider_limit"],
      omitted_optional_inputs: [],
      event_seq: 21,
    };

    render(
      <AgentCanvasInspector
        workflow={currentWorkflow}
        node={target}
        resolvedInputs={resolvedInputs}
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

    const section = screen.getByRole("region", { name: "Connected inputs" });
    const inputs = within(section).getAllByTestId("agent-canvas-connected-input");
    expect(inputs).toHaveLength(2);
    expect(within(inputs[0]!).getByText("Image 1")).toBeTruthy();
    expect(within(inputs[0]!).getByText("Storyboard Grid")).toBeTruthy();
    expect(within(inputs[0]!).getByText("Required")).toBeTruthy();
    expect(within(inputs[1]!).getByText("Image 2")).toBeTruthy();
    expect(within(inputs[1]!).getByText("Scene Design Board")).toBeTruthy();
    expect(within(inputs[1]!).getByText("Optional")).toBeTruthy();
    expect((within(inputs[0]!).getByRole("img") as HTMLImageElement).src)
      .toContain("/storyboard-grid.png");
    expect((within(inputs[1]!).getByRole("img") as HTMLImageElement).src)
      .toContain("/scene-board.png");
    expect(screen.getByText(/adjusted to a 15-second clip/i)).toBeTruthy();
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
