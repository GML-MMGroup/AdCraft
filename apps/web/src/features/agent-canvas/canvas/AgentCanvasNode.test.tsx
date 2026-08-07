import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  CanvasNodeStatusV2,
  CanvasNodeTypeV2,
  CanvasNodeV2,
  NodeRuntimeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import {
  AgentCanvasNodeCard,
  AgentCanvasNodeRenderer,
  type AgentCanvasNodeData,
} from "./AgentCanvasNode.tsx";

const updateNodeInternals = vi.hoisted(() => vi.fn());

vi.mock("@xyflow/react", async () => {
  const actual = await vi.importActual<typeof import("@xyflow/react")>("@xyflow/react");
  return {
    ...actual,
    useUpdateNodeInternals: () => updateNodeInternals,
  };
});

function makeNode(nodeType: CanvasNodeTypeV2, status: CanvasNodeStatusV2 = "draft"): CanvasNodeV2 {
  return {
    node_id: `${nodeType}-node`,
    workflow_id: "workflow-1",
    node_type: nodeType,
    creative_role: nodeType === "text" ? "general_text" : nodeType === "script" ? "script" : nodeType === "image" ? "general_image" : nodeType === "video" ? "general_video" : nodeType === "audio" ? "general_audio" : "editing",
    role_contract_version: "ad-media-role-v1",
    title: `Hidden ${nodeType} title`,
    status,
    summary_prompt: nodeType === "text" ? "A concise campaign brief" : null,
    generation_prompt: nodeType === "script" ? "Write a cinematic script" : null,
    structured_content: nodeType === "script"
      ? { script_text: "Open on a quiet city at dawn." }
      : {},
    model_id: null,
    parameters: {},
    metadata: {},
    prompt_context_snapshot_id: null,
    output_asset_id: ["image", "video", "audio", "editing"].includes(nodeType)
      ? `${nodeType}-asset`
      : null,
    position: { x: 80, y: 120 },
    revision: 1,
    error: status === "failed"
      ? { code: "provider_failed", message: "Provider failed", retryable: true }
      : null,
    variation_draft: null,
    created_at: "2026-07-28T09:00:00Z",
    updated_at: "2026-07-28T09:00:00Z",
  };
}

function makeAsset(mediaType: "image" | "video" | "audio"): ProjectAssetSummaryV2 {
  return {
    asset_id: `${mediaType}-asset`,
    project_id: "project-1",
    workflow_id: "workflow-1",
    media_type: mediaType,
    source_type: "generated",
    display_name: `${mediaType} output`,
    mime_type: mediaType === "image" ? "image/webp" : `${mediaType}/mp4`,
    status: "ready",
    size_bytes: 0,
    storage_key: null,
    preview_url: `/media/${mediaType}-poster.webp`,
    media_url: `/media/${mediaType}-output`,
    width: mediaType === "audio" ? null : 1280,
    height: mediaType === "audio" ? null : 720,
    duration_seconds: mediaType === "image" ? null : 12,
    checksum: `${mediaType}-checksum`,
    source_semantic_role: null,
    source_node_id: null,
    source_execution_id: null,
    provider: null,
    model_id: null,
    prompt_provenance: {},
    quality_metadata: {},
    created_at: "2026-07-28T09:00:00Z",
  };
}

function makeRuntime(status: CanvasNodeStatusV2): NodeRuntimeV2 {
  return {
    node_id: "script-node",
    visible_status: status,
    phase: status === "working" ? "running" : null,
    execution_id: status === "working" ? "execution-1" : null,
    provider_task_id: null,
    waiting_for_node_ids: [],
    blocked_by_node_ids: [],
    attempt_no: status === "working" ? 1 : 0,
    updated_at: "2026-07-28T09:00:00Z",
    error: null,
  };
}

afterEach(() => {
  cleanup();
  updateNodeInternals.mockClear();
});

