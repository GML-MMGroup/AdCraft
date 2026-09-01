import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import type { HTMLAttributes, ReactNode } from "react";
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
  type AgentCanvasFlowNode,
  type AgentCanvasNodeData,
} from "./AgentCanvasNode.tsx";
import { areAgentCanvasNodePropsEqual } from "./agentCanvasNodeRenderModel.ts";
import { creativeRoleDisplayName } from "./creativeRoleDisplayName.ts";

const updateNodeInternals = vi.hoisted(() => vi.fn());
const ensureVideoPoster = vi.hoisted(() => vi.fn());
const ensureVideoPosterFromElement = vi.hoisted(() => vi.fn());
const requestNativeVideoFirstFrame = vi.hoisted(() => vi.fn(() => Promise.resolve()));

vi.mock("@xyflow/react", async () => {
  const actual = await vi.importActual<typeof import("@xyflow/react")>("@xyflow/react");
  return {
    ...actual,
    NodeToolbar: ({ children, ...props }: { children?: ReactNode } & HTMLAttributes<HTMLDivElement>) => (
      <div {...props}>{children}</div>
    ),
    useUpdateNodeInternals: () => updateNodeInternals,
  };
});

vi.mock("../../../workflow/videoPosterCache.ts", () => ({
  ensureVideoPoster,
  ensureVideoPosterFromElement,
}));

vi.mock("./nativeVideoFirstFrame.ts", () => ({
  requestNativeVideoFirstFrame,
}));

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
  ensureVideoPoster.mockReset();
  ensureVideoPosterFromElement.mockReset();
  requestNativeVideoFirstFrame.mockReset();
  vi.useRealTimers();
});

