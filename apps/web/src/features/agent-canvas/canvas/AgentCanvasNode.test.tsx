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
    media_type: mediaType,
    source_type: "generated",
    display_name: `${mediaType} output`,
    mime_type: mediaType === "image" ? "image/webp" : `${mediaType}/mp4`,
    status: "ready",
    preview_url: `/media/${mediaType}-poster.webp`,
    media_url: `/media/${mediaType}-output`,
    width: mediaType === "audio" ? null : 1280,
    height: mediaType === "audio" ? null : 720,
    duration_seconds: mediaType === "image" ? null : 12,
    checksum: `${mediaType}-checksum`,
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

afterEach(() => cleanup());

describe("AgentCanvasNodeCard", () => {
  it.each<CanvasNodeTypeV2>(["text", "script", "image", "video", "audio", "editing"])(
    "renders a lightweight %s card with a border-aligned type marker and no title",
    (nodeType) => {
      const node = makeNode(nodeType);
      const asset = nodeType === "image" || nodeType === "video" || nodeType === "audio"
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

  it.each<CanvasNodeTypeV2>(["script", "image", "video", "audio"])(
    "runs an executable %s node through its callback",
    (nodeType) => {
      const onRun = vi.fn();
      const node = makeNode(nodeType);

      render(
        <AgentCanvasNodeCard
          node={node}
          asset={nodeType === "image" || nodeType === "video" || nodeType === "audio" ? makeAsset(nodeType) : null}
          onRun={onRun}
        />,
      );
      fireEvent.pointerDown(screen.getByRole("button", { name: `Run ${nodeType} node` }));
      fireEvent.click(screen.getByRole("button", { name: `Run ${nodeType} node` }));

      expect(onRun).toHaveBeenCalledOnce();
      expect(onRun).toHaveBeenCalledWith(node.node_id);
    },
  );

  it("never offers Run for a text node", () => {
    render(<AgentCanvasNodeCard node={makeNode("text")} onRun={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /Run text node/i })).toBeNull();
  });

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

  it("exports an editing node through its callback", () => {
    const onExport = vi.fn();
    const node = makeNode("editing", "ready");
    render(
      <AgentCanvasNodeCard
        node={node}
        asset={makeAsset("video")}
        onExport={onExport}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Export editing node" }));

    expect(onExport).toHaveBeenCalledWith(node.node_id);
  });

  it("retries a failed executable node and keeps its last media visible", () => {
    const onRetry = vi.fn();
    const node = makeNode("video", "failed");
    render(
      <AgentCanvasNodeCard
        node={node}
        asset={makeAsset("video")}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByRole("img", { name: "video output" }).classList.contains("agent-canvas-node__media")).toBe(true);
    expect(screen.getByText("Failed")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry video node" }));
    expect(onRetry).toHaveBeenCalledWith(node.node_id);
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

  it("renders image and video posters with the same full-bleed media surface", () => {
    const imageView = render(
      <AgentCanvasNodeCard node={makeNode("image", "ready")} asset={makeAsset("image")} />,
    );
    const image = screen.getByRole("img", { name: "image output" });
    expect(image.classList.contains("agent-canvas-node__media")).toBe(true);
    expect(image.classList.contains("agent-canvas-node__media--cover")).toBe(true);

    imageView.unmount();
    render(<AgentCanvasNodeCard node={makeNode("video", "ready")} asset={makeAsset("video")} />);
    const videoPoster = screen.getByRole("img", { name: "video output" });
    expect(videoPoster.classList.contains("agent-canvas-node__media")).toBe(true);
    expect(videoPoster.classList.contains("agent-canvas-node__media--cover")).toBe(true);
  });
});

describe("AgentCanvasNodeRenderer", () => {
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

    expect(screen.getByLabelText("Image node input")).toBeTruthy();
    expect(screen.getByLabelText("Image node output")).toBeTruthy();
  });
});