describe("AgentCanvasNodeCard", () => {
  it("uses a genuinely translucent glass surface for dark audio nodes", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/canvas/AgentCanvasNode.css");
    const css = readFileSync(cssPath, "utf8");
    const shellRule = css.match(
      /:root\[data-theme="dark"\] \.agent-canvas-node--audio\s*\{([\s\S]*?)\n\}/,
    )?.[1];
    const playerRule = css.match(
      /:root\[data-theme="dark"\] \.agent-canvas-audio-player\s*\{([\s\S]*?)\n\}/,
    )?.[1];
    const glassEdgeRule = css.match(
      /:root\[data-theme="dark"\] \.agent-canvas-audio-player::before\s*\{([\s\S]*?)\n\}/,
    )?.[1];
    const selectedRule = css.match(
      /:root\[data-theme="dark"\] \.agent-canvas-node--audio\.agent-canvas-node--selected\s*\{([\s\S]*?)\n\}/,
    )?.[1];

    expect(shellRule).toContain("background: transparent");
    expect(shellRule).toContain("backdrop-filter: none");
    expect(playerRule).toContain("isolation: auto");
    expect(playerRule).toContain("background: rgba(255, 255, 255, 0.06)");
    expect(playerRule).toContain("backdrop-filter: none");
    expect(playerRule).not.toContain("gradient");
    expect(glassEdgeRule).toContain("background: transparent");
    expect(glassEdgeRule).not.toContain("gradient");
    expect(selectedRule).toContain("0 0 0 3px rgba(185, 172, 216, 0.2)");
  });

  it("anchors a visible unframed type icon on the card's top-left border", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/canvas/AgentCanvasNode.css");
    const css = readFileSync(cssPath, "utf8");
    const markerRule = css.match(/\.agent-canvas-node__type-marker\s*\{([\s\S]*?)\n\}/)?.[1];

    expect(markerRule).toBeDefined();
    expect(markerRule).toContain("background: transparent");
    expect(markerRule).toContain("border: 0");
    expect(markerRule).toContain("top: 0");
    expect(markerRule).toContain("left: 0");
    expect(markerRule).toContain("width: 40px");
    expect(markerRule).toContain("height: 40px");
    expect(markerRule).toContain("transform: translateY(-100%)");
    expect(markerRule).not.toContain("border-radius");
    expect(markerRule).not.toContain("box-shadow");
  });

  it.each<CanvasNodeTypeV2>(["text", "script", "image", "video", "editing"])(
    "renders a lightweight %s card with a border-aligned type marker and no title",
    (nodeType) => {
      const node = makeNode(nodeType);
      const asset = nodeType === "image" || nodeType === "video"
        ? makeAsset(nodeType)
        : nodeType === "editing"
          ? makeAsset("video")
          : null;

      render(<AgentCanvasNodeCard node={node} asset={asset} />);

      const card = screen.getByTestId(`agent-canvas-node-${node.node_id}`);
      expect(card.dataset.nodeType).toBe(nodeType);
      expect(screen.getByLabelText(`${nodeType} node`).classList.contains("agent-canvas-node__type-marker")).toBe(true);
      expect(screen.queryByText(node.title)).toBeNull();
      expect(screen.getByText("Draft")).toBeTruthy();
    },
  );

  it("uses the glass player title instead of audio artwork or a status pill", () => {
    const node = makeNode("audio");
    render(<AgentCanvasNodeCard node={node} asset={makeAsset("audio")} />);

    expect(screen.getByText("No audio yet")).toBeTruthy();
    expect(screen.queryByText("Draft")).toBeNull();
    expect(screen.queryByLabelText("audio node")).toBeNull();
  });

  it("never offers Run for a text node", () => {
    render(<AgentCanvasNodeCard node={makeNode("text")} onRun={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /Run text node/i })).toBeNull();
  });

  it("labels and displays a World Setting as a Ready text document", () => {
    const node: CanvasNodeV2 = {
      ...makeNode("text", "ready"),
      creative_role: "world_setting",
      title: "World Setting",
      summary_prompt: null,
      structured_content: {
        document_kind: "world_setting",
        contract_version: "world-setting-v2",
        content: "A timeless mountain city governed by seasonal light and handmade technology.",
        core: {
          premise: "Seasonal light shapes daily life.",
          era_and_place: "A timeless mountain city.",
          world_rules: ["Technology is handmade."],
          visual_continuity: ["Natural stone and seasonal light recur."],
        },
        authoring_provenance: {
          source_proposal_id: "proposal-world-1",
          source_option_id: "option-world-1",
          materialization_run_id: "materialization-1",
          style_skill_run_id: null,
          creative_direction_snapshot_id: null,
        },
      },
    };

    render(<AgentCanvasNodeCard node={node} />);

    expect(screen.getByLabelText("World Setting node, Ready")).toBeTruthy();
    expect(screen.getByLabelText("World Setting node")).toBeTruthy();
    expect(screen.getByText(/timeless mountain city/)).toBeTruthy();
  });

  it("keeps a blocked Draft visible as waiting for upstream output", () => {
    render(
      <AgentCanvasNodeCard
        node={makeNode("image")}
        runtime={{
          ...makeRuntime("draft"),
          waiting_reason: "blocked_by_upstream",
          blocked_by_node_ids: ["upstream-node"],
        }}
      />,
    );

    expect(screen.getByText("Waiting for upstream")).toBeTruthy();
  });

  it("keeps a deterministic fallback node as a normal Draft and shows a bounded warning", () => {
    render(<AgentCanvasNodeCard node={{
      ...makeNode("image"),
      metadata: {
        materialization_mode: "deterministic_fallback",
        warning_code: "specialist_materialization_fallback",
        operation_policy_id: "agent.materialization.v1",
      },
    }} />);

    expect(screen.getByText("Draft")).toBeTruthy();
    expect(screen.getByText("Created with a simplified fallback")).toBeTruthy();
    expect(screen.queryByText("Failed")).toBeNull();
  });

  it.each<CanvasNodeTypeV2>(["script", "image", "video", "editing"])(
    "keeps %s actions in the inline composer instead of the card corner",
    (nodeType) => {
      const status = nodeType === "editing" ? "ready" : "draft";
      render(
        <AgentCanvasNodeCard
          node={makeNode(nodeType, status)}
          asset={nodeType === "editing" ? makeAsset("video") : null}
          onRun={vi.fn()}
          onRetry={vi.fn()}
          onExport={vi.fn()}
        />,
      );

      expect(screen.queryByRole("button")).toBeNull();
    },
  );

  it("does not run a Ready generated node in place", () => {
    render(
      <AgentCanvasNodeCard
        node={makeNode("image", "ready")}
        asset={makeAsset("image")}
        onRun={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Run image node" })).toBeNull();
  });

  it("labels a storyboard as one semantic Image output rather than nine shot nodes", () => {
    const node = { ...makeNode("image", "ready"), creative_role: "storyboard_sequence" as const };
    render(<AgentCanvasNodeCard node={node} asset={makeAsset("image")} />);

    expect(screen.getByLabelText("Storyboard Sequence image node")).toBeTruthy();
    expect(screen.getAllByRole("img", { name: "image output" })).toHaveLength(1);
  });

  it("keeps the last media visible for a failed executable node", () => {
    const node = makeNode("video", "failed");
    render(
      <AgentCanvasNodeCard
        node={node}
        asset={makeAsset("video")}
      />,
    );

    expect(screen.getByLabelText("video output").classList.contains("agent-canvas-node__media")).toBe(true);
    expect(screen.getByText("Failed")).toBeTruthy();
  });

  it("uses the runtime status, shows a restrained working treatment, and hides duplicate runs", () => {
    const node = makeNode("script", "draft");
    render(
      <AgentCanvasNodeCard
        node={node}
        runtime={makeRuntime("working")}
        onRun={vi.fn()}
      />,
    );

    expect(screen.getByText("Working")).toBeTruthy();
    expect(screen.getByLabelText("script node is working").classList.contains("agent-canvas-node__working")).toBe(true);
    expect(screen.queryByRole("button", { name: "Run script node" })).toBeNull();
  });

  it("contains complete image outputs while keeping video frames full-bleed", () => {
    const imageView = render(
      <AgentCanvasNodeCard node={makeNode("image", "ready")} asset={makeAsset("image")} />,
    );
    const image = screen.getByRole("img", { name: "image output" });
    expect(image.classList.contains("agent-canvas-node__media")).toBe(true);
    expect(image.classList.contains("agent-canvas-node__media--contain")).toBe(true);
    expect(image.classList.contains("agent-canvas-node__media--cover")).toBe(false);

    imageView.unmount();
    render(<AgentCanvasNodeCard node={makeNode("video", "ready")} asset={makeAsset("video")} />);
    const video = screen.getByLabelText("video output");
    expect(video.tagName).toBe("VIDEO");
    expect(video.getAttribute("src")).toBe("/media/video-output");
    expect(video.classList.contains("agent-canvas-node__media")).toBe(true);
    expect(video.classList.contains("agent-canvas-node__media--cover")).toBe(true);
  });

  it("sizes an image node shell from the generated asset dimensions", () => {
    const data: AgentCanvasNodeData = {
      node: makeNode("image", "ready"),
      asset: { ...makeAsset("image"), width: 1920, height: 1080 },
    };

    const { container } = render(
      <ReactFlowProvider>
        <AgentCanvasNodeRenderer
          id={data.node.node_id}
          data={data}
          type="agentCanvas"
          selected={false}
          dragging={false}
          draggable
          selectable
          deletable
          isConnectable
          zIndex={0}
          positionAbsoluteX={0}
          positionAbsoluteY={0}
        />
      </ReactFlowProvider>,
    );

    const shell = container.querySelector<HTMLElement>(".agent-canvas-node-shell");
    expect(shell?.style.width).toBe("360px");
    expect(shell?.style.height).toBe("203px");
  });

  it("falls back to the loaded image dimensions when asset metadata is missing", () => {
    const data: AgentCanvasNodeData = {
      node: makeNode("image", "ready"),
      asset: { ...makeAsset("image"), width: null, height: null },
    };

    const { container } = render(
      <ReactFlowProvider>
        <AgentCanvasNodeRenderer
          id={data.node.node_id}
          data={data}
          type="agentCanvas"
          selected={false}
          dragging={false}
          draggable
          selectable
          deletable
          isConnectable
          zIndex={0}
          positionAbsoluteX={0}
          positionAbsoluteY={0}
        />
      </ReactFlowProvider>,
    );

    const shell = container.querySelector<HTMLElement>(".agent-canvas-node-shell");
    const image = screen.getByRole("img", { name: "image output" });
    expect(shell?.style.width).toBe("272px");
    expect(shell?.style.height).toBe("184px");

    Object.defineProperty(image, "naturalWidth", { configurable: true, value: 1080 });
    Object.defineProperty(image, "naturalHeight", { configurable: true, value: 1920 });
    fireEvent.load(image);

    expect(shell?.style.width).toBe("203px");
    expect(shell?.style.height).toBe("360px");
    expect(updateNodeInternals).toHaveBeenLastCalledWith("image-node");
  });

  it("opens a generated video from its play control without bubbling to the node click surface", () => {
    const asset = makeAsset("video");
    const onOpenVideoPreview = vi.fn();
    const onNodeClick = vi.fn();
    const onNodePointerDown = vi.fn();

    render(
      // eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events -- Test harness observes React click bubbling from the child control.
      <div onClick={onNodeClick} onPointerDown={onNodePointerDown}>
        <AgentCanvasNodeCard
          node={makeNode("video", "ready")}
          asset={asset}
          onOpenVideoPreview={onOpenVideoPreview}
        />
      </div>,
    );

    const playButton = screen.getByRole("button", { name: "Play video output" });
    fireEvent.pointerDown(playButton);
    fireEvent.click(playButton);

    expect(onOpenVideoPreview).toHaveBeenCalledWith("video-node", asset);
    expect(onNodeClick).not.toHaveBeenCalled();
    expect(onNodePointerDown).not.toHaveBeenCalled();
  });

  it("keeps the rest of the video surface available to the existing node selection flow", () => {
    const onNodeClick = vi.fn();

    render(
      // eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events -- Test harness represents React Flow's node click listener.
      <div onClick={onNodeClick}>
        <AgentCanvasNodeCard
          node={makeNode("video", "ready")}
          asset={makeAsset("video")}
          onOpenVideoPreview={vi.fn()}
        />
      </div>,
    );

    fireEvent.click(screen.getByLabelText("video output"));

    expect(onNodeClick).toHaveBeenCalledTimes(1);
  });

  it("does not show a playback control for an image or a video without generated media", () => {
    const imageView = render(
      <AgentCanvasNodeCard
        node={makeNode("image", "ready")}
        asset={makeAsset("image")}
        onOpenVideoPreview={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Play image output" })).toBeNull();

    imageView.unmount();
    render(
      <AgentCanvasNodeCard
        node={{ ...makeNode("video", "ready"), output_asset_id: null }}
        onOpenVideoPreview={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Play video output" })).toBeNull();
  });

  it("keeps the generated image in the node instead of opening a separate media preview", () => {
    const asset = makeAsset("image");

    render(
      <AgentCanvasNodeCard
        node={makeNode("image", "ready")}
        asset={asset}
      />,
    );

    expect(screen.getByRole("img", { name: "image output" }).getAttribute("src")).toBe(asset.media_url);
    expect(screen.queryByRole("button", { name: /open .* preview/i })).toBeNull();
  });
});

describe("AgentCanvasNodeRenderer", () => {
  it("leaves connection point geometry to the default React Flow handles", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/canvas/AgentCanvasNode.css");
    const css = readFileSync(cssPath, "utf8");
    const handleRule = css.match(/^\.react-flow__handle\.agent-canvas-node__handle\s*\{([\s\S]*?)\n\}/m)?.[1];
    const inputRule = css.match(/^\.react-flow__handle\.agent-canvas-node__handle--input\s*\{([\s\S]*?)\n\}/m)?.[1];
    const outputRule = css.match(/^\.react-flow__handle\.agent-canvas-node__handle--output\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(handleRule).toContain("z-index: 12");
    expect(handleRule).not.toMatch(/\b(?:width|height|border|background(?:-color)?|display|place-items):/);
    expect(inputRule).toBeUndefined();
    expect(outputRule).toBeUndefined();
    expect(css).not.toContain(".agent-canvas-node__handle-target");
  });

  it.each<CanvasNodeTypeV2>(["text", "script", "image", "video", "audio", "editing"])(
    "renders %s node with only the default connection handles",
    (nodeType) => {
      const data: AgentCanvasNodeData = { node: makeNode(nodeType) };
      const { container } = render(
        <ReactFlowProvider>
          <AgentCanvasNodeRenderer
            id={data.node.node_id}
            data={data}
            type="agentCanvas"
            selected={false}
            dragging={false}
            draggable
            selectable
            deletable
            isConnectable
            zIndex={0}
            positionAbsoluteX={0}
            positionAbsoluteY={0}
          />
        </ReactFlowProvider>,
      );

      expect(container.querySelectorAll(".agent-canvas-node__handle")).toHaveLength(2);
      expect(container.querySelectorAll(".agent-canvas-node__handle-target")).toHaveLength(0);
    },
  );

  it("renders connectable left and right handles", () => {
    const data: AgentCanvasNodeData = {
      node: makeNode("image"),
      asset: makeAsset("image"),
      onRun: vi.fn(),
    };

    render(
      <ReactFlowProvider>
        <AgentCanvasNodeRenderer
          id={data.node.node_id}
          data={data}
          type="agentCanvas"
          selected={false}
          dragging={false}
          draggable
          selectable
          deletable
          isConnectable
          zIndex={0}
          positionAbsoluteX={0}
          positionAbsoluteY={0}
        />
      </ReactFlowProvider>,
    );

    expect(screen.getByLabelText("Image node input").classList).toContain("react-flow__handle-left");
    expect(screen.getByLabelText("Image node output").classList).toContain("react-flow__handle-right");
    expect(screen.queryByLabelText("Add an upstream node to Image")).toBeNull();
    expect(screen.queryByLabelText("Add a downstream node to Image")).toBeNull();
  });

  it.each(["image", "audio"] as const)(
    "renders the selected %s node workbench directly below the node shell",
    (nodeType) => {
      const workbenchLabel = `${nodeType === "image" ? "Image" : "Audio"} node workbench`;
      const data = {
        node: makeNode(nodeType),
        asset: makeAsset(nodeType),
        renderWorkbench: () => <div aria-label={workbenchLabel}>Prompt controls</div>,
      } as AgentCanvasNodeData & {
        renderWorkbench: () => JSX.Element;
      };

      render(
        <ReactFlowProvider>
          <AgentCanvasNodeRenderer
            id={data.node.node_id}
            data={data}
            type="agentCanvas"
            selected
            dragging={false}
            draggable
            selectable
            deletable
            isConnectable
            zIndex={0}
            positionAbsoluteX={0}
            positionAbsoluteY={0}
          />
        </ReactFlowProvider>,
      );

      expect(screen.getByLabelText(workbenchLabel)).toBeTruthy();
    },
  );

  it("centers the inline workbench beneath its card", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/canvas/AgentCanvasNode.css");
    const css = readFileSync(cssPath, "utf8");
    const anchorRule = css.match(/\.agent-canvas-node-workbench-anchor\s*\{([\s\S]*?)\n\}/)?.[1];

    expect(anchorRule).toBeDefined();
    expect(anchorRule).toContain("left: 50%");
    expect(anchorRule).toContain("transform: translateX(-50%)");
  });
});