describe("AgentCanvasNodeCard", () => {
  it.each([
    ["product", "image", "Product"],
    ["storyboard_sequence", "image", "Storyboard Sequence"],
    ["world_setting", "text", "World Setting"],
  ] as const)(
    "shows the backend-provided %s creative role in the header",
    (creativeRole, nodeType, expectedLabel) => {
      const { container } = render(
        <AgentCanvasNodeCard
          node={{
            ...makeNode(nodeType),
            creative_role: creativeRole,
            title: "A backend title that is not used for the label",
          }}
        />,
      );

      expect(container.querySelector(".agent-canvas-node__header-name")?.textContent).toBe(
        expectedLabel,
      );
    },
  );

  it("uses a genuinely translucent glass surface for dark audio nodes", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/canvas/AgentCanvasNode.css");
    const css = readFileSync(cssPath, "utf8");
    const shellRule = css.match(
      /:root \.agent-canvas-node--audio\s*\{([\s\S]*?)\n\}/,
    )?.[1];
    const playerRule = css.match(
      /:root \.agent-canvas-audio-player\s*\{([\s\S]*?)\n\}/,
    )?.[1];
    const glassEdgeRule = css.match(
      /:root \.agent-canvas-audio-player::before\s*\{([\s\S]*?)\n\}/,
    )?.[1];
    expect(shellRule).toContain("background: transparent");
    expect(shellRule).toContain("backdrop-filter: none");
    expect(playerRule).toContain("isolation: auto");
    expect(playerRule).toContain("background: rgba(255, 255, 255, 0.06)");
    expect(playerRule).toContain("backdrop-filter: none");
    expect(playerRule).not.toContain("gradient");
    expect(glassEdgeRule).toContain("background: transparent");
    expect(glassEdgeRule).not.toContain("gradient");
  });

  it("does not add a border, glow, or transform when a node is selected", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/canvas/AgentCanvasNode.css");
    const css = readFileSync(cssPath, "utf8");

    expect(css).not.toMatch(/\.agent-canvas-node--selected\s*\{/);
  });

  it("uses one transparent glass shell for every visible node type", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/canvas/AgentCanvasNode.css");
    const css = readFileSync(cssPath, "utf8");
    const shellRule = css.match(/^\.agent-canvas-node\s*\{([\s\S]*?)\n\}/m)?.[1];
    const surfaceRule = css.match(/^\.agent-canvas-node__surface\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(shellRule).toContain("background: transparent");
    expect(surfaceRule).toContain("background: rgba(255, 255, 255, 0.06)");
    expect(css).not.toContain(".agent-canvas-node__type-marker");
  });

  it.each<CanvasNodeTypeV2>(["text", "image", "video", "editing"])(
    "renders a lightweight %s card with the add-node icon in its header when no output exists",
    (nodeType) => {
      const node = makeNode(nodeType);

      render(<AgentCanvasNodeCard node={node} />);

      const card = screen.getByTestId(`agent-canvas-node-${node.node_id}`);
      expect(card.dataset.nodeType).toBe(nodeType);
      const label = creativeRoleDisplayName(node.creative_role);
      expect(screen.getByLabelText(`${label} node type`).classList.contains("agent-canvas-node__header-icon")).toBe(true);
      expect(screen.getByText(label)).toBeTruthy();
      expect(card.classList.contains("agent-canvas-node--draft")).toBe(true);
    },
  );

  it("shows media dimensions in the header and changes only icon color by status", () => {
    const { rerender } = render(
      <AgentCanvasNodeCard
        node={makeNode("image", "ready")}
        asset={makeAsset("image")}
      />,
    );

    const card = screen.getByTestId("agent-canvas-node-image-node");
    expect(screen.getByText("1280 × 720")).toBeTruthy();
    expect(card.querySelector(".agent-canvas-node__header--ready .agent-canvas-node__header-icon")).toBeTruthy();
    expect(card.querySelector(".agent-canvas-node__status")).toBeNull();

    rerender(
      <AgentCanvasNodeCard
        node={makeNode("image", "failed")}
        asset={makeAsset("image")}
      />,
    );

    const failedCard = screen.getByTestId("agent-canvas-node-image-node");
    expect(failedCard.querySelector(".agent-canvas-node__header--failed .agent-canvas-node__header-icon")).toBeTruthy();
    expect(failedCard.querySelector(".agent-canvas-node__header-icon .agent-canvas-node-icon")).toBeTruthy();
  });

  it("labels Character Main and Turnaround from prompt preparation fields", () => {
    const { rerender } = render(
      <AgentCanvasNodeCard
        node={{
          ...makeNode("image", "ready"),
          creative_role: "character",
          prompt_preparation: {
            status: "ready",
            operation_id: null,
            presentation_stream_id: null,
            attempt_no: 1,
            context_snapshot_id: null,
            occurrence_id: "occurrence:character:1",
            character_phase: "main",
            prompt_digest: null,
            role_variant: "character_main",
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
            assertion_evidence: null,
            attempt_stage: null,
            error: null,
            updated_at: "2026-08-27T08:00:00Z",
            summary: "Character main",
            category: "character",
            tags: [],
            supported_use_cases: [],
            preview: null,
            display_order: 0,
          },
        }}
      />,
    );
    expect(screen.getByText("Character Main")).toBeTruthy();
    expect(screen.queryByText("Hidden image title")).toBeNull();

    rerender(
      <AgentCanvasNodeCard
        node={{
          ...makeNode("image", "draft"),
          creative_role: "character",
          prompt_preparation: {
            ...({} as CanvasNodeV2["prompt_preparation"]),
            status: "ready",
            character_phase: "turnaround",
            occurrence_id: "occurrence:character:1",
            role_variant: "character_turnaround",
          } as CanvasNodeV2["prompt_preparation"],
        }}
      />,
    );
    expect(screen.getByText("Character Turnaround")).toBeTruthy();
  });

  it("renders backend Script content rather than hiding the canonical Script node", () => {
    const node = {
      ...makeNode("script", "ready"),
      structured_content: {
        content: "INT. CITY STREET - DAWN\n\nA quiet city begins to wake.",
      },
    } as CanvasNodeV2;

    render(<AgentCanvasNodeCard node={node} />);

    const card = screen.getByTestId("agent-canvas-node-script-node");
    expect(card.dataset.nodeType).toBe("script");
    expect(screen.getByText(/INT\. CITY STREET - DAWN/)).toBeTruthy();
    expect(screen.queryByText("Write a cinematic script")).toBeNull();
    const scriptContent = card.querySelector(".agent-canvas-node__content--script");
    expect(scriptContent).toBeTruthy();
    expect(scriptContent?.classList.contains("nowheel")).toBe(true);
    expect(screen.getByLabelText("Script node type")).toBeTruthy();
  });

  it("keeps non-Script node content available to canvas wheel gestures", () => {
    const node = {
      ...makeNode("text", "ready"),
      structured_content: { content: "A concise campaign direction." },
    } as CanvasNodeV2;

    render(<AgentCanvasNodeCard node={node} />);

    const card = screen.getByTestId("agent-canvas-node-text-node");
    expect(card.querySelector(".agent-canvas-node__content")?.classList.contains("nowheel"))
      .toBe(false);
  });

  it("keeps long Script output inside a 500px scrollable card", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/canvas/AgentCanvasNode.css");
    const css = readFileSync(cssPath, "utf8");
    const scriptContentRule = css.match(
      /\.agent-canvas-node__content--script\s*\{([\s\S]*?)\n\}/,
    )?.[1];

    expect(scriptContentRule).toContain("overflow-y: auto");
    expect(scriptContentRule).toContain("overscroll-behavior: contain");
  });

  it("renders saved Text content in the node body", () => {
    const node = {
      ...makeNode("text"),
      structured_content: { content: "A concise campaign direction." },
    } as CanvasNodeV2;

    render(<AgentCanvasNodeCard node={node} />);

    expect(screen.getByText("A concise campaign direction.")).toBeTruthy();
    expect(screen.getByLabelText(`${creativeRoleDisplayName(node.creative_role)} node type`)).toBeTruthy();
  });

  it.each<"image" | "video">(["image", "video"])(
    "keeps the empty %s body free of the generation prompt until media exists",
    (nodeType) => {
      const prompt = nodeType === "image"
        ? "A complete product image prompt."
        : "A smooth cinematic camera move.";
      const node = {
        ...makeNode(nodeType),
        generation_prompt: prompt,
        prompt_preparation: {
          status: "ready" as const,
          operation_id: "prompt-operation-1",
          attempt_no: 1,
          context_snapshot_id: "prompt-context-1",
          prompt_digest: "prompt-digest-1",
          error: null,
          updated_at: "2026-08-04T00:00:00Z",
        },
      } as CanvasNodeV2;

      render(<AgentCanvasNodeCard node={node} />);

      expect(screen.queryByText(prompt)).toBeNull();
      expect(screen.getByTestId(`agent-canvas-node-${nodeType}-node`).querySelector(
        ".agent-canvas-node__media-placeholder",
      )).toBeTruthy();
    },
  );

  it("renders current backend Script content on the card", () => {
    const node = {
      ...makeNode("script"),
      structured_content: { content: "A quiet coffee break resets the afternoon." },
    } as CanvasNodeV2;

    render(<AgentCanvasNodeCard node={node} />);

    expect(screen.getByLabelText("Script node, Draft")).toBeTruthy();
    expect(screen.getByText("A quiet coffee break resets the afternoon.")).toBeTruthy();
  });

  it("renders legacy script_text content on the card", () => {
    render(<AgentCanvasNodeCard node={makeNode("script")} />);

    expect(screen.getByText("Open on a quiet city at dawn.")).toBeTruthy();
  });

  it("renders a Script placeholder when the document is empty", () => {
    const node = {
      ...makeNode("script"),
      generation_prompt: null,
      structured_content: {},
    } as CanvasNodeV2;

    render(<AgentCanvasNodeCard node={node} />);

    expect(screen.getByLabelText("Script node type")).toBeTruthy();
  });

  it("does not resurrect legacy Script text after current content is cleared", () => {
    const node = {
      ...makeNode("script"),
      generation_prompt: null,
      structured_content: {
        script_text: "Legacy script that was cleared.",
        content: "",
      },
    } as CanvasNodeV2;

    render(<AgentCanvasNodeCard node={node} />);

    expect(screen.queryByText("Legacy script that was cleared.")).toBeNull();
    expect(screen.getByLabelText("Script node type")).toBeTruthy();
  });

  it("keeps the media body empty during prompt preparation without changing its four-state node status", () => {
    const node = {
      ...makeNode("image"),
      summary_prompt: "A warm product portrait for the campaign opening.",
      generation_prompt: null,
      prompt_preparation: {
        status: "queued",
        operation_id: "prompt-operation-1",
        attempt_no: 0,
        context_snapshot_id: null,
        prompt_digest: null,
        error: null,
        updated_at: "2026-08-11T10:00:00Z",
      },
    } as CanvasNodeV2;

    render(<AgentCanvasNodeCard node={node} />);

    const card = screen.getByTestId("agent-canvas-node-image-node");
    expect(screen.queryByText("A warm product portrait for the campaign opening.")).toBeNull();
    expect(card.querySelector(".agent-canvas-node__media-placeholder")).toBeTruthy();
    expect(card.classList.contains("agent-canvas-node--draft")).toBe(true);
    expect(screen.queryByText("Preparing")).toBeNull();
  });

  it("uses the persisted Node status even when runtime telemetry says working", () => {
    const node = makeNode("image", "draft");

    render(<AgentCanvasNodeCard node={node} runtime={makeRuntime("working")} />);

    const card = screen.getByTestId("agent-canvas-node-image-node");
    expect(card.getAttribute("data-node-status")).toBe("draft");
    expect(card.getAttribute("aria-label")).toBe("General Image node, Draft");
    expect(card.classList.contains("agent-canvas-node--working")).toBe(false);
    expect(card.classList.contains("agent-canvas-node--draft")).toBe(true);
  });

  it("keeps a prompt preparation failure distinct from a media generation failure", () => {
    const node = {
      ...makeNode("image"),
      summary_prompt: "A warm product portrait for the campaign opening.",
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

    render(<AgentCanvasNodeCard node={node} />);

    expect(screen.getByTestId("agent-canvas-node-image-node").classList.contains("agent-canvas-node--draft")).toBe(true);
    expect(screen.queryByTitle("Node prompt preparation failed.")).toBeNull();
  });

  it("uses the glass player title instead of audio artwork or a status pill", () => {
    const node = {
      ...makeNode("audio"),
      prompt_preparation: {
        status: "ready",
        operation_id: "prompt-operation-1",
        attempt_no: 1,
        context_snapshot_id: "prompt-context-1",
        prompt_digest: "prompt-digest-1",
        error: null,
        updated_at: "2026-08-04T00:00:00Z",
      },
    } satisfies CanvasNodeV2;
    render(<AgentCanvasNodeCard node={node} asset={makeAsset("audio")} />);

    expect(screen.getByText("No audio yet")).toBeTruthy();
    expect(document.querySelector("audio")?.getAttribute("preload")).toBe("none");
    expect(screen.queryByText("Draft")).toBeNull();
    expect(screen.getByLabelText("General Audio node type")).toBeTruthy();
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
    expect(screen.getByLabelText("World Setting node type")).toBeTruthy();
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

    expect(screen.getByTestId("agent-canvas-node-image-node").classList.contains("agent-canvas-node--draft")).toBe(true);
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

    expect(screen.getByTestId("agent-canvas-node-image-node").classList.contains("agent-canvas-node--draft")).toBe(true);
    expect(screen.getByText("Created with a simplified fallback")).toBeTruthy();
    expect(screen.queryByText("Failed")).toBeNull();
  });

  it.each<CanvasNodeTypeV2>(["image", "video"])(
    "keeps %s actions in the inline composer instead of the card corner",
    (nodeType) => {
      render(
        <AgentCanvasNodeCard
          node={makeNode(nodeType, "draft")}
          asset={null}
          onRun={vi.fn()}
          onRetry={vi.fn()}
          onExport={vi.fn()}
        />,
      );

      expect(screen.queryByRole("button")).toBeNull();
    },
  );

  it("opens the Editing panel from the scissors control in the node surface", () => {
    const onOpenEditing = vi.fn();
    render(
      <AgentCanvasNodeCard
        node={makeNode("editing", "ready")}
        asset={makeAsset("video")}
        onOpenEditing={onOpenEditing}
      />,
    );

    const scissors = screen.getByRole("button", { name: "Open editing editor" });
    expect(scissors.querySelector("img")?.getAttribute("src")).toBe("/imgs/node-icons/scissors.svg");

    fireEvent.click(scissors);

    expect(onOpenEditing).toHaveBeenCalledWith("editing-node");
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

  it("renders a source-only Image reference as Ready without generation controls", () => {
    render(
      <AgentCanvasNodeCard
        node={{
          ...makeNode("image", "ready"),
          execution_mode: "source_only",
          creative_role: "character",
          output_asset_id: "reference-asset",
        }}
        asset={{ ...makeAsset("image"), asset_id: "reference-asset", display_name: "Character reference" }}
        onRun={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Character node, Ready")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Character reference" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Run image node" })).toBeNull();
  });

  it("labels a storyboard as one semantic Image output rather than nine shot nodes", () => {
    const node = { ...makeNode("image", "ready"), creative_role: "storyboard_sequence" as const };
    render(<AgentCanvasNodeCard node={node} asset={makeAsset("image")} />);

    expect(screen.getByLabelText("Storyboard Sequence node, Ready")).toBeTruthy();
    expect(screen.getByLabelText("Storyboard Sequence node type")).toBeTruthy();
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

    expect(screen.getByRole("img", { name: "video output" }).classList.contains("agent-canvas-node__media")).toBe(true);
    expect(screen.getByTestId("agent-canvas-node-video-node").classList.contains("agent-canvas-node--failed")).toBe(true);
    expect(document.querySelector(".agent-canvas-node__error")).toBeNull();
  });

  it.each<"image" | "video">(["image", "video"])(
    "uses a transparent generation energy overlay while a %s node is generating",
    (nodeType) => {
      const node = makeNode(nodeType, "working");
      const { container } = render(
        <AgentCanvasNodeCard
          node={node}
          runtime={makeRuntime("working")}
          onRun={vi.fn()}
        />,
      );

      expect(screen.getByTestId(`agent-canvas-node-${nodeType}-node`).classList.contains("agent-canvas-node--working")).toBe(true);
      const overlay = screen.getByRole("status", { name: `Generating ${nodeType}` });
      expect(overlay.classList.contains("agent-canvas-node__working--media")).toBe(true);
      expect(overlay.querySelector(".agent-canvas-node__generation-energy")).toBeTruthy();
      expect(overlay.querySelector(".agent-canvas-node__generation-loader")).toBeNull();
      expect(overlay.querySelector(".iml-loader")).toBeNull();
      expect(screen.queryByRole("button", { name: `Run ${nodeType} node` })).toBeNull();
    },
  );

  it("keeps the generation energy overlay transparent and motion-aware", () => {
    const nodeCss = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/canvas/AgentCanvasNode.css"),
      "utf8",
    );
    const pageCss = readFileSync(
      resolve(process.cwd(), "src/features/agent-canvas/agent-canvas-page.css"),
      "utf8",
    );
    const mediaOverlayRule = nodeCss.match(
      /\.agent-canvas-node__working--media\s*\{([\s\S]*?)\n\}/,
    )?.[1];
    const energyRule = nodeCss.match(
      /\.agent-canvas-node__generation-energy\s*\{([\s\S]*?)\n\}/,
    )?.[1];
    const energyGlowRule = nodeCss.match(
      /\.agent-canvas-node__generation-energy::before\s*\{([\s\S]*?)\n\}/,
    )?.[1];

    expect(mediaOverlayRule).toContain("background: transparent");
    expect(energyRule).toContain("pointer-events: none");
    expect(energyRule).toContain("contain: paint");
    expect(energyGlowRule).toContain("background-image: radial-gradient");
    expect(energyGlowRule).toContain("animation: agent-canvas-node-energy-drift");
    expect(nodeCss).not.toContain("generative-loaders");
    expect(nodeCss).not.toContain("agent-canvas-node__generation-loader");
    expect(nodeCss).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.agent-canvas-node__generation-energy::before[\s\S]*?animation: none/,
    );
    expect(pageCss).toMatch(
      /\.agent-canvas-board\.is-interacting\s+\.agent-canvas-node__generation-energy::before,[\s\S]*?\.agent-canvas-board\.is-interacting\s+\.agent-canvas-node__generation-energy::after\s*\{[\s\S]*?animation-play-state: paused;/,
    );
    expect(pageCss).not.toMatch(
      /\.agent-canvas-board\.is-interacting :is\([^)]*\.agent-canvas-node__generation-energy::before/,
    );
  });

  it("uses a derived image preview and keeps video source media out of the node", () => {
    const imageView = render(
      <AgentCanvasNodeCard node={makeNode("image", "ready")} asset={makeAsset("image")} />,
    );
    const image = screen.getByRole("img", { name: "image output" });
    expect(image.getAttribute("src")).toBe("/media/image-poster.webp");
    expect(image.getAttribute("loading")).toBe("lazy");
    expect(image.classList.contains("agent-canvas-node__media")).toBe(true);
    expect(image.classList.contains("agent-canvas-node__media--contain")).toBe(true);
    expect(image.classList.contains("agent-canvas-node__media--cover")).toBe(false);

    imageView.unmount();
    render(<AgentCanvasNodeCard node={makeNode("video", "ready")} asset={makeAsset("video")} />);
    expect(screen.queryByLabelText("video output")).toBeNull();
    expect(screen.getByRole("img", { name: "video output" })).toBeTruthy();
  });

  it("does not mount a video element just to capture a node thumbnail", () => {
    render(<AgentCanvasNodeCard node={makeNode("video", "ready")} asset={makeAsset("video")} />);
    expect(document.querySelector("video")).toBeNull();
    expect(ensureVideoPosterFromElement).not.toHaveBeenCalled();
  });

  it("keeps a posterless video source out of the canvas card", () => {
    const asset = {
      ...makeAsset("video"),
      preview_url: null,
      media_url: "/api/v2/assets/video-asset/content?v=video-version-2",
      version_id: "video-version-2",
    };

    render(<AgentCanvasNodeCard node={makeNode("video", "ready")} asset={asset} />);

    expect(document.querySelector("video")).toBeNull();
    expect(document.querySelector(".agent-canvas-node__media-placeholder")).toBeTruthy();
    expect(ensureVideoPoster).not.toHaveBeenCalled();
    expect(ensureVideoPosterFromElement).not.toHaveBeenCalled();
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

  it("grows a Script shell from the Text-node default height to its measured content height", () => {
    const scrollHeight = vi.spyOn(HTMLElement.prototype, "scrollHeight", "get")
      .mockReturnValue(260);
    const data: AgentCanvasNodeData = {
      node: makeNode("script", "ready"),
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
    expect(shell?.style.width).toBe("248px");
    expect(shell?.style.height).toBe("330px");
    expect(updateNodeInternals).toHaveBeenLastCalledWith("script-node");

    scrollHeight.mockRestore();
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
    const onNodeDoubleClick = vi.fn();

    render(
      // eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events -- Test harness observes React click bubbling from the child control.
      <div onClick={onNodeClick} onPointerDown={onNodePointerDown} onDoubleClick={onNodeDoubleClick}>
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
    fireEvent.doubleClick(playButton);

    expect(onOpenVideoPreview).toHaveBeenCalledWith("video-node", asset);
    expect(onNodeClick).not.toHaveBeenCalled();
    expect(onNodePointerDown).not.toHaveBeenCalled();
    expect(onNodeDoubleClick).not.toHaveBeenCalled();
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

    fireEvent.click(screen.getByRole("img", { name: "video output" }));

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

    expect(screen.getByRole("img", { name: "image output" }).getAttribute("src")).toBe(asset.preview_url);
    expect(screen.getByLabelText("General Image node type")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /open .* preview/i })).toBeNull();
  });
});

describe("AgentCanvasNodeRenderer", () => {
  function rendererProps(
    data: AgentCanvasNodeData,
    selected = false,
  ): Parameters<typeof areAgentCanvasNodePropsEqual>[0] {
    return {
      id: data.node.node_id,
      data,
      type: "agentCanvas",
      selected,
      dragging: false,
      draggable: true,
      selectable: true,
      deletable: true,
      isConnectable: true,
      zIndex: 0,
      positionAbsoluteX: 0,
      positionAbsoluteY: 0,
    } as Parameters<typeof areAgentCanvasNodePropsEqual>[0] & AgentCanvasFlowNode;
  }

  it("skips rerendering unchanged unselected nodes after object hydration", () => {
    const runtime = makeRuntime("working");
    const previous = rendererProps({
      node: makeNode("image", "working"),
      asset: makeAsset("image"),
      runtime,
      workbenchActive: false,
      renderWorkbench: vi.fn(),
    });
    const next = rendererProps({
      node: { ...previous.data.node },
      asset: { ...previous.data.asset! },
      runtime: { ...runtime, updated_at: "2026-07-28T09:00:10Z" },
      workbenchActive: false,
      renderWorkbench: vi.fn(),
    });

    expect(areAgentCanvasNodePropsEqual(previous, next)).toBe(true);
  });

  it("rerenders changed node revisions and active workbench runtime", () => {
    const runtime = makeRuntime("working");
    const previous = rendererProps({
      node: makeNode("script", "working"),
      runtime,
      workbenchActive: true,
      renderWorkbench: vi.fn(),
    }, true);
    const changedNode = rendererProps({
      ...previous.data,
      node: { ...previous.data.node, revision: previous.data.node.revision + 1 },
    }, true);
    const changedRuntime = rendererProps({
      ...previous.data,
      runtime: { ...runtime, attempt_no: runtime.attempt_no + 1 },
    }, true);
    const changedWorkflow = rendererProps({
      ...previous.data,
      node: { ...previous.data.node, workflow_id: "workflow-2" },
    }, true);

    expect(areAgentCanvasNodePropsEqual(previous, changedNode)).toBe(false);
    expect(areAgentCanvasNodePropsEqual(previous, changedRuntime)).toBe(false);
    expect(areAgentCanvasNodePropsEqual(previous, changedWorkflow)).toBe(false);
  });

  it("renders hover-revealed gray connection rings instead of default React Flow dots", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/canvas/AgentCanvasNode.css");
    const css = readFileSync(cssPath, "utf8");
    const handleRule = css.match(/^\.react-flow__handle\.agent-canvas-node__handle\s*\{([\s\S]*?)\n\}/m)?.[1];
    const ringRule = css.match(/^\.react-flow__handle\.agent-canvas-node__handle::after\s*\{([\s\S]*?)\n\}/m)?.[1];
    const inputRule = css.match(/^\.react-flow__handle\.agent-canvas-node__handle--input\s*\{([\s\S]*?)\n\}/m)?.[1];
    const outputRule = css.match(/^\.react-flow__handle\.agent-canvas-node__handle--output\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(handleRule).toContain("z-index: 12");
    expect(handleRule).toContain("width: 28px");
    expect(handleRule).toContain("height: 28px");
    expect(handleRule).toContain("border: 0");
    expect(handleRule).toContain("background: transparent");
    expect(handleRule).toContain("opacity: 0");
    expect(handleRule).toContain("pointer-events: none");
    expect(ringRule).toContain("width: 14px");
    expect(ringRule).toContain("height: 14px");
    expect(ringRule).toContain("border: 2px solid rgba(148, 151, 160, 0.92)");
    expect(ringRule).toContain("background: transparent");
    expect(inputRule).toContain("left: 14px");
    expect(inputRule).toContain("--agent-handle-ring-offset: -26px");
    expect(outputRule).toContain("right: 14px");
    expect(outputRule).toContain("--agent-handle-ring-offset: 26px");
    expect(ringRule).toContain("translateX(var(--agent-handle-ring-offset, 0px))");
    expect(css).toContain(".agent-canvas-node-shell:has(> .agent-canvas-node:hover)");
    expect(css).toContain("opacity: 1");
    expect(css).toContain("pointer-events: auto");
    expect(css).not.toContain(".agent-canvas-node__handle-target");
  });

  it.each<CanvasNodeTypeV2>(["text", "image", "video", "audio", "editing"])(
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

  it("does not render the bottom workbench for an Editing node", () => {
    const renderWorkbench = vi.fn(() => <div aria-label="Editing node workbench">Prompt controls</div>);
    const data: AgentCanvasNodeData = {
      node: makeNode("editing", "ready"),
      renderWorkbench,
      onOpenEditing: vi.fn(),
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

    expect(renderWorkbench).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Editing node workbench")).toBeNull();
    expect(screen.getByRole("button", { name: "Open editing editor" })).toBeTruthy();
  });

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

    expect(screen.getByLabelText("General Image node input").classList).toContain("react-flow__handle-left");
    expect(screen.getByLabelText("General Image node output").classList).toContain("react-flow__handle-right");
    expect(screen.queryByLabelText("Add an upstream node to General Image")).toBeNull();
    expect(screen.queryByLabelText("Add a downstream node to General Image")).toBeNull();
  });

  it.each(["image", "audio"] as const)(
    "renders the selected %s node workbench through the viewport-independent toolbar",
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

  it("passes the live runtime state to the inline workbench renderer", () => {
    const node = makeNode("script");
    const runtime = makeRuntime("working");
    const renderWorkbench = vi.fn(() => <div>Script controls</div>);
    const data: AgentCanvasNodeData = { node, runtime, renderWorkbench };

    render(
      <ReactFlowProvider>
        <AgentCanvasNodeRenderer
          id={node.node_id}
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

    expect(renderWorkbench).toHaveBeenCalledWith(node, runtime);
  });

  it("does not render the removed conversation navigation action", () => {
    const data: AgentCanvasNodeData = {
      node: makeNode("image", "ready"),
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
    expect(screen.queryByRole("button", { name: "Show in conversation" })).toBeNull();
  });

  it("keeps the prompt workbench fixed at 638 by 217 CSS pixels", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/workbench/agent-canvas-inline-workbench.css");
    const css = readFileSync(cssPath, "utf8");
    const workbenchRule = css.match(/\.agent-node-workbench\s*\{([\s\S]*?)\n\}/)?.[1];

    expect(workbenchRule).toBeDefined();
    expect(workbenchRule).toContain("width: 638px");
    expect(workbenchRule).toContain("height: 217px");
    expect(workbenchRule).toContain("box-sizing: border-box");

    const nodeCssPath = resolve(process.cwd(), "src/features/agent-canvas/canvas/AgentCanvasNode.css");
    const nodeCss = readFileSync(nodeCssPath, "utf8");
    expect(nodeCss).toContain(".react-flow__node-toolbar.agent-canvas-node-workbench-toolbar");
    expect(nodeCss).toContain("pointer-events: auto");
  });
});
