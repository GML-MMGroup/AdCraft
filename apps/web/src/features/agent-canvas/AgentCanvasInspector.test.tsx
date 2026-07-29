import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../types-v2.ts";
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
      onGenerateVariation: vi.fn(),
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
        onGenerateVariation={vi.fn()}
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
        onGenerateVariation={vi.fn()}
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
        onGenerateVariation={vi.fn()}
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
        onGenerateVariation={vi.fn()}
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
        onGenerateVariation={vi.fn()}
        onSaveImageToLibrary={vi.fn()}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Run node" })).toBeNull();
  });

  it("edits a Ready image variation and generates without patching the source", async () => {
    const source: CanvasNodeV2 = {
      ...imageNode("Original prompt", 3),
      status: "ready",
      output_asset_id: "asset-image-1",
      model_id: "image-model-v1",
      parameters: { aspect_ratio: "1:1" },
    };
    const patchNode = vi.fn();
    const onGenerateVariation = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentCanvasInspector
        workflow={workflow(source)}
        node={source}
        patchNode={patchNode}
        providerCapabilities={[{
          provider: "volcengine",
          model_id: "image-model-v2",
          output_type: "image",
          accepted_input_types: ["text", "image"],
          max_references: 8,
          supported_parameters: ["aspect_ratio"],
          supported_aspect_ratios: ["1:1", "3:4"],
          duration_range_seconds: null,
          pixel_bounds: [512, 4096],
          available: true,
          unavailable_reason: null,
          supports_native_audio: false,
        }]}
        onRun={vi.fn()}
        onGenerateVariation={onGenerateVariation}
        onSaveImageToLibrary={vi.fn()}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.queryByText("Create editable draft")).toBeNull();
    expect((screen.getByLabelText("Generation prompt") as HTMLTextAreaElement).disabled).toBe(false);
    expect((screen.getByLabelText("Provider model") as HTMLSelectElement).disabled).toBe(false);

    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Alternative hero" },
    });
    fireEvent.change(screen.getByLabelText("Generation prompt"), {
      target: { value: "A cleaner premium alternative." },
    });
    fireEvent.change(screen.getByLabelText("Provider model"), {
      target: { value: "image-model-v2" },
    });
    fireEvent.change(screen.getByLabelText("Aspect ratio"), {
      target: { value: "3:4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate variation" }));

    await waitFor(() => expect(onGenerateVariation).toHaveBeenCalledWith(source, {
      title: "Alternative hero",
      generationPrompt: "A cleaner premium alternative.",
      modelId: "image-model-v2",
      parameters: { aspect_ratio: "3:4" },
    }));
    expect(patchNode).not.toHaveBeenCalled();
  });

  it.each(["video", "audio"] as const)(
    "keeps Ready %s provider and duration controls editable",
    (nodeType) => {
      const source: CanvasNodeV2 = {
        ...imageNode(`Generate ${nodeType}`, 2),
        node_id: `${nodeType}-1`,
        node_type: nodeType,
        semantic_role: `${nodeType}_hero`,
        status: "ready",
        output_asset_id: `${nodeType}-asset`,
        model_id: `${nodeType}-model`,
        parameters: { duration_seconds: 8 },
      };
      render(
        <AgentCanvasInspector
          workflow={workflow(source)}
          node={source}
          patchNode={vi.fn()}
          providerCapabilities={[{
            provider: nodeType === "audio" ? "tianpuyue" : "volcengine",
            model_id: `${nodeType}-model`,
            output_type: nodeType,
            accepted_input_types: ["text"],
            max_references: 0,
            supported_parameters: ["duration_seconds"],
            supported_aspect_ratios: [],
            duration_range_seconds: [1, 12],
            pixel_bounds: null,
            available: true,
            unavailable_reason: null,
            supports_native_audio: false,
          }]}
          onRun={vi.fn()}
          onGenerateVariation={vi.fn()}
          onSaveImageToLibrary={vi.fn()}
          onDelete={vi.fn()}
          onOpenEditing={vi.fn()}
          onClose={vi.fn()}
        />,
      );

      expect((screen.getByLabelText("Generation prompt") as HTMLTextAreaElement).disabled).toBe(false);
      expect((screen.getByLabelText("Provider model") as HTMLSelectElement).disabled).toBe(false);
      expect((screen.getByLabelText("Duration (seconds)") as HTMLInputElement).disabled).toBe(false);
    },
  );

  it("preserves a dirty Ready variation during refresh and resets for a new source", () => {
    const source: CanvasNodeV2 = {
      ...imageNode("Original source prompt", 2),
      status: "ready",
      output_asset_id: "asset-image-1",
    };
    const props = {
      patchNode: vi.fn(),
      onRun: vi.fn(),
      onGenerateVariation: vi.fn(),
      onSaveImageToLibrary: vi.fn(),
      onDelete: vi.fn(),
      onOpenEditing: vi.fn(),
      onClose: vi.fn(),
    };
    const view = render(
      <AgentCanvasInspector workflow={workflow(source)} node={source} {...props} />,
    );
    fireEvent.change(screen.getByLabelText("Generation prompt"), {
      target: { value: "Dirty variation prompt" },
    });

    const refreshed = {
      ...source,
      generation_prompt: "Canonical refresh prompt",
      revision: 3,
    };
    view.rerender(
      <AgentCanvasInspector workflow={workflow(refreshed)} node={refreshed} {...props} />,
    );
    expect((screen.getByLabelText("Generation prompt") as HTMLTextAreaElement).value)
      .toBe("Dirty variation prompt");

    const anotherSource = {
      ...source,
      node_id: "image-2",
      generation_prompt: "Another source prompt",
    };
    view.rerender(
      <AgentCanvasInspector workflow={workflow(anotherSource)} node={anotherSource} {...props} />,
    );
    expect((screen.getByLabelText("Generation prompt") as HTMLTextAreaElement).value)
      .toBe("Another source prompt");
  });

  it("prevents duplicate variation generation while the first action is pending", async () => {
    const source: CanvasNodeV2 = {
      ...imageNode("Original prompt", 2),
      status: "ready",
      output_asset_id: "asset-image-1",
    };
    let resolveGenerate!: () => void;
    const onGenerateVariation = vi.fn(() => new Promise<void>((resolve) => {
      resolveGenerate = resolve;
    }));
    render(
      <AgentCanvasInspector
        workflow={workflow(source)}
        node={source}
        patchNode={vi.fn()}
        onRun={vi.fn()}
        onGenerateVariation={onGenerateVariation}
        onSaveImageToLibrary={vi.fn()}
        onDelete={vi.fn()}
        onOpenEditing={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    const generate = screen.getByRole("button", { name: "Generate variation" });
    fireEvent.click(generate);
    fireEvent.click(generate);

    expect(onGenerateVariation).toHaveBeenCalledTimes(1);
    expect((generate as HTMLButtonElement).disabled).toBe(true);
    resolveGenerate();
    await waitFor(() => expect((generate as HTMLButtonElement).disabled).toBe(false));
  });
});
