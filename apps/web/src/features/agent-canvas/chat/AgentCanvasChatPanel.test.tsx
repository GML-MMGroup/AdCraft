import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const panelMocks = vi.hoisted(() => ({
  prepareRoleVisual: vi.fn(),
  getRoleVisualSnapshot: vi.fn(),
  useAgentCanvasChat: vi.fn(),
}));

vi.mock("./useAgentCanvasChat.ts", () => ({
  useAgentCanvasChat: panelMocks.useAgentCanvasChat,
}));

vi.mock("./agent-role-animation/agentRoleVisualResource.ts", async (importOriginal) => ({
  ...await importOriginal<typeof import("./agent-role-animation/agentRoleVisualResource.ts")>(),
  prepareRoleVisual: panelMocks.prepareRoleVisual,
  getRoleVisualSnapshot: panelMocks.getRoleVisualSnapshot,
  subscribeRoleVisual: () => () => undefined,
}));

vi.mock("./agent-role-animation/AgentRoleAnimation.tsx", () => ({
  AgentRoleAnimation: ({
    capabilityId,
    motionState,
  }: {
    capabilityId: string;
    motionState: string;
  }) => (
    <span
      data-testid="agent-role-animation-double"
      data-capability-id={capabilityId}
      data-motion-state={motionState}
    />
  ),
}));

import type {
  AgentCanvasChatTurnV2,
  CanvasRuntimeEventV2,
  ChatActionReceiptCardV2,
  AgentCanvasWorkflowV2,
  ChatCapabilityActivityV2,
  ChatCommandPlanCardV2,
  ChatProposalCardV2,
  ChatTimelineItemV2,
  GuidanceAwaitingV1,
  GuidedInteractionV1,
  GuidedSessionStateV2,
  ProposalActionDescriptorV2,
} from "../../../types-v2.ts";
import {
  ActionReceiptCard,
  AgentCanvasChatPanel,
  AgentWorkingRow,
  TimelineHydrationSkeleton,
  CapabilityActivityRow,
  CommandPlanCard,
  GuidanceSessionProgress,
  GuidedActionsCard,
  ProposalCard,
} from "./AgentCanvasChatPanel.tsx";
import {
  resizeChatComposerTextarea,
  snapChatComposerScroll,
} from "./chatComposerTextarea.ts";
import type { PresentationStreamView } from "../runtime/useAgentCanvasPresentationStreams.ts";
import type { BrandDecisionPanelV1 } from "../brand/brandDecisions.ts";
import { normalizeBrandDecisionPanelV1 } from "../brand/brandDecisionNormalizers.ts";
import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import { LocaleProvider } from "../../../i18n/locale.tsx";
import { LanguageSwitcher } from "../../../components/LanguageSwitcher.tsx";
import { normalizeAgentCanvasChatTimelineV2 } from "../model/normalizers.ts";

function mockChatResult(
  items: ChatTimelineItemV2[] = [],
  agentWaitingForModel = false,
  turnsById: Record<string, AgentCanvasChatTurnV2> = {},
) {
  const hydratedTurns = Object.fromEntries(items.flatMap((item) => {
    if (item.item_type !== "expert_activity") return [];
    const turn: AgentCanvasChatTurnV2 = {
      turn_id: item.turn_id, workflow_id: roleMotionWorkflow.workflow_id, conversation_id: "conversation-1",
      status: item.status === "working" ? "running" : item.status,
      turn_kind: "capability", request: { capability_id: item.capability_id },
      error_code: null, error_message: null, creation_mode: null,
      guidance_session_revision: null, continuation: null, retry_of_turn_id: null,
      retry_attempt_no: 0, retryable: false, operation_stage: null, operation_failure: null,
      created_at: "2026-09-03T00:00:00Z", updated_at: "2026-09-03T00:00:00Z",
    };
    return [[item.turn_id, turn]];
  }));
  return {
    state: {
      items,
      guidedAnswerBubbles: [],
      messageSkillTitles: {},
      guidanceSession: null,
      hasGuidedProductionIntent: false,
      guidedInteraction: null,
      guidanceAwaiting: null,
      currentSessionActions: [],
      continuations: [],
      turnsById: { ...hydratedTurns, ...turnsById },
      retryingSourceTurnIds: {},
      presentationStreams: [],
      loading: false,
      sending: false,
      agentWorking: items.some((item) => (
        item.item_type === "expert_activity" && item.status === "working"
      )),
      postReadyCheckpoint: null,
      agentWaitingForModel,
      actingProposalId: null,
      actingDecisionBundleId: null,
      actingCommandPlanId: null,
      actingGuidedActionId: null,
      actingInteractionId: null,
      composerRecovery: null,
      timelineRecovery: null,
      workflowRecovery: null,
      guidedInteractionIssue: null,
      notice: null,
      proposalIssues: {},
      failedDraft: null,
    },
    actions: {
      refresh: vi.fn(),
      submit: vi.fn(),
      selectProposal: vi.fn(),
      reviseProposal: vi.fn(),
      applyProposalAction: vi.fn(),
      actOnCommandPlan: vi.fn(),
      applyGuidedAction: vi.fn(),
      actOnDecisionBundle: vi.fn(),
      submitGuidedInteraction: vi.fn(),
      retryCapabilityActivity: vi.fn(),
      retryProposalMaterialization: vi.fn(),
      retryTurn: vi.fn(),
      clearFailedDraft: vi.fn(),
      clearComposerRecovery: vi.fn(),
      clearTimelineRecovery: vi.fn(),
      clearWorkflowRecovery: vi.fn(),
      clearNotice: vi.fn(),
    },
  };
}

beforeEach(() => {
  panelMocks.useAgentCanvasChat.mockReset();
  panelMocks.useAgentCanvasChat.mockReturnValue(mockChatResult());
  panelMocks.prepareRoleVisual.mockReset();
  panelMocks.getRoleVisualSnapshot.mockReturnValue({
    status: "ready", source: "/role.png", Artwork: () => null, error: null, generation: 1, fallbackKind: "none",
  });
});

describe("chat composer textarea", () => {
  it("grows with its content and only scrolls after reaching its height limit", () => {
    const textarea = document.createElement("textarea");
    let scrollHeight = 86;
    let clientHeight = 86;
    Object.defineProperty(textarea, "scrollHeight", { configurable: true, get: () => scrollHeight });
    Object.defineProperty(textarea, "clientHeight", { configurable: true, get: () => clientHeight });

    resizeChatComposerTextarea(textarea);
    expect(textarea.style.height).toBe("86px");
    expect(textarea.style.overflowY).toBe("hidden");

    scrollHeight = 220;
    clientHeight = 120;
    resizeChatComposerTextarea(textarea);
    expect(textarea.style.height).toBe("220px");
    expect(textarea.style.overflowY).toBe("auto");
  });

  it("snaps native textarea scrolling to complete line boundaries", () => {
    const textarea = document.createElement("textarea");
    textarea.style.lineHeight = "20px";
    Object.defineProperty(textarea, "scrollHeight", { configurable: true, value: 200 });
    Object.defineProperty(textarea, "clientHeight", { configurable: true, value: 120 });

    textarea.scrollTop = 29;
    snapChatComposerScroll(textarea);
    expect(textarea.scrollTop).toBe(20);
  });
});

describe("AgentCanvasChatPanel optimistic composer", () => {
  afterEach(cleanup);

  function renderPendingSubmission(retry = false) {
    const chat = mockChatResult();
    let accept!: (accepted: boolean) => void;
    chat.actions.submit.mockReturnValue(new Promise<boolean>(resolve => { accept = resolve; }));
    panelMocks.useAgentCanvasChat.mockReturnValue({
      ...chat,
      state: {
        ...chat.state,
        failedDraft: retry ? { text: "Create a product launch video", mentionedNodeIds: [], mentionedImageAssetIds: [] } : null,
        composerRecovery: retry ? {
          scope: "composer", title: "Response could not be submitted", message: "Try again.", action: "retry", technicalDetail: null,
        } : null,
      },
    });
    render(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()} />);
    const composer = screen.getByRole("textbox", { name: "Message AdCraft Video Agent" }) as HTMLTextAreaElement;
    return { chat, composer, accept };
  }

  it.each(["click", "enter"])("clears the first message immediately on %s while submission is pending", async (trigger) => {
    const { chat, composer, accept } = renderPendingSubmission();
    fireEvent.change(composer, { target: { value: "Create a product launch video" } });

    if (trigger === "enter") fireEvent.keyDown(composer, { key: "Enter" });
    else fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(chat.actions.submit).toHaveBeenCalledOnce();
    expect(chat.actions.submit).toHaveBeenCalledWith(expect.objectContaining({ text: "Create a product launch video" }));
    expect(composer.value).toBe("");
    await act(async () => { accept(true); });
    expect(composer.value).toBe("");
  });

  it.each(["Send message", "Retry"])("restores the exact draft if %s fails after clearing it immediately", async (button) => {
    const { composer, accept } = renderPendingSubmission(button === "Retry");
    const draft = "  Create a product launch video\n";
    fireEvent.change(composer, { target: { value: draft } });
    fireEvent.click(screen.getByRole("button", { name: button }));
    expect(composer.value).toBe("");

    await act(async () => { accept(false); });
    expect(composer.value).toBe(draft);
  });

  it.each([
    { button: "Send message", accepted: true },
    { button: "Send message", accepted: false },
    { button: "Retry", accepted: true },
    { button: "Retry", accepted: false },
  ])("preserves a new draft when $button settles with accepted=$accepted", async ({ button, accepted }) => {
    const { composer, accept } = renderPendingSubmission(button === "Retry");
    fireEvent.change(composer, { target: { value: "Create a product launch video" } });
    fireEvent.click(screen.getByRole("button", { name: button }));
    expect(composer.value).toBe("");
    // Re-entering the same text is still a new draft and must survive acceptance.
    const nextDraft = accepted ? "Create a product launch video" : "Make the next video shorter";
    fireEvent.change(composer, { target: { value: nextDraft } });

    await act(async () => { accept(accepted); });
    expect(composer.value).toBe(nextDraft);
  });

  it("leaves an unrelated draft untouched when retrying a failed message", async () => {
    const { chat, composer, accept } = renderPendingSubmission(true);
    fireEvent.change(composer, { target: { value: "A different request" } });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(chat.actions.submit).toHaveBeenCalledWith(expect.objectContaining({ text: "Create a product launch video" }));
    expect(composer.value).toBe("A different request");
    await act(async () => { accept(true); });
    expect(composer.value).toBe("A different request");
  });

  it("keeps whitespace-only input without submitting it", () => {
    const { chat, composer } = renderPendingSubmission();
    fireEvent.change(composer, { target: { value: "  \n" } });
    fireEvent.keyDown(composer, { key: "Enter" });
    expect(chat.actions.submit).not.toHaveBeenCalled();
    expect(composer.value).toBe("  \n");
  });
});

describe("AgentWorkingRow", () => {
  afterEach(() => { cleanup(); localStorage.removeItem("adcraft.locale"); });

  it("announces that the Agent is working and renders a loading indicator", () => {
    render(<AgentWorkingRow />);

    expect(screen.getByRole("status", { name: "AdCraft Video Agent is working" })).toBeTruthy();
    expect(document.querySelector(".agent-chat__working-text")?.textContent).toBe("Agent is working...");
    const loader = document.querySelector<HTMLElement>('.agent-chat__working-loader[data-variant="halo"]');
    expect(loader).toBeTruthy();
    expect(loader?.style.getPropertyValue("--il-size")).toBe("20px");
    expect(document.querySelector(".agent-chat__working-spinner")).toBeNull();
  });

  it("announces model waiting as a non-terminal Agent activity", () => {
    const chat = mockChatResult([], true);
    panelMocks.useAgentCanvasChat.mockReturnValue({ ...chat, state: { ...chat.state, agentWorking: true } });
    render(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()} />);

    expect(screen.getByRole("status", { name: "AdCraft Video Agent is working" })).toBeTruthy();
    expect(document.querySelector(".agent-chat__working-text")?.textContent).toBe("Agent is working...");
    expect(document.querySelector('.agent-chat__working-loader[data-variant="halo"]')).toBeTruthy();
    expect(document.querySelector(".agent-chat__working-spinner")).toBeNull();
  });

  it("updates the loading text when the active role or UI language changes", () => {
    localStorage.removeItem("adcraft.locale");
    const chat = mockChatResult([capabilityActivity({ capability_id: "script_authoring", capability_display_name: "Script Writer" })]);
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    const panel = () => <LocaleProvider initialLocale="en-US"><LanguageSwitcher />
      <AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()} />
    </LocaleProvider>;
    const view = render(panel());
    expect(document.querySelector(".agent-chat__working-text")?.textContent).toBe("Script Writer is working...");
    fireEvent.click(screen.getByRole("button", { name: "切换到中文" }));
    expect(screen.getByRole("status", { name: "编剧正在工作..." })).toBeTruthy();
    chat.state.turnsById["turn-world"].status = "completed";
    chat.state.items = [capabilityActivity({ turn_id: "turn-character", sequence: 2,
      capability_id: "character_design", capability_display_name: "Character Designer" })];
    view.rerender(panel());
    expect(document.querySelector(".agent-chat__working-text")?.textContent).toBe("角色设计师正在工作...");
    expect(screen.queryByRole("status", { name: "编剧正在工作..." })).toBeNull();
  });

  it("shows the persisted script checkpoints as named steps rather than separate scripts", () => {
    const stages = ["narrative_direction", "style_lock", "storyboard_plan"];
    const timeline = normalizeAgentCanvasChatTimelineV2({
      workflow_id: roleMotionWorkflow.workflow_id, conversation_id: "conversation-1",
      guidance_session: null, continuations: [], current_session_actions: [], next_cursor: 3,
      items: stages.map((stage, index) => ({
        entry_id: `script-entry-${index}`, workflow_id: roleMotionWorkflow.workflow_id,
        conversation_id: "conversation-1", sequence_no: index + 1, entry_type: "expert_activity",
        speaker: null, content: "Script Writer", command_plan: null, action_receipt: null,
        created_at: "2026-11-13T02:40:45Z",
        metadata: { activity_id: `script-activity-${index}`, turn_id: `script-turn-${index}`,
          capability_id: "script_authoring", capability_display_name: "Script Writer",
          journey_stage: stage, status: "completed" },
      })),
    });
    panelMocks.useAgentCanvasChat.mockReturnValue(mockChatResult(timeline.items));
    render(<LocaleProvider initialLocale="zh-CN">
      <AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()} />
    </LocaleProvider>);

    for (const name of ["叙事设计已完成", "风格设定已完成", "分镜规划已完成"]) {
      expect(screen.getByRole("status", { name })).toBeTruthy();
      expect(screen.getByText(name)).toBeTruthy();
    }
    expect(screen.queryByText(/脚本 [123]/)).toBeNull();
  });
});

describe("assistant presentation streams", () => {
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  const reply = {
    item_type: "message" as const, message_kind: "conversation" as const,
    message_id: "new-reply", conversation_id: "conversation-1", speaker: "adcraft_video_agent" as const,
    text: "新的回复会逐字出现，并且在刷新数据时继续显示，不从头重复播放。".repeat(3),
    sequence: 11, linked_node_ids: [], script_node_id: null, proposal_id: null, capability_id: null,
    created_at: "2026-11-11T00:00:00Z",
  };
  const view: PresentationStreamView = {
    stream_id: "stream-1", status: "open", generation_id: "generation-1", reasoning_text: "",
    text: reply.text, reasoning_started_at: null, answer_started_at: 0, terminal_at_ms: null,
    last_sequence_no: 1, stream_kind: "assistant", turn_id: "turn-1", node_id: null,
    authoritative_id: null, error_code: null, protocol_error: null, last_event_type: "delta", last_event: null,
  };
  function setChat(items: ChatTimelineItemV2[], streams: Record<string, PresentationStreamView> = {}) {
    const chat = mockChatResult(items);
    panelMocks.useAgentCanvasChat.mockReturnValue({ ...chat, state: {
      ...chat.state, initialTimelineSequence: 10, presentationStreams: streams,
    } });
  }
  const panel = () => <AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()} />;

  it("shows history immediately and types only a newly received Agent reply", () => {
    vi.useFakeTimers();
    const history = { ...reply, message_id: "history", sequence: 10, text: "Existing history" };
    setChat([history]);
    const { rerender } = render(panel());
    expect(screen.getByText(history.text)).toBeTruthy();
    expect(document.querySelector('[data-typing="true"]')).toBeNull();
    const user = { ...reply, message_id: "user", speaker: "user" as const, text: "My request" };
    setChat([history, user, reply]);
    rerender(panel());
    expect(screen.getByText(user.text)).toBeTruthy();
    const animated = document.querySelector('[data-typing="true"]')!;
    expect(animated.textContent).toBe("");
    act(() => vi.advanceTimersByTime(240));
    const partial = animated.textContent!;
    expect(partial.length).toBeGreaterThan(0);
    expect(partial.length).toBeLessThan(reply.text.length);
    setChat([history, user, { ...reply }]);
    rerender(panel());
    expect(animated.textContent).toBe(partial);
    act(() => vi.advanceTimersByTime(8_000));
    expect(animated.textContent).toBe(reply.text);
    expect(animated.getAttribute("aria-busy")).toBe("false");
  });

  it("keeps a completed stream visible until commit arrives, then continues at the same character", () => {
    vi.useFakeTimers();
    setChat([], { stream: view });
    const { rerender } = render(panel());
    act(() => vi.advanceTimersByTime(240));
    const partial = document.querySelector(".agent-chat__message-text")!.textContent;
    expect(partial!.length).toBeGreaterThan(0);
    const completed = { ...view, status: "completed" as const, authoritative_id: reply.message_id };
    setChat([], { stream: completed });
    rerender(panel());
    expect(document.querySelector(".agent-chat__live-turn")).toBeTruthy();
    expect(document.querySelector(".agent-chat__message-text")!.textContent).toBe(partial);
    setChat([reply], { stream: completed });
    rerender(panel());
    expect(document.querySelector(".agent-chat__live-turn")).toBeNull();
    expect(screen.getAllByRole("article", { name: "Agent message" })).toHaveLength(1);
    expect(document.querySelector(".agent-chat__message-text")!.textContent).toBe(partial);
    act(() => vi.advanceTimersByTime(8_000));
    expect(document.querySelector(".agent-chat__message-text")!.textContent).toBe(reply.text);
  });

  it("does not project assistant presentation streams into the visible timeline", () => {
    const panelPath = resolve(process.cwd(), "src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx");
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const panelSource = readFileSync(panelPath, "utf8");
    const css = readFileSync(cssPath, "utf8");

    expect(panelSource).not.toContain("PresentationStreamRow");
    expect(panelSource).not.toContain("activePresentationStreams");
    expect(panelSource).not.toContain("presentationVersion");
    expect(css).not.toContain(".agent-chat__presentation-stream");
  });
});

describe("TimelineHydrationSkeleton", () => {
  afterEach(() => cleanup());

  it("keeps pointer-backed decisions visible while their details load", () => {
    render(<TimelineHydrationSkeleton itemType="proposal" />);

    expect(screen.getByRole("status", { name: "Loading proposal" })).toBeTruthy();
    expect(screen.getByText("Loading proposal…")).toBeTruthy();
  });
});

function proposalAction(
  action: ProposalActionDescriptorV2["action"],
  label: string,
  optionId: string | null = null,
): ProposalActionDescriptorV2 {
  return {
    action_id: `action-${action}`,
    action,
    label,
    proposal_id: "proposal-1",
    expected_session_revision: 7,
    confirmation_required: false,
    reason: `${label} for the active topic.`,
    option_id: optionId,
    enabled: true,
    disabled_reason: null,
  };
}

const proposalCard: ChatProposalCardV2 = {
  item_type: "proposal",
  proposal: {
    proposal_id: "proposal-1",
    workflow_id: "workflow-1",
    turn_id: "turn-1",
    video_skill_run_id: null,
    topic_id: "topic-character",
    creative_direction_snapshot_id: null,
    proposal_revision: 1,
    source_proposal_id: null,
    proposal_kind: "character",
    capability_id: "character_design",
    capability_display_name: "Character Designer",
    options: [{
      option_id: "option-1",
      title: "Hero",
      public_summary: "A focused campaign hero",
      key_decisions: ["Contemporary wardrobe", "Confident posture"],
    }],
    proposed_references: [],
    target_node_id: null,
    target_node_revision: null,
    proposal_purpose: null,
    availability: "open",
    application_count: 0,
    latest_application: null,
    materialization: null,
    guidance_session_id: "guidance-1",
    guidance_session_revision: 7,
    actions: [
      proposalAction("select_option", "Use this direction"),
      proposalAction("revise_options", "Revise options"),
      proposalAction("defer_topic", "Decide later"),
      proposalAction("exclude_element", "Exclude character"),
      proposalAction("delegate_choice", "Let AdCraft choose"),
    ],
    created_at: "2026-08-04T00:00:00Z",
    updated_at: "2026-08-04T00:00:00Z",
  },
  sequence: 4,
  created_at: "2026-08-04T00:00:00Z",
};

const roleMotionWorkflow: AgentCanvasWorkflowV2 = {
  workflow_id: "workflow-role-motion",
  project_id: "project-role-motion",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 1,
  layout_revision: 1,
  nodes: [],
  bindings: [],
  assets: [],
};

describe("Draft receipt canvas handoff", () => {
  afterEach(cleanup);

  function createdReceipt(status: "applied" | "applied_with_run_error" = "applied"): ChatActionReceiptCardV2 {
    return {
      item_type: "action_receipt", sequence: 5, created_at: proposalCard.created_at,
      action_receipt: {
        receipt_id: "receipt-created", workflow_id: roleMotionWorkflow.workflow_id,
        plan_id: null, action_id: "turn-1", proposal_id: "proposal-1", proposal_option_id: "option-1",
        proposal_action: "select_option", actor_kind: "user", idempotency_key: "created-1",
        status, summary: "已创建 2 个草稿节点。", created_node_ids: ["draft-a", "draft-b"],
        updated_node_ids: [], deleted_node_ids: [], created_binding_ids: [], deleted_binding_ids: [],
        queued_execution_ids: [], run_queue_errors: status === "applied" ? [] : ["Queue unavailable"],
        operation_results: [], workflow_revision: 2, before_workflow_revision: 1,
        placement_hints: [], continuation_turn_id: null, superseded_by: null,
        error_code: null, error_message: null, created_at: proposalCard.created_at,
      },
    };
  }

  it("keeps an absorbed receipt until every created card has painted, even after the timeline replaces it", () => {
    const receipt = createdReceipt();
    const applied: ChatProposalCardV2 = { ...proposalCard, proposal: { ...proposalCard.proposal,
      availability: "applied", latest_application: {
        application_id: "application-1", option_id: "option-1", action: "select_option",
        receipt_id: receipt.action_receipt.receipt_id, created_node_ids: ["draft-a", "draft-b"],
        queued_execution_ids: [], created_at: proposalCard.created_at,
      } } };
    const chat = mockChatResult([applied, receipt]);
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    const panel = (ids: string[], workflow = roleMotionWorkflow) => <AgentCanvasChatPanel
      workflow={workflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()}
      renderedCanvasNodeIds={new Set(ids)} />;
    const view = render(panel([]));
    expect(screen.getByText("已创建 2 个草稿节点。")).toBeTruthy();
    chat.state.items = [applied];
    view.rerender(panel(["unrelated", "draft-a"]));
    expect(screen.getByText("已创建 2 个草稿节点。")).toBeTruthy();
    view.rerender(panel(["draft-a", "draft-b"]));
    expect(screen.queryByText("已创建 2 个草稿节点。")).toBeNull();
    expect(screen.getByText("A focused campaign hero")).toBeTruthy();
  });

  it("removes a standalone creation receipt only after canvas rendering", () => {
    const queued: ChatTimelineItemV2 = {
      item_type: "message", message_id: "draft-queued", message_kind: "planning_progress",
      conversation_id: "conversation-1", speaker: "adcraft_video_agent", text: "Creating draft nodes",
      linked_node_ids: [], script_node_id: null, proposal_id: null, sequence: 3,
      capability_id: "character_design", created_at: proposalCard.created_at,
      metadata: { materialization_id: "materialization-1", proposal_id: "proposal-1", status: "queued" },
    };
    const chat = mockChatResult([queued, createdReceipt()]);
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    const panel = (ids: string[]) => <AgentCanvasChatPanel workflow={roleMotionWorkflow}
      chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()} renderedCanvasNodeIds={new Set(ids)} />;
    const view = render(panel([]));
    expect(screen.getByText("已创建 2 个草稿节点。")).toBeTruthy();
    view.rerender(panel(["draft-a", "draft-b"]));
    expect(screen.queryByText("已创建 2 个草稿节点。")).toBeNull();
    expect(screen.queryByText("Creating draft nodes")).toBeNull();
  });

  it("keeps receipt errors visible after all created nodes render", () => {
    panelMocks.useAgentCanvasChat.mockReturnValue(mockChatResult([createdReceipt("applied_with_run_error")]));
    render(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]}
      onFocusNode={vi.fn()} renderedCanvasNodeIds={new Set(["draft-a", "draft-b"])} />);
    expect(screen.getByText("Queue unavailable")).toBeTruthy();
  });

  it("does not carry a pending receipt into another workflow", () => {
    const chat = mockChatResult([createdReceipt()]);
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    const panel = (workflow = roleMotionWorkflow) => <AgentCanvasChatPanel workflow={workflow}
      chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()} />;
    const view = render(panel());
    expect(screen.getByText("已创建 2 个草稿节点。")).toBeTruthy();
    chat.state.items = [];
    view.rerender(panel({ ...roleMotionWorkflow, workflow_id: "workflow-next" }));
    expect(screen.queryByText("已创建 2 个草稿节点。")).toBeNull();
  });
});

function capabilityActivity(
  overrides: Partial<ChatCapabilityActivityV2> = {},
): ChatCapabilityActivityV2 {
  return {
    item_type: "expert_activity",
    activity_id: "activity-world",
    turn_id: "turn-world",
    capability_id: "world_setting",
    capability_display_name: "World Setting Designer",
    status: "working",
    sequence: 1,
    started_at: "2026-08-04T00:00:00Z",
    finished_at: null,
    message: null,
    error_code: null,
    elapsed_ms: null,
    attempt_stage: null,
    retryable: false,
    validation_paths: [],
    suggested_actions: [],
    completion_mode: null,
    warning_code: null,
    ...overrides,
  };
}

function renderedRoleMotionStates(): Record<string, string> {
  return Object.fromEntries([...document.querySelectorAll<HTMLElement>(
    '[data-testid="agent-role-animation-double"]',
  )].map((animation) => [
    animation.dataset.capabilityId ?? "",
    animation.dataset.motionState ?? "",
  ]));
}

describe("AgentCanvasChatPanel role motion integration", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it.each([false, true])("keeps the panel title without a status subtitle (working=%s)", (working) => {
    panelMocks.useAgentCanvasChat.mockReturnValue(mockChatResult(working ? [capabilityActivity()] : []));
    render(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()} />);
    const identity = document.querySelector(".agent-chat__header .agent-chat__identity");
    expect(identity?.textContent).toBe("AdCraft Video Agent");
    expect(identity?.querySelector("span")).toBeNull();
    expect(screen.getByRole("button", { name: "Collapse AdCraft Bot panel" })).toBeTruthy();
    if (working) expect(renderedRoleMotionStates()).toEqual({ world_setting: "working" });
  });

  it("animates a working activity before its exact turn is hydrated", () => {
    const chat = mockChatResult([capabilityActivity()]);
    chat.state.turnsById = {};
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    render(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()} />);
    expect(renderedRoleMotionStates()).toEqual({ world_setting: "working" });
  });

  it("hands animation to the latest role in the Timeline", () => {
    const roles = [
      "world_setting", "product_design", "prop_design", "character_design", "scene_design",
      "script_authoring", "storyboard_design", "video_direction", "bgm_direction", "quick_media",
    ] as const;
    panelMocks.useAgentCanvasChat.mockReturnValue(mockChatResult(roles.map((capabilityId, index) => (
      capabilityActivity({
        activity_id: `activity-${capabilityId}`,
        turn_id: `turn-${capabilityId}`,
        capability_id: capabilityId,
        capability_display_name: capabilityId,
        sequence: index + 1,
      })
    ))));
    render(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()} />);
    expect(renderedRoleMotionStates()).toEqual(Object.fromEntries(
      roles.map((role) => [role, role === "quick_media" ? "working" : "idle"]),
    ));
  });

  it("keeps the latest role animated independently of global model wait", async () => {
    const items: ChatTimelineItemV2[] = [
      capabilityActivity(),
      capabilityActivity({
        activity_id: "activity-scene",
        turn_id: "turn-scene",
        capability_id: "scene_design",
        capability_display_name: "Scene Designer",
        sequence: 2,
      }),
    ];
    panelMocks.useAgentCanvasChat.mockReturnValue(mockChatResult(items));

    const { rerender } = render(
      <AgentCanvasChatPanel
        workflow={roleMotionWorkflow}
        chatRevision={0}
        chatEvents={[]}
        onFocusNode={vi.fn()}
      />,
    );

    expect(renderedRoleMotionStates()).toEqual({
      world_setting: "idle",
      scene_design: "working",
    });
    expect(panelMocks.prepareRoleVisual).toHaveBeenCalledWith("world_setting", "bitmap");
    expect(panelMocks.prepareRoleVisual).toHaveBeenCalledWith("scene_design", "animated");

    panelMocks.useAgentCanvasChat.mockReturnValue(mockChatResult(items, true));
    rerender(
      <AgentCanvasChatPanel
        workflow={roleMotionWorkflow}
        chatRevision={1}
        chatEvents={[]}
        onFocusNode={vi.fn()}
      />,
    );

    expect(renderedRoleMotionStates()).toEqual({
      world_setting: "idle",
      scene_design: "working",
    });
    await waitFor(() => {
      expect(panelMocks.prepareRoleVisual.mock.calls.filter(([, mode]) => mode === "animated")
        .map(([capabilityId]) => capabilityId)).toEqual(expect.arrayContaining(["scene_design"]));
    });
  });

  it("stops only the role whose owning turn became terminal", () => {
    const items = [capabilityActivity(), capabilityActivity({
      activity_id: "activity-scene",
      turn_id: "turn-scene",
      capability_id: "scene_design",
      capability_display_name: "Scene Designer",
      sequence: 2,
    })];
    panelMocks.useAgentCanvasChat.mockReturnValue(mockChatResult(items, false, {
      "turn-world": {
        turn_id: "turn-world", workflow_id: roleMotionWorkflow.workflow_id, conversation_id: "conversation-1",
        status: "failed", turn_kind: "capability", request: {}, error_code: null, error_message: null,
        creation_mode: null, guidance_session_revision: null, continuation: null, retry_of_turn_id: null,
        retry_attempt_no: 0, retryable: false, operation_stage: "failed", operation_failure: null,
        created_at: "2026-09-03T00:00:00Z", updated_at: "2026-09-03T00:00:00Z",
      },
    }));
    render(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()} />);
    expect(renderedRoleMotionStates()).toEqual({ world_setting: "idle", scene_design: "working" });
  });

  it("animates standalone working activity identity, stops terminal identity, and omits compact identity", () => {
    const { rerender } = render(<CapabilityActivityRow activity={capabilityActivity()} />);
    expect(renderedRoleMotionStates()).toEqual({ world_setting: "working" });

    rerender(<CapabilityActivityRow activity={capabilityActivity({ status: "failed" })} />);
    expect(renderedRoleMotionStates()).toEqual({ world_setting: "idle" });

    rerender(<CapabilityActivityRow activity={capabilityActivity()} compact />);
    expect(renderedRoleMotionStates()).toEqual({});
  });

  it.each([
    [
      "completed",
      [capabilityActivity({
        status: "completed",
        finished_at: "2026-08-04T00:01:00Z",
      })],
      "world_setting",
    ],
    ["waiting-user", [proposalCard], "character_design"],
  ] as const)("only settles a terminal %s current stage", (label, items, capabilityId) => {
    panelMocks.useAgentCanvasChat.mockReturnValue(mockChatResult([...items], true));

    render(
      <AgentCanvasChatPanel
        workflow={roleMotionWorkflow}
        chatRevision={0}
        chatEvents={[]}
        onFocusNode={vi.fn()}
      />,
    );

    expect(renderedRoleMotionStates()).toEqual({ [capabilityId]: label === "completed" ? "idle" : "working" });
  });

  it("does not expose a failed working Role as a static or waiting visual", async () => {
    panelMocks.getRoleVisualSnapshot.mockReturnValue({
      status: "fallback", source: "/role.png", Artwork: null, error: "role chunk unavailable",
      generation: 1, fallbackKind: "bitmap", retryAvailable: true,
    });
    panelMocks.useAgentCanvasChat.mockReturnValue(mockChatResult([
      capabilityActivity(),
    ]));

    render(
      <AgentCanvasChatPanel
        workflow={roleMotionWorkflow}
        chatRevision={0}
        chatEvents={[]}
        onFocusNode={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByRole("complementary", { name: "AdCraft Video Agent" })).toBeTruthy());
    expect(panelMocks.prepareRoleVisual).toHaveBeenCalledWith("world_setting", "animated");
    expect(screen.getByText("Role animation could not be loaded.")).toBeTruthy();
    expect(screen.queryByText("World Setting Designer")).toBeNull();
    expect(document.querySelector("[data-role-waiting-motion=\"true\"]")).toBeNull();
  });
});

describe("ProposalCard", () => {
  afterEach(() => cleanup());

  it("uses the select descriptor and creates a Draft without a second generation choice", () => {
    const onSelect = vi.fn().mockResolvedValue(undefined);
    render(
      <ProposalCard
        card={proposalCard}
        pending={false}
        onSelect={onSelect}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("Hero").closest("button")!);
    fireEvent.click(screen.getByRole("button", { name: "Use this direction" }));

    expect(onSelect).toHaveBeenCalledWith(
      "proposal-1",
      expect.objectContaining({ action_id: "action-select_option", action: "select_option" }),
      "option-1",
      [],
    );
    expect(screen.queryByText("Contemporary wardrobe")).toBeNull();
    expect(screen.queryByText("Confident posture")).toBeNull();
    expect(screen.queryByRole("button", { name: "Generate now" })).toBeNull();
  });

  it("keeps the Timeline proposal as concise read-only history", () => {
    render(
      <ProposalCard
        card={proposalCard}
        pending={false}
        readOnly
      />,
    );

    expect(screen.getByText("A focused campaign hero")).toBeTruthy();
    expect(screen.queryByText("Contemporary wardrobe")).toBeNull();
    expect(screen.queryByText("Confident posture")).toBeNull();
    expect(screen.queryByRole("button", { name: "Use this direction" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Revise options" })).toBeNull();
  });

  it("renders an applied Timeline proposal as a non-interactive option preview", () => {
    render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            availability: "applied",
            options: [
              proposalCard.proposal.options[0]!,
              {
                option_id: "option-2",
                title: "Everyday warmth",
                public_summary: "A familiar family moment with a calm domestic tone.",
                key_decisions: [],
              },
              {
                option_id: "option-3",
                title: "Natural sanctuary",
                public_summary: "A gentle world shaped by forests and morning light.",
                key_decisions: [],
              },
            ],
            application_count: 1,
            latest_application: {
              application_id: "application-1",
              option_id: "option-3",
              action: "select_option",
              receipt_id: "receipt-1",
              created_node_ids: ["node-character-1"],
              queued_execution_ids: [],
              created_at: "2026-08-04T00:01:00Z",
            },
            materialization: {
              materialization_id: "materialization-1",
              option_id: "option-1",
              turn_id: "turn-materialization-1",
              status: "completed",
              attempt_no: 1,
              retryable: false,
              error: null,
              created_at: "2026-08-04T00:01:00Z",
              updated_at: "2026-08-04T00:01:01Z",
            },
          },
        }}
        pending={false}
        readOnly
      />,
    );

    const selectedOption = screen.getByRole("article", { name: "Selected option: Natural sanctuary" });
    expect(selectedOption).toBeTruthy();
    expect(selectedOption.textContent).not.toContain("Selected");
    expect(screen.queryByText("Selected")).toBeNull();
    expect(screen.getByText("A")).toBeTruthy();
    expect(screen.getByText("B")).toBeTruthy();
    expect(screen.getByText("C")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Natural sanctuary/ })).toBeNull();
    expect(screen.queryByText(/Applied 1 time/)).toBeNull();
    expect(screen.queryByRole("status", { name: "Proposal materialization completed" })).toBeNull();
  });

  it("shows an optimistic selection in the historical proposal card", () => {
    render(
      <ProposalCard
        card={proposalCard}
        pending
        readOnly
        optimisticSelectedOptionId="option-1"
      />,
    );

    expect(screen.getByRole("article", { name: "Selected option: Hero" })).toBeTruthy();
  });

  it("renders historical option markers without circular chrome", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const markerRule = css.match(/\.agent-chat__historical-option-marker\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(markerRule).toBeTruthy();
    expect(markerRule).not.toContain("border:");
    expect(markerRule).not.toContain("border-radius:");
    expect(markerRule).toContain("font-size: 11px");
  });

  it("defines a visible selected state for interactive proposal options", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const selectedRule = css.match(/\.agent-chat__proposal-option\.is-selected\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(selectedRule).toBeTruthy();
    expect(selectedRule).toContain("border:");
    expect(selectedRule).toContain("background:");
    expect(selectedRule).toContain("box-shadow:");
  });

  it.each(["queued", "working"] as const)(
    "keeps the selected direction visible and disables every action while materialization is %s",
    (status) => {
      render(
        <ProposalCard
          card={{
            ...proposalCard,
            proposal: {
              ...proposalCard.proposal,
              materialization: {
                materialization_id: "materialization-1",
                option_id: "option-1",
                turn_id: "turn-materialization-1",
                status,
                attempt_no: 1,
                retryable: false,
                error: null,
                created_at: "2026-08-08T00:00:00Z",
                updated_at: "2026-08-08T00:00:01Z",
              },
            },
          }}
          pending={false}
          onSelect={vi.fn()}
          onRevise={vi.fn()}
          onApplyAction={vi.fn()}
        />,
      );

      expect(screen.getByRole("status", { name: `Proposal materialization ${status}` })).toBeTruthy();
      expect((screen.getByRole("button", { name: "Use this direction" }) as HTMLButtonElement).disabled).toBe(true);
      expect((screen.getByRole("button", { name: "Revise options" }) as HTMLButtonElement).disabled).toBe(true);
      expect((screen.getByRole("button", { name: "Decide later" }) as HTMLButtonElement).disabled).toBe(true);
    },
  );

  it("preserves the selected option and references after a retryable failure", () => {
    const onRetryMaterialization = vi.fn().mockResolvedValue(true);
    const proposedReference = {
      source_kind: "image_asset" as const,
      source_id: "asset-hero-1",
      binding_kind: "image_reference" as const,
      input_role: "visual_reference" as const,
      required: true,
      display_order: 0,
      display_name: "Hero reference",
      media_type: "image" as const,
    };
    const { rerender } = render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            proposed_references: [proposedReference],
          },
        }}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
        onRetryMaterialization={onRetryMaterialization}
      />,
    );

    fireEvent.click(screen.getByText("Hero").closest("button")!);
    fireEvent.click(screen.getByRole("checkbox", { name: "Required" }));
    expect((screen.getByRole("checkbox", { name: "Required" }) as HTMLInputElement).checked).toBe(false);

    rerender(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            proposal_revision: 2,
            proposed_references: [proposedReference],
            materialization: {
              materialization_id: "materialization-1",
              option_id: "option-1",
              turn_id: "turn-materialization-1",
              status: "failed",
              attempt_no: 1,
              retryable: true,
              error: {
                code: "capability_materialization_failed",
                message: "The selected direction could not be prepared.",
                actionable_failure: {
                  failure_class: "transient",
                  retry_scope: "turn",
                  user_action: "retry",
                  retryable: true,
                },
              },
              created_at: "2026-08-08T00:00:00Z",
              updated_at: "2026-08-08T00:00:01Z",
            },
          },
        }}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
        onRetryMaterialization={onRetryMaterialization}
      />,
    );

    expect(screen.getByText("The selected direction could not be prepared.")).toBeTruthy();
    expect(screen.getByText("Hero reference")).toBeTruthy();
    expect((screen.getByRole("checkbox", { name: "Required" }) as HTMLInputElement).checked).toBe(false);
    expect((screen.getByRole("button", { name: "Use this direction" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Revise options" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Retry draft creation" }));
    expect(onRetryMaterialization).toHaveBeenCalledWith("turn-materialization-1");
  });

  it("does not offer a failed materialization retry when the backend marks it non-retryable", () => {
    render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            materialization: {
              materialization_id: "materialization-1",
              option_id: "option-1",
              turn_id: "turn-materialization-1",
              status: "failed",
              attempt_no: 1,
              retryable: false,
              error: {
                code: "proposal_reference_unavailable",
                message: "A required reference is no longer available.",
              },
              created_at: "2026-08-08T00:00:00Z",
              updated_at: "2026-08-08T00:00:01Z",
            },
          },
        }}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );

    expect(screen.getByText("A required reference is no longer available.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry draft creation" })).toBeNull();
    expect((screen.getByRole("button", { name: "Use this direction" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("redesigns a failed Proposal only through its returned revise descriptor", () => {
    const onRevise = vi.fn().mockResolvedValue(undefined);
    render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            proposal_kind: "storyboard",
            materialization: {
              materialization_id: "materialization-storyboard-1",
              option_id: "option-1",
              turn_id: "turn-materialization-storyboard-1",
              status: "failed",
              attempt_no: 1,
              retryable: false,
              error: {
                code: "storyboard_materialization_invalid",
                message: "The Storyboard direction must be redesigned.",
                actionable_failure: {
                  failure_class: "deterministic",
                  retry_scope: "none",
                  user_action: "redesign",
                  retryable: false,
                },
              },
              created_at: "2026-08-08T00:00:00Z",
              updated_at: "2026-08-08T00:00:01Z",
            },
          },
        }}
        pending={false}
        readOnly
        onRevise={onRevise}
      />,
    );

    expect(screen.queryByRole("button", { name: "Use this direction" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Redesign proposal" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Proposal revision" }), {
      target: { value: "Use a clearer three-shot progression." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit proposal revision" }));

    expect(onRevise).toHaveBeenCalledWith(
      "proposal-1",
      expect.objectContaining({ action: "revise_options" }),
      "Use a clearer three-shot progression.",
    );
  });

  it("dispatches revise, defer, exclude, and delegate through their structured descriptors", () => {
    const onRevise = vi.fn().mockResolvedValue(undefined);
    const onApplyAction = vi.fn().mockResolvedValue(undefined);
    render(
      <ProposalCard
        card={proposalCard}
        pending={false}
        onSelect={vi.fn()}
        onRevise={onRevise}
        onApplyAction={onApplyAction}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Revise options" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Proposal revision" }), {
      target: { value: "Make the character warmer." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit proposal revision" }));
    expect(onRevise).toHaveBeenCalledWith(
      "proposal-1",
      expect.objectContaining({ action: "revise_options" }),
      "Make the character warmer.",
    );

    for (const [label, action] of [
      ["Decide later", "defer_topic"],
      ["Exclude character", "exclude_element"],
      ["Let AdCraft choose", "delegate_choice"],
    ] as const) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(onApplyAction).toHaveBeenCalledWith(
        "proposal-1",
        expect.objectContaining({ action }),
      );
    }
  });

  it("does not expose legacy custom-direction actions on Timeline history", () => {
    render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            actions: [
              ...proposalCard.proposal.actions,
              proposalAction(
                "custom_direction",
                "Use a custom direction",
              ),
            ],
          },
        }}
        pending={false}
        readOnly
      />,
    );

    expect(screen.queryByRole("textbox", { name: "Custom creative direction" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Use a custom direction" })).toBeNull();
  });

  it("keeps applied proposal content visible but disables all stale actions", () => {
    render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            availability: "applied",
            application_count: 1,
            latest_application: {
              application_id: "application-1",
              option_id: "option-1",
              action: "select_option",
              receipt_id: "receipt-1",
              created_node_ids: ["node-character-1"],
              queued_execution_ids: [],
              created_at: "2026-08-04T00:01:00Z",
            },
          },
        }}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );

    expect(screen.getByText("Hero")).toBeTruthy();
    expect(screen.getByText(/Applied 1 time/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Use this direction" })).toBeNull();
  });

  it("renders enabled historical actions on a superseded proposal option", () => {
    const onApplyAction = vi.fn().mockResolvedValue(undefined);
    render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            availability: "superseded",
            actions: [
              proposalAction("reuse_direction", "Use this direction", "option-1"),
              proposalAction("revise_direction", "Revise this direction", "option-1"),
            ],
          },
        }}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={onApplyAction}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Use this direction" }));
    expect(onApplyAction).toHaveBeenCalledWith(
      "proposal-1",
      expect.objectContaining({ action: "reuse_direction", option_id: "option-1" }),
    );
    expect(screen.getByRole("button", { name: "Revise this direction" })).toBeTruthy();
  });

  it("renders only the World Setting actions returned by the backend", () => {
    render(
      <ProposalCard
        card={{
          ...proposalCard,
          proposal: {
            ...proposalCard.proposal,
            proposal_kind: "world_setting",
            capability_id: "world_setting",
            capability_display_name: "World Setting Designer",
            options: [
              { option_id: "world-1", title: "Quiet future", public_summary: "A calm near-future city.", key_decisions: ["Quiet technology"] },
              { option_id: "world-2", title: "Living heritage", public_summary: "Modern craft rooted in tradition.", key_decisions: ["Visible craft heritage"] },
            ],
            actions: [
              proposalAction("select_option", "Use this world"),
              proposalAction("revise_options", "Revise worlds"),
              proposalAction("delegate_choice", "Let AdCraft choose"),
            ],
          },
        }}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Quiet future/ }));
    expect(screen.getByRole("button", { name: "Use this world" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Revise worlds" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Let AdCraft choose" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Decide later" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Exclude character" })).toBeNull();
  });
});

describe("progress and action cards", () => {
  afterEach(() => cleanup());

  it("renders progressive guidance state without a fixed production recipe", () => {
    const session: GuidedSessionStateV2 = {
      session_id: "guidance-1",
      workflow_id: "workflow-1",
      status: "active",
      goal: {
        requested_output: "video",
        delivery_scope: "generated_media",
        summary: "Create a launch film.",
        explicit_constraints: {},
      },
      creative_authority: {
        authority: "user",
        source: "explicit_user",
        decided_at_turn_id: "turn-authority-1",
        revision: 1,
      },
      current_checkpoint: {
        checkpoint_id: "checkpoint-1",
        workflow_id: "workflow-1",
        session_revision: 7,
        stage_kind: "scene",
        status: "waiting_user",
        trigger: "proposal_action",
        action_id: null,
      },
      narrative_direction: null,
      element_decisions: [],
      current_topic_id: "topic-scene",
      topics: [
        {
          topic_id: "topic-character",
          topic_kind: "character",
          title: "Lead character",
          status: "selected",
          capability_id: "character_design",
          capability_display_name: "Character Designer",
          related_node_ids: ["node-character-1"],
          source_proposal_id: "proposal-character",
          revision: 1,
        },
        {
          topic_id: "topic-scene",
          topic_kind: "scene",
          title: "Scene direction",
          status: "proposed",
          capability_id: "scene_design",
          capability_display_name: "Scene Designer",
          related_node_ids: [],
          source_proposal_id: "proposal-scene",
          revision: 1,
        },
      ],
      active_proposal_id: "proposal-scene",
      active_style_skill_run_id: null,
      completion: {
        authoring: "not_ready",
        delivery: "not_ready",
        editing_preparation: "not_ready",
        editing_node_id: null,
        matching_node_ids: ["node-character-1"],
        matching_asset_ids: [],
      },
      journey: {
        policy_version: "fixed_ad_production_v2",
        stage: "scene",
        stage_status: "waiting_user",
        stage_revision: 4,
        decisions: [{
          decision_id: "decision:scene:1",
          element_kind: "scene",
          occurrence_id: "occurrence:scene:1",
          occurrence_index: 1,
          outcome: "unresolved",
          source: "user",
          source_revision: 1,
          requirements: {},
        }],
        active_occurrence_id: "occurrence:scene:1",
        active_action: null,
        suspended_action: null,
        transition_evidence: [],
      },
      revision: 7,
      updated_at: "2026-08-04T00:00:00Z",
    };

    const { rerender } = render(<GuidanceSessionProgress session={session} />);

    expect(screen.getByText("Create a launch film.")).toBeTruthy();
    expect(screen.getByText("Scene · waiting user")).toBeTruthy();
    expect(screen.getByText("Creative 4/5")).toBeTruthy();
    expect(screen.getByText("Storyboard 0/4")).toBeTruthy();
    expect(screen.getByText("Delivery 0/3")).toBeTruthy();
    expect(screen.queryByText("Authoring: not ready")).toBeNull();
    expect(screen.queryByText("Direction: You")).toBeNull();
    expect(screen.queryByText("Current decision: scene 1 · unresolved")).toBeNull();

    rerender(<GuidanceSessionProgress session={{
      ...session,
      journey: {
        ...session.journey,
        stage: "completed",
        stage_status: "completed",
      },
    }} />);
    expect(screen.getByText("Completed")).toBeTruthy();
    expect(screen.queryByText("Completed · completed")).toBeNull();
  });

  it("renders only current stop or resume guidance actions", () => {
    const onApply = vi.fn().mockResolvedValue(undefined);
    render(
      <GuidedActionsCard
        actions={[
          {
            action_id: "action-stale",
            logical_key: "stop:old",
            action: "stop_guidance",
            state: "superseded",
            creating_turn_id: "turn-1",
            expected_session_revision: 6,
            label: "Old stop action",
            workflow_id: "workflow-1",
            confirmation_required: true,
            reason: "A newer session revision exists.",
            authority: null,
          },
          {
            action_id: "action-stop",
            logical_key: "stop:current",
            action: "stop_guidance",
            state: "pending",
            creating_turn_id: "turn-2",
            expected_session_revision: 7,
            label: "Stop guidance",
            workflow_id: "workflow-1",
            confirmation_required: true,
            reason: "Keep the current drafts.",
            authority: null,
          },
        ]}
        actingActionId={null}
        onApply={onApply}
      />,
    );

    expect(screen.queryByRole("button", { name: "Old stop action" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Stop guidance" }));
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({
      action_id: "action-stop",
      action: "stop_guidance",
    }));
  });
});

describe("command and receipt cards", () => {
  afterEach(() => cleanup());

  it("offers Confirm and Reject for a pending command", () => {
    const card: ChatCommandPlanCardV2 = {
      item_type: "command_plan",
      command_plan: {
        plan_id: "plan-1",
        workflow_id: "workflow-1",
        conversation_id: "conversation-1",
        source_turn_id: "turn-1",
        context_snapshot_id: "snapshot-1",
        base_workflow_revision: 3,
        expires_at: "2026-08-04T01:00:00Z",
        operations: [{
          operation_type: "delete_node",
          operation_id: "delete-1",
          node: { kind: "node_id", node_id: "node-1" },
        }],
        continuation_requested: false,
        risk: "destructive_authoring",
        confirmation_required: true,
        target_summary: "Delete the failed image draft.",
        operation_fingerprint: "fingerprint-1",
        idempotency_key: "command-1",
        status: "pending_confirmation",
        supersedes_plan_id: null,
        replacement_plan_id: null,
        actor: "agent",
        created_at: "2026-08-04T00:00:00Z",
        updated_at: "2026-08-04T00:00:00Z",
      },
      sequence: 5,
      created_at: "2026-08-04T00:00:00Z",
    };
    const onAction = vi.fn().mockResolvedValue(undefined);
    render(<CommandPlanCard card={card} pending={false} onAction={onAction} />);

    expect(screen.getByText("1 canvas change will be applied.")).toBeTruthy();
    expect(screen.queryByText("Delete Node")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Confirm command" }));
    fireEvent.click(screen.getByRole("button", { name: "Reject command" }));
    expect(onAction).toHaveBeenNthCalledWith(1, "plan-1", "confirm");
    expect(onAction).toHaveBeenNthCalledWith(2, "plan-1", "reject");
  });

  it("renders structured receipt errors and continuation state", () => {
    const card: ChatActionReceiptCardV2 = {
      item_type: "action_receipt",
      action_receipt: {
        receipt_id: "receipt-1",
        workflow_id: "workflow-1",
        plan_id: null,
        action_id: "action-select_option",
        proposal_id: "proposal-1",
        proposal_option_id: "option-1",
        proposal_action: "select_option",
        actor_kind: "user",
        idempotency_key: "proposal-select-1",
        status: "applied_with_run_error",
        summary: "Created the selected Draft.",
        created_node_ids: ["node-1"],
        updated_node_ids: [],
        deleted_node_ids: [],
        created_binding_ids: [],
        deleted_binding_ids: [],
        queued_execution_ids: [],
        run_queue_errors: ["The provider queue is temporarily unavailable."],
        operation_results: [],
        workflow_revision: 4,
        before_workflow_revision: 3,
        placement_hints: [],
        continuation_turn_id: "turn-next",
        superseded_by: null,
        error_code: "agent_runtime_unavailable",
        error_message: "Generation can be retried later.",
        created_at: "2026-08-04T00:00:00Z",
      },
      sequence: 6,
      created_at: "2026-08-04T00:00:00Z",
    };

    render(<ActionReceiptCard card={card} />);

    expect(screen.getByText("Created the selected Draft.")).toBeTruthy();
    expect(screen.getByText("Generation can be retried later.")).toBeTruthy();
    expect(screen.getByText("Planning continues automatically")).toBeTruthy();
  });

  it("shows capability work as status rather than another chat speaker", () => {
    const activity: ChatCapabilityActivityV2 = {
      item_type: "expert_activity",
      activity_id: "activity-1",
      turn_id: "turn-1",
      capability_id: "scene_design",
      capability_display_name: "Scene Designer",
      status: "working",
      sequence: 4,
      started_at: "2026-08-04T00:00:00Z",
      finished_at: null,
      message: null,
      error_code: null,
      elapsed_ms: null,
      attempt_stage: null,
      retryable: false,
      validation_paths: [],
      suggested_actions: [],
      completion_mode: null,
      warning_code: null,
    };
    render(<CapabilityActivityRow activity={activity} />);

    expect(screen.getByRole("status", { name: "Scene Designer is working" })).toBeTruthy();
    expect(screen.getByText("Scene Designer")).toBeTruthy();
    expect(screen.getByText("Working")).toBeTruthy();
    expect(document.querySelector<HTMLElement>(
      '[data-testid="agent-role-animation-double"]',
    )?.dataset.capabilityId).toBe("scene_design");
    expect(screen.queryByText("AdCraft Video Agent", { exact: false })).toBeNull();
  });

  it("separates the Agent identity header from its response content", () => {
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: "activity-content-separation",
      turn_id: "turn-content-separation",
      capability_id: "product_design",
      capability_display_name: "Product Designer",
      status: "completed",
      sequence: 5,
      started_at: "2026-08-27T00:00:00Z",
      finished_at: "2026-08-27T00:01:00Z",
      presentation_text: "The product language is ready for the next stage.",
      message: null,
      error_code: null,
      elapsed_ms: 60_000,
      attempt_stage: null,
      retryable: false,
      validation_paths: [],
      suggested_actions: [],
      completion_mode: null,
      warning_code: null,
    }} />);

    const identity = document.querySelector(".agent-chat__capability-identity");
    const content = document.querySelector(".agent-chat__activity-content");
    expect(identity).toBeTruthy();
    expect(content).toBeTruthy();
    expect(identity?.textContent ?? "").toContain("Product Designer");
    expect(content?.textContent ?? "").toContain("The product language is ready for the next stage.");
    expect(identity && content?.contains(identity)).toBe(false);
  });

  it("renders nested capability activity as a compact record without its duplicate identity icon", () => {
    render(<CapabilityActivityRow
      compact
      activity={{
        item_type: "expert_activity",
        activity_id: "activity-compact",
        turn_id: "turn-compact",
        capability_id: "product_design",
        capability_display_name: "Product Designer",
        status: "completed",
        sequence: 6,
        started_at: "2026-08-27T00:00:00Z",
        finished_at: "2026-08-27T00:01:00Z",
        presentation_text: "The product direction is ready.",
        message: null,
        error_code: null,
        elapsed_ms: 60_000,
        attempt_stage: null,
        retryable: false,
        validation_paths: [],
        suggested_actions: [],
        completion_mode: null,
        warning_code: null,
      }}
    />);

    expect(document.querySelector('[data-testid="agent-capability-icon"]')).toBeNull();
    expect(document.querySelector(".agent-chat__compact-capability-heading")?.textContent)
      .toContain("Product Designer");
    expect(screen.getByText("The product direction is ready.")).toBeTruthy();
  });

  it("puts the matching role icon before an interactive capability proposal", () => {
    render(
      <ProposalCard
        card={proposalCard}
        pending={false}
        onSelect={vi.fn()}
        onRevise={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );

    expect(document.querySelector<HTMLElement>(
      '[data-testid="agent-role-animation-double"]',
    )?.dataset.capabilityId).toBe("character_design");
  });

  it("renders nested proposal history without repeating the capability identity icon or name", () => {
    render(
      <ProposalCard
        card={proposalCard}
        pending={false}
        readOnly
        compact
      />,
    );

    expect(document.querySelector('[data-testid="agent-capability-icon"]')).toBeNull();
    expect(document.querySelector(".agent-chat__compact-capability-heading")).toBeNull();
  });

  it.each([
    ["World Setting", "World Setting 已完成。"],
    ["Product Designer", "Product Designer finished."],
  ])("hides the redundant completion body for %s", (_capability, redundantBody) => {
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: `activity-redundant-${_capability}`,
      turn_id: `turn-redundant-${_capability}`,
      capability_id: "world_setting",
      capability_display_name: _capability,
      status: "completed",
      sequence: 7,
      started_at: "2026-08-27T00:00:00Z",
      finished_at: "2026-08-27T00:01:00Z",
      presentation_text: redundantBody,
      message: null,
      error_code: null,
      elapsed_ms: 60_000,
      attempt_stage: null,
      retryable: false,
      validation_paths: [],
      suggested_actions: [],
      completion_mode: null,
      warning_code: null,
    }} />);

    expect(screen.getByText("Completed")).toBeTruthy();
    expect(screen.queryByText(redundantBody)).toBeNull();
  });

  it("presents backend activity duration and explanation as a compact section", () => {
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: "activity-completed",
      turn_id: "turn-completed",
      capability_id: "world_setting",
      capability_display_name: "Creative Direction",
      status: "completed",
      sequence: 8,
      started_at: "2026-08-27T00:00:00Z",
      finished_at: "2026-08-27T00:01:04Z",
      presentation_text: "Visual language locked for the next production stage.",
      message: null,
      error_code: null,
      elapsed_ms: 64_000,
      attempt_stage: null,
      retryable: false,
      validation_paths: [],
      suggested_actions: [],
      completion_mode: null,
      warning_code: null,
    }} />);

    expect(screen.getByRole("status", { name: "Creative Direction completed" })).toBeTruthy();
    expect(screen.getByText("Completed")).toBeTruthy();
    expect(screen.getByText("for 1m 4s")).toBeTruthy();
    expect(screen.getByText("Visual language locked for the next production stage.")).toBeTruthy();
  });

  it("uses the activity heading for work status without a second loading message", () => {
    const activity: ChatCapabilityActivityV2 = {
      item_type: "expert_activity",
      activity_id: "activity-loader",
      turn_id: "turn-loader",
      capability_id: "scene_design",
      capability_display_name: "Scene Designer",
      status: "working",
      sequence: 4,
      started_at: "2026-08-04T00:00:00Z",
      finished_at: null,
      message: null,
      error_code: null,
      elapsed_ms: null,
      attempt_stage: null,
      retryable: false,
      validation_paths: [],
      suggested_actions: [],
      completion_mode: null,
      warning_code: null,
    };

    const { rerender } = render(<CapabilityActivityRow activity={activity} />);

    expect(screen.getByText("Working")).toBeTruthy();
    expect(screen.queryByText("Preparing the next response...")).toBeNull();
    expect(document.querySelector(".agent-chat__activity-content")).toBeNull();

    rerender(<CapabilityActivityRow activity={{
      ...activity,
      status: "completed",
      finished_at: "2026-08-04T00:01:00Z",
    }} />);

    expect(screen.queryByText("Preparing the next response...")).toBeNull();

    rerender(<CapabilityActivityRow activity={{
      ...activity,
      status: "failed",
      finished_at: "2026-08-04T00:02:00Z",
      message: "The capability request failed.",
      error_code: "agent_failed",
    }} />);

    expect(screen.queryByText("Preparing the next response...")).toBeNull();
  });

  it("shows a superseded capability as replaced progress rather than a failure", () => {
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: "activity-storyboard-1",
      turn_id: "turn-storyboard-1",
      capability_id: "storyboard_design",
      capability_display_name: "Storyboard Artist",
      status: "superseded",
      sequence: 43,
      started_at: "2026-08-21T06:17:00Z",
      finished_at: "2026-08-21T06:18:00Z",
      message: null,
      error_code: "guidance_revision_conflict",
      elapsed_ms: 60000,
      attempt_stage: "initial",
      retryable: true,
      actionable_failure: {
        failure_class: "transient",
        retry_scope: "turn",
        user_action: "retry",
        retryable: true,
      },
      validation_paths: [],
      suggested_actions: ["retry", "revise_request"],
      completion_mode: null,
      warning_code: null,
    }} onRetry={vi.fn()} onReviseRequest={vi.fn()} />);

    expect(screen.getByText("Storyboard Artist was superseded by later progress")).toBeTruthy();
    expect(screen.queryByText(/failed/i)).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows bounded recovery actions for a backend-owned capability failure", () => {
    const onRetry = vi.fn();
    const onReviseRequest = vi.fn();
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: "activity-failed",
      turn_id: "turn-failed",
      capability_id: "scene_design",
      capability_display_name: "Scene Designer",
      status: "failed",
      sequence: 5,
      started_at: "2026-08-07T01:00:00Z",
      finished_at: "2026-08-07T01:07:00Z",
      message: "The capability request timed out.",
      error_code: "agent_deadline_exceeded",
      elapsed_ms: 420000,
      attempt_stage: "transport_retry",
      retryable: true,
      actionable_failure: {
        failure_class: "external",
        retry_scope: "turn",
        user_action: "retry",
        retryable: true,
      },
      validation_paths: [],
      suggested_actions: ["retry", "revise_request"],
      completion_mode: null,
      warning_code: null,
    }} onRetry={onRetry} onReviseRequest={onReviseRequest} />);

    expect(screen.queryByText("agent_deadline_exceeded")).toBeNull();
    fireEvent.click(screen.getByText("Technical details"));
    expect(screen.getByText(/agent_deadline_exceeded/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry Scene Designer activity" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Revise Scene Designer request" })).toBeNull();
    expect(onReviseRequest).not.toHaveBeenCalled();
  });

  it("offers request revision only for the typed revise action", () => {
    const onReviseRequest = vi.fn();
    const activity = {
      item_type: "expert_activity" as const,
      activity_id: "activity-revise",
      turn_id: "turn-revise",
      capability_id: "scene_design" as const,
      capability_display_name: "Scene Designer",
      status: "failed" as const,
      sequence: 5,
      started_at: "2026-08-07T01:00:00Z",
      finished_at: "2026-08-07T01:07:00Z",
      message: "The request must be revised.",
      error_code: "request_invalid",
      elapsed_ms: 420000,
      attempt_stage: "initial" as const,
      retryable: false,
      actionable_failure: {
        failure_class: "deterministic" as const,
        retry_scope: "none" as const,
        user_action: "revise" as const,
        retryable: false,
      },
      validation_paths: [],
      suggested_actions: ["retry" as const],
      completion_mode: null,
      warning_code: null,
    };

    render(<CapabilityActivityRow activity={activity} onRetry={vi.fn()} onReviseRequest={onReviseRequest} />);

    fireEvent.click(screen.getByRole("button", { name: "Revise Scene Designer request" }));
    expect(onReviseRequest).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Retry Scene Designer activity" })).toBeNull();
  });

  it("disables a failed activity retry while its recovery turn is working", () => {
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: "activity-retrying",
      turn_id: "turn-failed",
      capability_id: "scene_design",
      capability_display_name: "Scene Designer",
      status: "failed",
      sequence: 5,
      started_at: "2026-08-07T01:00:00Z",
      finished_at: "2026-08-07T01:07:00Z",
      message: "The capability request timed out.",
      error_code: "agent_deadline_exceeded",
      elapsed_ms: 420000,
      attempt_stage: "transport_retry",
      retryable: true,
      actionable_failure: {
        failure_class: "transient",
        retry_scope: "turn",
        user_action: "retry",
        retryable: true,
      },
      validation_paths: [],
      suggested_actions: ["retry"],
      completion_mode: null,
      warning_code: null,
    }} onRetry={vi.fn()} retrying />);

    expect((screen.getByRole("button", {
      name: "Retry Scene Designer activity",
    }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("treats deterministic fallback as completed with a warning", () => {
    render(<CapabilityActivityRow activity={{
      item_type: "expert_activity",
      activity_id: "activity-fallback",
      turn_id: "turn-fallback",
      capability_id: "product_design",
      capability_display_name: "Product Designer",
      status: "completed",
      sequence: 6,
      started_at: "2026-08-07T01:00:00Z",
      finished_at: "2026-08-07T01:01:00Z",
      message: null,
      error_code: null,
      elapsed_ms: null,
      attempt_stage: null,
      retryable: false,
      validation_paths: [],
      suggested_actions: [],
      completion_mode: "deterministic_fallback",
      warning_code: "specialist_materialization_fallback",
    }} />);

    expect(screen.getByText("Draft created with a simplified fallback.")).toBeTruthy();
    expect(screen.queryByText(/failed/i)).toBeNull();
  });
});

describe("AgentCanvasChatPanel Style integration", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("places the persistent Workflow Style control beside composer tools", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      workflow_id: "workflow-1",
      conversation_id: null,
      items: [],
      next_cursor: 0,
    }), { headers: { "Content-Type": "application/json" } })));
    const workflow: AgentCanvasWorkflowV2 = {
      workflow_id: "workflow-1",
      project_id: "project-1",
      workflow_schema_version: 2,
      canvas_model: "agent_canvas_v1",
      revision: 1,
      layout_revision: 1,
      nodes: [],
      bindings: [],
      assets: [],
      active_style_skill: {
        skill_run_id: "style-run-1",
        skill_id: "platform-default",
        skill_version: "1.0.0",
        title: "Platform Default",
        summary: "Balanced commercial video direction.",
        category: "commercial-craft",
        creative_direction_snapshot_id: "direction-1",
      },
    };

    render(
      <AgentCanvasChatPanel
        workflow={workflow}
        chatRevision={0}
        chatEvents={[]}
        onFocusNode={vi.fn()}
        onWorkflowRefresh={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Mention node or image asset" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Skill" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Resize AdCraft Video Agent panel" })).toBeTruthy();
  });

  it("hides the selected Skill marker while a proposal choice is active", () => {
    const panelPath = resolve(process.cwd(), "src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx");
    const panelSource = readFileSync(panelPath, "utf8");

    expect(panelSource).toMatch(/\{!conceptInteraction\s*&&\s*selectedSkillTitle\s*\?/);
  });

  it("renders proposal choice interactions as an overlay inside the Timeline shell", () => {
    const panelPath = resolve(process.cwd(), "src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx");
    const panelSource = readFileSync(panelPath, "utf8");
    const timelineShellIndex = panelSource.indexOf('<div className="agent-chat__timeline-shell">');
    const overlayInteractionIndex = panelSource.indexOf('agent-chat__current-interaction--overlay');
    const composerIndex = panelSource.indexOf('<div className="agent-chat__composer">');

    expect(overlayInteractionIndex).toBeGreaterThan(timelineShellIndex);
    expect(composerIndex).toBeGreaterThan(overlayInteractionIndex);
  });

  it("uses neutral surfaces with blue outlines in the fixed chat rail with plain Agent replies", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const panelRule = css.match(/^\.agent-chat\s*\{([\s\S]*?)\n\}/m)?.[1];
    const userMessageContainerRule = css.match(/\.agent-chat__message--user\s*\{([\s\S]*?)\n\}/m)?.[1];
    const agentMessageRule = css.match(/\.agent-chat__message--agent\s*:\s*is\(p, \.agent-chat__markdown\)\s*\{([\s\S]*?)\n\}/m)?.[1];
    const userMessageBodyRule = css.match(/\.agent-chat__message--user \.agent-chat__message-body\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(panelRule).toContain("top: 0");
    expect(panelRule).toContain("right: 0");
    expect(panelRule).toContain("bottom: 0");
    expect(panelRule).toContain("max-width: min(720px, calc(100vw - 24px));");
    expect(panelRule).toContain("--agent-chat-canvas: var(--surface-input)");
    expect(panelRule).toContain("--agent-chat-panel: var(--nav-bg)");
    expect(panelRule).toContain("--agent-chat-raised: var(--surface-raised)");
    expect(panelRule).toContain("--agent-chat-border: var(--border-default)");
    expect(panelRule).toContain("--agent-chat-strong-line: var(--border-strong)");
    expect(panelRule).toContain("--agent-chat-primary: var(--text-primary)");
    expect(panelRule).toContain("--agent-chat-secondary: var(--text-secondary)");
    expect(panelRule).toContain("--agent-chat-muted: var(--text-disabled)");
    expect(panelRule).toContain("background: var(--agent-chat-panel)");
    expect(panelRule).toContain("backdrop-filter: none");
    expect(panelRule).toContain("border-radius: 0");
    expect(css).toMatch(/\.agent-chat__message--agent > span\s*\{\s*display: none;/);
    expect(userMessageContainerRule).toContain("width: fit-content");
    expect(userMessageContainerRule).toContain("max-width: min(86%, 520px)");
    expect(agentMessageRule).toContain("padding: 0");
    expect(agentMessageRule).toContain("background: transparent");
    expect(userMessageBodyRule).toContain("background: var(--agent-chat-raised)");
    expect(css).toContain(".agent-chat__resize-handle");
    expect(css).toContain("cursor: ew-resize");
  });

  it("aligns user message containers to the right inside conversation locations", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const userMessageContainerRule = css.match(/\.agent-chat__message--user\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(userMessageContainerRule).toContain("justify-self: end");
  });

  it("keeps historical capability names smaller than the stage thread identity", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const compactHeadingRule = css.match(/\.agent-chat__compact-capability-heading\s+strong\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(css).toMatch(/\.agent-chat__activity:not\(\.is-compact\)\s*>\s*header\s+strong\s*\{/);
    expect(compactHeadingRule).toContain("font-size: 11px");
  });

  it("styles View on canvas as a white physical action button", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const canvasActionRule = css.match(/\.agent-chat\s+\.agent-chat__node-links--result\s*>\s*button\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(canvasActionRule).toContain("background: #fff");
    expect(canvasActionRule).toContain("color: black");
    expect(canvasActionRule).toContain("font-family: inherit");
    expect(canvasActionRule).toContain("padding: 0.35em 0.8em");
    expect(canvasActionRule).toContain("font-weight: 900");
    expect(canvasActionRule).toContain("font-size: 10px");
    expect(canvasActionRule).toContain("border: 1px solid black");
    expect(canvasActionRule).toContain("box-shadow: 0.18em 0.18em;");
    expect(canvasActionRule).toContain("cursor: pointer");
    expect(css).toMatch(/\.agent-chat\s+\.agent-chat__node-links--result\s*>\s*button:hover\s*\{[\s\S]*?transform: translate\(-0\.05em, -0\.05em\);[\s\S]*?box-shadow: 0\.24em 0\.24em;/m);
    expect(canvasActionRule).toContain("transition: none");
    expect(css).toMatch(/\.agent-chat\s+\.agent-chat__node-links--result\s*>\s*button:active:not\(:disabled\):not\(\[aria-disabled="true"\]\)\s*\{[\s\S]*?transform: translate\(0\.05em, 0\.05em\);[\s\S]*?box-shadow: 0\.1em 0\.1em;/m);
  });

  it("styles Stage Threads as quiet monochrome timeline sections", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const threadRule = css.match(/\.agent-chat__stage-thread\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(threadRule).toContain("border-top: 1px solid var(--agent-chat-border)");
    expect(threadRule).toContain("background: transparent");
    expect(css).not.toContain(".agent-chat__stage-thread-summary");
    expect(css).toContain("--agent-chat-selected: var(--surface-selected)");
    expect(css).toMatch(/\.agent-chat__stage-thread > header span\s*\{[^}]*color: var\(--agent-chat-secondary\)/s);
    expect(css).toMatch(/\.agent-chat__progress-groups span\s*\{[^}]*color: var\(--agent-chat-secondary\)/s);
  });

  it("keeps the full capability identity only on the Stage Thread header", () => {
    const panelPath = resolve(process.cwd(), "src/features/agent-canvas/chat/AgentCanvasChatPanel.tsx");
    const panelSource = readFileSync(panelPath, "utf8");

    expect(panelSource).toContain("...unit.planning");
    expect(panelSource).toContain("...unit.activities");
    expect(panelSource).toContain("...unit.proposals");
    expect(panelSource).toContain(".sort((left, right) => left.sequence - right.sequence)");
    expect(panelSource).toMatch(/<StageThread\s+\n?\s+unit=\{unit\}/);
  });

  it("uses one scrolling monochrome Decision Dock surface", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const currentInteractionRule = css.match(/\.agent-chat__current-interaction\s*\{([\s\S]*?)\n\}/m)?.[1];
    const currentInteractionDockRule = css.match(/\.agent-chat__current-interaction\s*>\s*\.agent-chat__decision-dock\s*\{([\s\S]*?)\n\}/m)?.[1];
    const optionsRule = css.match(/\.agent-chat__decision-dock-options\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(css).toContain(".agent-chat__decision-dock");
    expect(css).toContain(".agent-chat__decision-dock-body");
    expect(css).toContain(".agent-chat__decision-dock-footer");
    expect(css).toContain("max-height: min(50vh, 480px)");
    expect(css).toContain("overflow-y: auto");
    expect(css).toMatch(/\.agent-chat__proposal-option:not\(\.is-selected\)[\s\S]*-webkit-line-clamp: 2/);
    expect(css).toMatch(/\.agent-chat__proposal-option\.is-selected[\s\S]*border-color: var\(--agent-chat-primary\)/);
    expect(css).toMatch(/\.agent-chat__decision-dock-header strong\s*\{[^}]*font-size: 13px/s);
    expect(css).toMatch(/\.agent-chat__decision-dock-header p\s*\{[^}]*font-size: 12px/s);
    expect(css).toMatch(/\.agent-chat__proposal-option-copy strong\s*\{[^}]*font-size: 13px/s);
    expect(css).toMatch(/\.agent-chat__proposal-option-copy > span\s*\{[^}]*font-size: 12px/s);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*\.agent-chat__decision-dock/);
    expect(css).not.toContain(".agent-chat__guided-proposal-intro");
    expect(css).not.toContain("#e6a34a");
    expect(css).not.toContain("#77c9c2");
    expect(currentInteractionRule).toContain("overflow: hidden");
    expect(currentInteractionRule).not.toContain("overflow-y: auto");
    expect(currentInteractionRule).toContain("display: flex");
    expect(css).toMatch(/\.agent-chat__timeline-shell\s*\{[\s\S]*display: flex;[\s\S]*flex-direction: column;/m);
    expect(css).toMatch(/\.agent-chat__timeline\s*\{[\s\S]*flex: 1 1 auto;/m);
    expect(css).toMatch(/\.agent-chat__current-interaction--overlay\s*\{[\s\S]*position: relative;[\s\S]*flex: 0 0 auto;/m);
    const dockRule = css.match(/\.agent-chat__current-interaction--overlay\s*\{([\s\S]*?)\n\}/m)?.[1] ?? "";
    expect(dockRule).not.toContain("position: absolute");
    expect(dockRule).not.toContain("pointer-events");
    expect(currentInteractionDockRule).toContain("max-height: 100%");
    expect(currentInteractionDockRule).toContain("flex: 1 1 auto");
    expect(optionsRule).toContain("min-height: max-content");
  });

  it("keeps recovery and message context as bounded monochrome Shell regions", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const panelRule = css.match(/^\.agent-chat\s*\{([\s\S]*?)\n\}/m)?.[1];
    const timelineRule = css.match(/\.agent-chat__timeline\s*\{([\s\S]*?)\n\}/m)?.[1];
    const recoveryRule = css.match(/\.agent-chat__recovery\s*\{([\s\S]*?)\n\}/m)?.[1];
    const trayRule = css.match(/\.agent-chat__context-tray\s*\{([\s\S]*?)\n\}/m)?.[1];
    const trayGroupsRule = css.match(/\.agent-chat__context-groups\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(panelRule).toContain("display: flex");
    expect(panelRule).toContain("flex-direction: column");
    expect(panelRule).toContain("overflow: hidden");
    expect(timelineRule).toContain("overflow-y: auto");
    expect(recoveryRule).toContain("background: var(--agent-chat-raised)");
    expect(recoveryRule).not.toMatch(/gradient|#[0-9a-f]{3,8}/i);
    expect(trayRule).toContain("max-height: min(28vh, 230px)");
    expect(trayRule).toContain("overflow: hidden");
    expect(trayGroupsRule).toContain("overflow-y: auto");
    expect(css).toMatch(/@media \(max-width: 350px\)[\s\S]*\.agent-chat__mention-menu[\s\S]*grid-template-columns: minmax\(0, 1fr\)/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*\.agent-chat__recovery[\s\S]*\.agent-chat__context-tray/);
  });

  it("gives natural messages readable markdown without truncation", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    expect(css).not.toContain(".agent-chat__message-body.is-collapsed");
    expect(css).toMatch(/\.agent-chat__markdown pre\s*\{[^}]*overflow-x: auto/s);
    expect(css).toMatch(/\.agent-chat__markdown a\s*\{[^}]*overflow-wrap: anywhere/s);
    expect(css).toMatch(/\.agent-chat__message-meta time\s*\{[^}]*opacity: 0/s);
  });

  it("uses the brand blue for Style selection while preserving semantic states", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const errorRule = css.match(/\.agent-chat__error\s*\{([\s\S]*?)\n\}/m)?.[1];
    const noticeRule = css.match(/\.agent-chat__notice\s*\{([\s\S]*?)\n\}/m)?.[1];
    const selectedStyleRule = css.match(/\.agent-chat__style-menu \.agent-chat__style-option\.is-selected\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(errorRule).toContain("border-color: var(--agent-chat-strong-line)");
    expect(errorRule).toContain("color: var(--agent-chat-primary)");
    expect(noticeRule).toContain("color: var(--agent-chat-secondary)");
    expect(selectedStyleRule).toContain("border-color: var(--brand)");
    expect(css).not.toContain("#e6a34a");
    expect(css).not.toContain("#77c9c2");
  });

  it("disables chat presentation motion when reduced motion is requested", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const reducedMotion = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*)\}\s*$/m)?.[1];

    expect(reducedMotion).toContain(".agent-chat__message");
    expect(reducedMotion).toContain(".agent-chat__activity");
    expect(reducedMotion).toContain("animation: none !important");
  });

  it("keeps the fixed header without a divider above the scrolling timeline", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const headerRule = css.match(/\.agent-chat__header\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(headerRule).toContain("border-bottom: 0");
  });

  it("does not include the retired React Flow Mini Map chrome", () => {
    const pagePath = resolve(process.cwd(), "src/features/agent-canvas/AgentCanvasPageSurface.tsx");
    const pageSource = readFileSync(pagePath, "utf8");
    const canvasCssPath = resolve(process.cwd(), "src/features/agent-canvas/agent-canvas-page.css");
    const canvasCss = readFileSync(canvasCssPath, "utf8");

    expect(pageSource).not.toMatch(/\bMiniMap\b/);
    expect(canvasCss).not.toContain(".react-flow__minimap");
  });

  it("uses a legible AdCraft Bot icon in the collapsed trigger", () => {
    const cssPath = resolve(process.cwd(), "src/features/agent-canvas/chat/agent-canvas-chat.css");
    const css = readFileSync(cssPath, "utf8");
    const triggerRule = css.match(/\.agent-chat__collapsed-trigger\s*\{([\s\S]*?)\n\}/m)?.[1];
    const iconRule = css.match(/\.agent-chat__collapsed-trigger img\s*\{([\s\S]*?)\n\}/m)?.[1];

    expect(triggerRule).toContain("height: 42px");
    expect(iconRule).toContain("width: 28px");
    expect(iconRule).toContain("height: 28px");
  });

  it("collapses to an AdCraft Bot trigger without discarding the message draft", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      workflow_id: "workflow-1",
      conversation_id: null,
      items: [],
      next_cursor: 0,
    }), { headers: { "Content-Type": "application/json" } })));
    const workflow: AgentCanvasWorkflowV2 = {
      workflow_id: "workflow-1",
      project_id: "project-1",
      workflow_schema_version: 2,
      canvas_model: "agent_canvas_v1",
      revision: 1,
      layout_revision: 1,
      nodes: [],
      bindings: [],
      assets: [],
    };
    const { container } = render(
      <AgentCanvasChatPanel
        workflow={workflow}
        chatRevision={0}
        chatEvents={[]}
        onFocusNode={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByRole("textbox", { name: "Message AdCraft Video Agent" }), {
      target: { value: "Keep this draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Collapse AdCraft Bot panel" }));

    expect(screen.queryByRole("complementary", { name: "AdCraft Video Agent" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open AdCraft Bot panel" })).toBeTruthy();
    expect(container.querySelector('img[src="/imgs/logo.png"]')).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open AdCraft Bot panel" }));

    expect(screen.getByRole("complementary", { name: "AdCraft Video Agent" })).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Message AdCraft Video Agent" }) as HTMLTextAreaElement).value).toBe("Keep this draft");
  });
});

describe("AgentCanvasChatPanel decision dock overlay", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  function openInteraction(): GuidedInteractionV1 {
    return {
      interaction_id: "interaction-overlay-1",
      workflow_id: roleMotionWorkflow.workflow_id,
      session_id: "session-1",
      checkpoint_id: "checkpoint-1",
      kind: "clarification_questionnaire",
      status: "open",
      response_locale: "en-US",
      expected_session_revision: 3,
      revision: 2,
      title: "Choose duration",
      context: "Choose one duration.",
      content: {
        content_kind: "questionnaire",
        questions: [{
          question_id: "production_duration_seconds",
          prompt: "How long should the ad be?",
          input_kind: "single_select",
          options: [{
            option_id: "duration-15",
            title: "15 seconds",
            summary: "Short and punchy.",
            difference_tags: [],
            recommended: true,
            reference_preview: [],
          }],
          allow_custom: false,
          allow_skip: false,
          required: true,
        }],
      },
      allowed_actions: ["answer"],
      submit_path: "/guided-interactions/interaction-overlay-1/submit",
      created_at: "2026-09-15T00:00:00Z",
      updated_at: "2026-09-15T00:00:00Z",
    };
  }

  function renderPanelWithInteraction(interaction: GuidedInteractionV1 = openInteraction(), guidanceAwaiting: GuidanceAwaitingV1 | null = null) {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      workflow_id: roleMotionWorkflow.workflow_id,
      conversation_id: null,
      items: [],
      next_cursor: 0,
    }), { headers: { "Content-Type": "application/json" } })));
    const chat = mockChatResult();
    chat.state.guidedInteraction = interaction;
    panelMocks.useAgentCanvasChat.mockReturnValue({ ...chat, state: { ...chat.state, guidanceAwaiting } });
    const rendered = render(
      <AgentCanvasChatPanel
        workflow={roleMotionWorkflow}
        chatRevision={0}
        chatEvents={[]}
        onFocusNode={vi.fn()}
      />,
    );
    return { ...rendered, chat };
  }

  function directionInteraction(): GuidedInteractionV1 {
    return {
      ...openInteraction(), kind: "concept_choice", context: "Choose your direction",
      content: {
        content_kind: "concept_choice", proposal_id: null, stage: "world_view", stage_revision: 3,
        action_id: "action-world", occurrence_id: "world-1", capability_id: "world_setting",
        allow_custom: true, allow_exclusion: false,
        options: [{ option_id: "option-world", title: "Quiet world", summary: "A calm setting.",
          difference_tags: [], recommended: true, reference_preview: [] }],
      },
      allowed_actions: ["select", "custom"],
    };
  }

  function submitDirection() {
    fireEvent.click(screen.getByRole("radio", { name: /Quiet world/ }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm direction" }));
  }

  it.each(["loading", "sending", "agentWorking"] as const)(
    "waits for backend %s state before revealing a new choice card",
    (pendingState) => {
      const chat = mockChatResult();
      chat.state.guidedInteraction = directionInteraction();
      chat.state[pendingState] = true;
      panelMocks.useAgentCanvasChat.mockReturnValue(chat);
      const props = { workflow: roleMotionWorkflow, chatRevision: 0, chatEvents: [], onFocusNode: vi.fn() };
      const { rerender } = render(<AgentCanvasChatPanel {...props} />);

      expect(screen.queryByRole("radio", { name: /Quiet world/ })).toBeNull();
      expect(screen.queryByRole("button", { name: "Confirm direction" })).toBeNull();
      expect(screen.getAllByRole("status", { name: "World Setting Designer is working..." })).toHaveLength(1);
      expect(document.querySelector('.agent-chat__working-loader[data-variant="halo"]')).toBeTruthy();

      chat.state[pendingState] = false;
      rerender(<AgentCanvasChatPanel {...props} />);
      expect(screen.queryByRole("status", { name: "World Setting Designer is working..." })).toBeNull();
      fireEvent.click(screen.getByRole("radio", { name: /Quiet world/ }));
      expect((screen.getByRole("button", { name: "Confirm direction" }) as HTMLButtonElement).disabled).toBe(false);
    },
  );

  it("keeps waiting until the matching proposal detail needed for confirmation arrives", () => {
    const interaction = directionInteraction();
    if (interaction.content.content_kind !== "concept_choice") throw new Error("Expected concept choice");
    interaction.content.proposal_id = proposalCard.proposal.proposal_id;
    const chat = mockChatResult();
    chat.state.guidedInteraction = interaction;
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    const props = { workflow: roleMotionWorkflow, chatRevision: 0, chatEvents: [], onFocusNode: vi.fn() };
    const { rerender } = render(<AgentCanvasChatPanel {...props} />);
    expect(screen.queryByRole("radio", { name: /Quiet world/ })).toBeNull();
    expect(screen.getByRole("status", { name: "World Setting Designer is working..." })).toBeTruthy();

    chat.state.items = [proposalCard];
    rerender(<AgentCanvasChatPanel {...props} />);
    fireEvent.click(screen.getByRole("radio", { name: /Quiet world/ }));
    expect((screen.getByRole("button", { name: "Confirm direction" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByRole("status", { name: "World Setting Designer is working..." })).toBeNull();
  });

  it("waits for initial Brand state without discarding a choice during later refreshes", () => {
    const chat = mockChatResult();
    chat.state.guidedInteraction = directionInteraction();
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    const props = { workflow: roleMotionWorkflow, chatRevision: 0, chatEvents: [], onFocusNode: vi.fn() };
    const { rerender } = render(<AgentCanvasChatPanel {...props} brandContextReady={false} />);
    expect(screen.queryByRole("radio", { name: /Quiet world/ })).toBeNull();
    expect(screen.getByRole("status", { name: "World Setting Designer is working..." })).toBeTruthy();

    rerender(<AgentCanvasChatPanel {...props} brandContextReady />);
    const option = screen.getByRole("radio", { name: /Quiet world/ });
    fireEvent.click(option);
    chat.state.loading = true;
    chat.state.sending = true;
    rerender(<AgentCanvasChatPanel {...props} brandContextReady />);
    expect(screen.getByRole("radio", { name: /Quiet world/ })).toBe(option);
    expect(option.getAttribute("aria-checked")).toBe("true");
  });

  it("confirms a selected direction from the card instead of the empty composer", async () => {
    const { chat } = renderPanelWithInteraction(directionInteraction());
    chat.actions.submitGuidedInteraction.mockResolvedValue(true);
    const confirm = screen.getByRole("button", { name: "Confirm direction" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: /Quiet world/ }));
    expect(confirm.disabled).toBe(false);
    const send = screen.getByRole("button", { name: "Submit guided direction" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.click(send);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Message AdCraft Video Agent" }), { key: "Enter" });
    expect(chat.actions.submitGuidedInteraction).not.toHaveBeenCalled();
    fireEvent.click(confirm);
    await waitFor(() => expect(chat.actions.submitGuidedInteraction).toHaveBeenCalledWith(
      expect.anything(), expect.objectContaining({ action: "select", option_id: "option-world", custom_text: null }),
    ));
    expect(chat.actions.submit).not.toHaveBeenCalled();
  });

  it.each(["brand-memory", "campaign"] as const)("keeps the real Agent reply and confirmed %s summary without synthetic questions", async (stage) => {
    const title = stage === "brand-memory" ? "Brand details" : "Campaign details";
    const value = stage === "brand-memory" ? "Volt" : "Launch";
    const slotId = stage === "brand-memory" ? "brand_name" : "campaign_goal";
    const agentReply = "What are this cup's selling points, target audience, and advertising goals?";
    const chat = mockChatResult([{
      item_type: "message", message_kind: "conversation", message_id: "agent-reply",
      conversation_id: "conversation-1", speaker: "adcraft_video_agent", text: agentReply,
      linked_node_ids: [], script_node_id: null, proposal_id: null, capability_id: null,
      sequence: 2, created_at: "2026-10-23T02:59:00Z",
      metadata: { intent_mode: "guided_production", production_readiness: "not_ready" },
    }]);
    let accept!: (accepted: boolean) => void;
    chat.actions.submitGuidedInteraction.mockReturnValue(new Promise<boolean>(resolve => { accept = resolve; }));
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    let decisions: BrandDecisionPanelV1 = {
      project_id: "project-1", workflow_id: roleMotionWorkflow.workflow_id, mode: "brand",
      journey: { policy_version: "brand_professional_v1", stage, stage_revision: 2,
        treatment_substep: null, stage_status: "ready" },
      brand_name: "Volt", slot_values: [], open_card: null, hypotheses: [],
      selected_hypothesis_id: null, adspec: null, skill_stack: null, treatment_steps: [],
      treatment_locked: false,
    };
    const panel = () => <AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={1}
      chatEvents={[]} onFocusNode={vi.fn()} brandMode brandStage={decisions.journey.stage}
      brandDecisions={decisions} />;
    const view = render(panel());
    expect(screen.getByText(agentReply)).toBeTruthy();
    expect(screen.queryByRole("article", { name: "Agent question" })).toBeNull();
    chat.state.hasGuidedProductionIntent = true;
    view.rerender(panel());
    expect(screen.queryByRole("article", { name: "Agent question" })).toBeNull();
    expect(screen.queryByRole("article", { name: "Your selections" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Confirm entire form" })).toBeNull();

    chat.state.guidedInteraction = {
      ...openInteraction(), kind: "brand_form", title,
      allowed_actions: ["select", "custom"],
      content: {
        content_kind: "brand_form", form_id: `${stage}-form`, stage, revision: 2,
        response_locale: "en-US", context_digest: "a".repeat(64), title,
        instructions: "Confirm the details below.",
        rows: [{ question_id: slotId, slot_id: slotId, prompt: "Choose a value",
          options: [{ option_id: "choice", label: value, why: null },
            { option_id: "custom", label: "Custom", why: null }],
          custom_option_id: "custom", required: true }],
      },
    };
    view.rerender(panel());
    expect(screen.queryByRole("article", { name: "Agent question" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Collapse decision card" }));
    expect(screen.queryByRole("article", { name: "Agent question" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: new RegExp(title) }));
    fireEvent.click(screen.getByRole("radio", { name: new RegExp(value) }));
    expect(screen.queryByRole("article", { name: "Your selections" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Confirm entire form" }));
    await waitFor(() => expect(chat.actions.submitGuidedInteraction).toHaveBeenCalledOnce());
    const confirmation = screen.getByRole("status", { name: "Information confirmed" });
    expect(document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay")?.hidden).toBe(true);
    await act(async () => { accept(true); });
    expect(screen.getByRole("status", { name: "Information confirmed" })).toBe(confirmation);
    expect(screen.queryByRole("article", { name: "Agent question" })).toBeNull();
    expect(screen.queryByRole("article", { name: "Your selections" })).toBeNull();

    chat.state.guidedInteraction = null;
    decisions = { ...decisions, journey: { ...decisions.journey, stage: stage === "brand-memory" ? "campaign" : "hypothesis" },
      [stage === "brand-memory" ? "brand_profile" : "campaign_brief"]: { values: [{ slot_id: slotId, stage, value,
        kind: "fact", provenance: "user_confirmed", confirmed_at: "2026-10-23T03:00:00Z" }],
      inherited_values: [], unresolved_fields: [] } };
    view.rerender(panel());
    expect(screen.queryByRole("article", { name: "Agent question" })).toBeNull();
    expect(screen.getAllByText(agentReply)).toHaveLength(1);
    expect(screen.getByRole("article", { name: "Your selections" }).textContent).toContain(value);

    expect(screen.getByRole("status", { name: "Information confirmed" })).toBe(confirmation);
    fireEvent.click(screen.getByRole("button", { name: "Collapse AdCraft Bot panel" }));
    expect(screen.getByRole("status", { name: "Information confirmed" })).toBe(confirmation);
    view.unmount();
    render(panel());
    expect(screen.queryByRole("status", { name: "Information confirmed" })).toBeNull();
    expect(screen.queryByRole("article", { name: "Agent question" })).toBeNull();
    expect(screen.getAllByText(agentReply)).toHaveLength(1);
    expect(screen.getByRole("article", { name: "Your selections" }).textContent).toContain(value);
  });

  it.each(["rejected", "throws"])("rolls back immediate confirmation and restores the filled form when submission %s", async (outcome) => {
    const interaction: GuidedInteractionV1 = {
      ...openInteraction(), kind: "brand_form", allowed_actions: ["select", "custom"],
      content: { content_kind: "brand_form", form_id: "brand-form", stage: "brand-memory", revision: 2,
        response_locale: "en-US", context_digest: "a".repeat(64), title: "Brand details", instructions: "Choose the brand.",
        rows: [{ question_id: "brand", slot_id: "brand_name", prompt: "Brand name", required: true,
          custom_option_id: "custom", options: [{ option_id: "volt", label: "Volt", why: null }] }] },
    };
    const { chat } = renderPanelWithInteraction(interaction);
    let settle!: () => void;
    chat.actions.submitGuidedInteraction.mockReturnValue(new Promise<boolean>((resolve, reject) => {
      settle = () => outcome === "throws" ? reject(new Error("Submission failed")) : resolve(false);
    }));
    fireEvent.click(screen.getByRole("radio", { name: /Volt/ }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm entire form" }));
    expect(screen.getByRole("status", { name: "Information confirmed" })).toBeTruthy();
    expect(document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay")?.hidden).toBe(true);
    await act(async () => { settle(); });
    expect(chat.actions.submitGuidedInteraction).toHaveBeenCalledOnce();
    expect(screen.queryByRole("status", { name: "Information confirmed" })).toBeNull();
    expect(document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay")?.hidden).toBe(false);
    expect((screen.getByRole("radio", { name: /Volt/ }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("button", { name: "Confirm entire form" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it.each(["skill-stack", "skill-stack-early"] as const)("opens %s adjustment without submitting the old chat choice", (stage) => {
    const interaction = directionInteraction();
    if (interaction.content.content_kind !== "concept_choice") throw new Error("Expected concept choice");
    interaction.content = { ...interaction.content, capability_id: `brand_${stage}`, options: [{ ...interaction.content.options[0], option_id: "adjust", title: "调整 Skills" }] };
    const chat = mockChatResult();
    chat.state.guidedInteraction = interaction;
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    const onOpen = vi.fn();
    render(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()}
      brandMode brandStage={stage} onBrandSkillPickerOpen={onOpen} />);
    fireEvent.click(screen.getByRole("radio", { name: /调整 Skills/ }));
    expect(onOpen).toHaveBeenCalledOnce();
    expect(chat.actions.submitGuidedInteraction).not.toHaveBeenCalled();
  });

  it("submits early skip as an explicit choice without opening or confirming the picker", async () => {
    const interaction = directionInteraction();
    if (interaction.content.content_kind !== "concept_choice") throw new Error("Expected concept choice");
    interaction.content = { ...interaction.content, capability_id: "brand_skill-stack-early", options: [{ ...interaction.content.options[0], option_id: "skip", title: "Skip for now, choose later" }] };
    const chat = mockChatResult();
    chat.state.guidedInteraction = interaction;
    chat.actions.submitGuidedInteraction.mockResolvedValue(true);
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    const onOpen = vi.fn();
    render(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()}
      brandMode brandStage="skill-stack-early" onBrandSkillPickerOpen={onOpen} />);
    fireEvent.click(screen.getByRole("radio", { name: /Skip for now, choose later/ }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm direction" }));
    await waitFor(() => expect(chat.actions.submitGuidedInteraction).toHaveBeenCalledWith(interaction, expect.objectContaining({ action: "select", option_id: "skip" })));
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("immediately collapses a submitted choice, retains its card and prevents resubmission", async () => {
    const { chat, rerender } = renderPanelWithInteraction(directionInteraction());
    let accept!: (accepted: boolean) => void;
    chat.actions.submitGuidedInteraction.mockReturnValue(new Promise<boolean>(resolve => { accept = resolve; }));
    submitDirection();
    expect(chat.actions.submitGuidedInteraction).toHaveBeenCalledTimes(1);
    expect(chat.actions.submitGuidedInteraction).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ action: "select", option_id: "option-world" }));
    expect(screen.queryByRole("status", { name: "Guided interaction submitted" })).toBeNull();
    expect(screen.queryByText("Generating nodes…")).toBeNull();
    const overlay = document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay");
    expect(overlay?.hidden).toBe(true);
    expect(overlay?.querySelector('[role="radio"]')).toBeTruthy();
    expect(screen.queryByRole("radio", { name: /Quiet world/ })).toBeNull();
    const chip = screen.getByRole("button", { name: /Choose duration.*Working/ });
    fireEvent.click(chip);
    expect(overlay?.hidden).toBe(false);
    expect((screen.getByRole("radio", { name: /Quiet world/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Submitting" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Submitting" }));
    expect(chat.actions.submitGuidedInteraction).toHaveBeenCalledOnce();
    expect((screen.getByRole("button", { name: "Submit guided direction" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Collapse decision card" }));
    await act(async () => { accept(true); });
    expect(document.querySelector(".agent-chat__current-interaction--overlay")).toBe(overlay);
    expect(overlay?.hidden).toBe(true);
    chat.state.guidedInteraction = { ...directionInteraction(), revision: 3, status: "submitted" };
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    rerender(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={1} chatEvents={[]} onFocusNode={vi.fn()} />);
    expect(overlay?.hidden).toBe(true);
    expect(screen.getByRole("button", { name: /Choose duration.*Working/ })).toBeTruthy();
    chat.state.guidedInteraction = { ...openInteraction(), interaction_id: "next-interaction" };
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    rerender(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={1} chatEvents={[]} onFocusNode={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Collapse decision card" })).toBeTruthy();
  });

  it.each(["composer", "card"])("submits a custom Brand direction from the %s and opens the refreshed options", async (source) => {
    const interaction = directionInteraction();
    if (interaction.content.content_kind !== "concept_choice") throw new Error("Expected concept choice");
    interaction.content = { ...interaction.content, capability_id: "brand_hypothesis" };
    const { chat, rerender } = renderPanelWithInteraction(interaction);
    let accept!: (accepted: boolean) => void;
    chat.actions.submitGuidedInteraction.mockReturnValue(new Promise<boolean>(resolve => { accept = resolve; }));
    if (source === "card") fireEvent.click(screen.getByRole("radio", { name: /Other \(custom\)/ }));
    fireEvent.change(screen.getByRole("textbox", { name: source === "card" ? "Custom content" : "Message AdCraft Video Agent" }), {
      target: { value: "Give me more directions" },
    });
    fireEvent.click(screen.getByRole("button", { name: source === "card" ? "Confirm direction" : "Submit guided direction" }));
    expect(document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay")?.hidden).toBe(true);
    expect(chat.actions.submitGuidedInteraction).toHaveBeenCalledWith(interaction, expect.objectContaining({ action: "custom" }));
    expect((screen.getByRole("textbox", { name: "Message AdCraft Video Agent" }) as HTMLTextAreaElement).value).toBe("");

    chat.state.guidedInteraction = { ...interaction, revision: interaction.revision + 1 };
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    rerender(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={1} chatEvents={[]} onFocusNode={vi.fn()} />);
    expect(document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay")?.hidden).toBe(false);
    fireEvent.click(screen.getByRole("radio", { name: /Quiet world/ }));
    await act(async () => { accept(true); });
    expect(screen.getByRole("radio", { name: /Quiet world/ }).getAttribute("aria-checked")).toBe("true");
  });

  it.each([true, false])("clears custom direction text immediately and settles with accepted=%s", async (accepted) => {
    const { chat } = renderPanelWithInteraction(directionInteraction());
    let accept!: (accepted: boolean) => void;
    chat.actions.submitGuidedInteraction.mockReturnValue(new Promise<boolean>(resolve => { accept = resolve; }));
    const composer = screen.getByRole("textbox", { name: "Message AdCraft Video Agent" }) as HTMLTextAreaElement;
    const draft = "  Use a sunny world instead  ";
    fireEvent.change(composer, { target: { value: draft } });
    fireEvent.click(screen.getByRole("button", { name: "Submit guided direction" }));
    expect(chat.actions.submitGuidedInteraction).toHaveBeenCalledOnce();
    expect(composer.value).toBe("");
    await act(async () => { accept(accepted); });
    expect(composer.value).toBe(accepted ? "" : draft);
  });

  it.each(["rejected", "throws"])("restores the original choices after submission %s", async outcome => {
    const { chat } = renderPanelWithInteraction(directionInteraction());
    if (outcome === "throws") chat.actions.submitGuidedInteraction.mockRejectedValue(new Error("Submission failed"));
    else chat.actions.submitGuidedInteraction.mockResolvedValue(false);
    submitDirection();
    await waitFor(() => expect(screen.getByRole("radio", { name: /Quiet world/ })).toBeTruthy());
    expect(screen.getByRole("radio", { name: /Quiet world/ }).getAttribute("aria-checked")).toBe("true");
    expect((screen.getByRole("button", { name: "Confirm direction" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByRole("button", { name: "Collapse decision card" })).toBeTruthy();
    expect(screen.queryByText("Generating nodes…")).toBeNull();
  });

  it("restores the interaction when the submitted materialization explicitly fails", async () => {
    const interaction = directionInteraction();
    const { chat, rerender } = renderPanelWithInteraction(interaction);
    chat.actions.submitGuidedInteraction.mockResolvedValue(true);
    submitDirection();
    await act(async () => {});
    expect(document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay")?.hidden).toBe(true);
    const event: CanvasRuntimeEventV2 = {
      seq: 1, workflow_id: roleMotionWorkflow.workflow_id, event_type: "proposal_materialization_failed",
      project_id: null, execution_id: null, node_id: null, asset_id: null, binding_id: null,
      conversation_id: null, turn_id: null, action_id: interaction.interaction_id, trace_id: null,
      span_id: null, created_at: "2026-09-15T00:00:01Z", payload: null,
    };
    rerender(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={1} chatEvents={[event]} onFocusNode={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("radio", { name: /Quiet world/ })).toBeTruthy());
  });

  it("renders open interactions as a docked bottom region that reserves timeline space", () => {
    renderPanelWithInteraction();

    const shell = document.querySelector(".agent-chat__timeline-shell");
    const overlay = shell?.querySelector(":scope > .agent-chat__current-interaction--overlay");
    expect(overlay).not.toBeNull();
    expect(overlay?.querySelector(".agent-chat__decision-dock")).not.toBeNull();
    expect(overlay?.previousElementSibling?.classList.contains("agent-chat__timeline")).toBe(true);
    expect(screen.getByRole("button", { name: "Collapse decision card" })).toBeTruthy();
  });

  it("omits the top production notice while keeping the Product source interaction", () => {
    const interaction: GuidedInteractionV1 = {
      ...openInteraction(), kind: "product_source", title: "Product image source",
      content: {
        content_kind: "product_source", input_kind: "main", question_id: "product_main_source",
        prompt: "Provide one Product Main image.", expected_guidance_revision: 3,
        min_asset_count: 1, max_asset_count: 1,
      },
      allowed_actions: ["select_source"],
    };
    renderPanelWithInteraction(interaction, {
      awaiting_id: "awaiting-product", workflow_id: roleMotionWorkflow.workflow_id,
      session_id: "session-1", checkpoint_id: "checkpoint-1", kind: "product_source",
      requires_user_action: true, resume_policy: "submit_interaction",
      interaction_id: interaction.interaction_id, node_ids: [], stage: "product",
      stage_revision: 1, created_at: "2026-09-15T00:00:00Z",
    });
    expect(screen.queryByRole("status", { name: "Current production step" })).toBeNull();
    expect(screen.queryByText("A product source is needed")).toBeNull();
    expect(screen.queryByText("Add or choose a product source to continue")).toBeNull();
    expect(screen.getByText("Product image source")).toBeTruthy();
    expect(screen.getByText("Provide one Product Main image.")).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Use uploaded Product source" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Generate Product source" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Collapse decision card" })).toBeTruthy();
    expect(document.querySelector(".agent-chat__header")?.nextElementSibling?.className).toBe("agent-chat__timeline-shell");
  });

  it("keeps the pending brand question in an Agent bubble after collapsing its choice card", () => {
    const interaction = directionInteraction();
    interaction.title = "这支球鞋广告想传达怎样的创意方向？";
    interaction.context = "请先选择一个方案。";
    if (interaction.content.content_kind !== "concept_choice") throw new Error("Expected concept choice");
    interaction.content = { ...interaction.content, capability_id: "brand_hypothesis", stage: "intake" };
    const { chat } = renderPanelWithInteraction(interaction);
    expect(screen.getByRole("article", { name: "Agent question" }).textContent).toContain(interaction.title);
    fireEvent.click(screen.getByRole("button", { name: "Collapse decision card" }));
    expect(document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay")?.hidden).toBe(true);
    expect(chat.actions.submitGuidedInteraction).not.toHaveBeenCalled();
    expect(screen.getByRole("article", { name: "Agent question" }).textContent).toContain(interaction.title);
  });

  it.each(["ordinary", "hypothesis", "adspec", "treatment", "creative-route"])("retains answered %s Agent questions through confirmation, reload, rollback and the next question", (stage) => {
    const interaction = directionInteraction();
    if (stage !== "ordinary") interaction.interaction_id = `interaction_workflow_brand_${stage}_4_choice`;
    const { chat, rerender } = renderPanelWithInteraction(interaction);
    const answer = {
      bubble_id: "optimistic-answer", interaction_id: interaction.interaction_id,
      question_id: "action-world", label: interaction.title, value: "Quiet world", sequence: 1,
    };
    const refresh = (current: GuidedInteractionV1 | null, answers: typeof answer[]) => {
      panelMocks.useAgentCanvasChat.mockReturnValue({ ...chat, state: {
        ...chat.state, guidedInteraction: current, guidedAnswerBubbles: answers,
      } });
      rerender(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={1} chatEvents={[]} onFocusNode={vi.fn()} />);
    };
    expect(screen.getAllByRole("article", { name: "Agent question" })).toHaveLength(1);
    refresh(interaction, [answer]);
    expect(screen.getAllByRole("article", { name: "Agent question" })).toHaveLength(1);
    expect(screen.getAllByRole("article", { name: "Your guided answer" })).toHaveLength(1);
    expect(screen.getByRole("article", { name: "Your guided answer" }).querySelector("details")?.open).toBe(false);
    expect(screen.getAllByRole("article", { name: "Agent question" })[0]!.textContent).toContain(interaction.title);
    refresh(null, [{ ...answer, bubble_id: "persisted-answer" }]);
    expect(screen.getAllByRole("article", { name: "Agent question" })).toHaveLength(1);
    expect(screen.getAllByRole("article", { name: "Your guided answer" })).toHaveLength(1);
    refresh(interaction, []);
    expect(screen.getAllByRole("article", { name: "Agent question" })).toHaveLength(1);
    expect(screen.queryByRole("article", { name: "Your guided answer" })).toBeNull();
    refresh({ ...interaction, interaction_id: "next", title: "Choose the next direction" }, [answer]);
    expect(screen.getAllByRole("article", { name: "Agent question" })).toHaveLength(2);
    expect(screen.getAllByRole("article", { name: "Agent question" })[1]!.textContent).toContain("Choose the next direction");
    expect(screen.getAllByRole("article", { name: "Agent question" })[0]!.textContent).toContain(interaction.title);
  });

  it.each(["skill-stack", "skill-stack-early"] as const)("retains the %s question beside its confirmed summary after reload", (stage) => {
    const interaction = directionInteraction();
    interaction.interaction_id = `interaction_workflow_brand_${stage}_4_choice`;
    interaction.title = "Choose a creative method and audiovisual style";
    const answer = {
      bubble_id: "skill-answer", interaction_id: interaction.interaction_id,
      question_id: "action-world", label: interaction.title, value: "Metaphor / Quiet", sequence: 5,
    };
    const decisions = normalizeBrandDecisionPanelV1({
      project_id: roleMotionWorkflow.project_id, workflow_id: roleMotionWorkflow.workflow_id,
      mode: "brand", brand_name: "Brand", journey: { stage: "treatment", stage_revision: 6, stage_status: "ready" },
      early_skills_confirmed: stage === "skill-stack-early",
      skill_stack: { entries: [
        { skill_id: "metaphor", version: "1.0.0", skill_kind: "creative_method", title: "Metaphor", selected: true },
        { skill_id: "quiet", version: "1.0.0", skill_kind: "audiovisual_style", title: "Quiet", selected: true },
      ] },
    });
    const chat = mockChatResult();
    panelMocks.useAgentCanvasChat.mockReturnValue({ ...chat, state: {
      ...chat.state, guidedInteraction: interaction, guidedAnswerBubbles: [answer],
    } });
    const panel = (confirmed = false) => <AgentCanvasChatPanel workflow={roleMotionWorkflow}
      chatRevision={1} chatEvents={[]} onFocusNode={vi.fn()} brandMode brandStage="treatment"
      brandDecisions={confirmed ? decisions : null} />;
    const view = render(panel());
    expect(screen.getAllByRole("article", { name: "Agent question" })).toHaveLength(1);
    expect(screen.getAllByRole("article", { name: "Your guided answer" })).toHaveLength(1);
    const expectExchange = () => {
      const question = screen.getByRole("article", { name: "Agent question" });
      expect(question.textContent).toContain(interaction.title);
      const receipt = screen.getByRole("article", { name: "Your selections" });
      expect(question.compareDocumentPosition(receipt) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(receipt.textContent).toContain("Metaphor");
      expect(receipt.textContent).toContain("Quiet");
      expect(receipt.querySelector("details")?.open).toBe(false);
      expect(screen.queryByRole("article", { name: "Your guided answer" })).toBeNull();
    };
    view.rerender(panel(true));
    expectExchange();
    panelMocks.useAgentCanvasChat.mockReturnValue({ ...chat, state: {
      ...chat.state, guidedAnswerBubbles: [{ ...answer, bubble_id: "persisted-skill-answer" }],
    } });
    view.unmount();
    const reloaded = render(panel(true));
    expectExchange();

    // Replacing the latest receipt with a summary must not erase earlier choices.
    const earlier = { ...answer, bubble_id: "earlier-skill-answer", sequence: 4,
      interaction_id: `interaction_workflow_brand_${stage}_3_choice`, label: "Which initial styles would you like?" };
    panelMocks.useAgentCanvasChat.mockReturnValue({ ...chat, state: {
      ...chat.state, guidedAnswerBubbles: [earlier, answer],
      guidedInteraction: { ...interaction, interaction_id: "next-question", title: "Choose the next direction" },
    } });
    reloaded.rerender(panel(true));
    expect(screen.getAllByRole("article", { name: "Agent question" }).map(question => question.textContent)).toEqual([
      expect.stringContaining(earlier.label), expect.stringContaining(answer.label), expect.stringContaining("Choose the next direction"),
    ]);
    expect(screen.getAllByRole("article", { name: "Your guided answer" })).toHaveLength(1);
    expect(screen.getAllByRole("article", { name: "Your selections" })).toHaveLength(1);
  });

  it("restores a production question from timeline history before detail loads, without duplicating it after selection", () => {
    const titles = [
      "《续命处方》分镜与场景设计：诊所悬疑喜剧",
      "诊所场景美术设计：冷光诊室+晨间工位",
      "《续命处方》场景执行方案：2场景45秒反转广告",
    ];
    const label = titles.join(" / ");
    const options = titles.map((title, index) => ({
      option_id: `option-${index + 1}`, title, public_summary: `方案 ${index + 1}`, key_decisions: [],
    }));
    const entry = {
      entry_id: "proposal-entry", workflow_id: roleMotionWorkflow.workflow_id,
      conversation_id: "conversation-1", sequence_no: 4, entry_type: "concept_proposal",
      speaker: "adcraft_video_agent", content: "Review 3 option(s).",
      metadata: { proposal_id: "proposal-1", options },
      command_plan: null, action_receipt: null, created_at: proposalCard.created_at,
    };
    const timeline = normalizeAgentCanvasChatTimelineV2({
      workflow_id: roleMotionWorkflow.workflow_id, conversation_id: "conversation-1",
      guidance_session: null, continuations: [], current_session_actions: [],
      items: [entry], next_cursor: 4,
      presentation_items: [{ ...entry, presentation_key: "proposal:proposal-1",
        presentation_revision: 1, source_entry_ids: [entry.entry_id],
        message_key: null, message_args: {}, response_locale: "zh-CN" }],
    });
    const pointer = timeline.presentationItems![0]!.item;
    expect(pointer).toEqual(timeline.items[0]);
    const interaction = directionInteraction();
    if (interaction.content.content_kind !== "concept_choice") throw new Error("Expected concept choice");
    interaction.title = label;
    interaction.content = { ...interaction.content, proposal_id: "proposal-1",
      capability_id: "scene_design", options: options.map(option => ({ ...option,
        summary: option.public_summary, difference_tags: [], recommended: false, reference_preview: [],
      })) };
    const answer = {
      bubble_id: "answer-scene", proposal_id: "proposal-1", interaction_id: interaction.interaction_id,
      question_id: "action-world", label, value: titles[0]!, sequence: 5,
    };
    const chat = mockChatResult([pointer]);
    panelMocks.useAgentCanvasChat.mockReturnValue({ ...chat, state: { ...chat.state, guidedInteraction: interaction } });
    const panel = () => <AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={1} chatEvents={[]} onFocusNode={vi.fn()} />;
    const view = render(panel());
    const expectQuestion = () => {
      const questions = screen.getAllByRole("article", { name: "Agent question" });
      expect(questions).toHaveLength(1);
      expect(questions[0]!.textContent).toContain(label);
      expect(questions[0]!.closest("details")).toBeNull();
    };
    expectQuestion();
    panelMocks.useAgentCanvasChat.mockReturnValue({ ...chat, state: {
      ...chat.state, guidedInteraction: interaction, guidedAnswerBubbles: [answer],
    } });
    view.rerender(panel());
    expectQuestion();
    expect(screen.getAllByRole("article", { name: "Your guided answer" })).toHaveLength(1);

    // A reload has neither the old interaction nor local answer state.
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    view.rerender(panel());
    expectQuestion();
    const applied: ChatProposalCardV2 = { ...proposalCard, proposal: {
      ...proposalCard.proposal, capability_id: "scene_design", proposal_kind: "scene", options,
      capability_display_name: "Scene Designer", availability: "applied",
      latest_application: { application_id: "application-scene", receipt_id: "receipt-scene",
        option_id: "option-1", action: "select_option", created_node_ids: [],
        queued_execution_ids: [], created_at: proposalCard.created_at },
    } };
    panelMocks.useAgentCanvasChat.mockReturnValue(mockChatResult([applied]));
    view.rerender(panel());
    expectQuestion();
    expect(screen.getByRole("article", { name: `Selected option: ${titles[0]}` })).toBeTruthy();
  });

  it("collapses the decision dock into an in-flow chip and re-expands it on demand", () => {
    renderPanelWithInteraction();

    fireEvent.click(screen.getByRole("button", { name: "Collapse decision card" }));

    expect(document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay")?.hidden).toBe(true);
    const chip = screen.getByRole("button", { name: /Choose duration/ });
    expect(chip.querySelector(".agent-chat__interaction-chip") ?? chip).toBeTruthy();
    expect(chip.parentElement?.classList.contains("agent-chat__timeline-shell")).toBe(true);

    fireEvent.click(chip);

    expect(document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay")?.hidden).toBe(false);
    expect(screen.getByRole("button", { name: "Collapse decision card" })).toBeTruthy();
  });

  it("auto-expands a new interaction even if the previous one was collapsed", () => {
    const { rerender } = renderPanelWithInteraction();
    fireEvent.click(screen.getByRole("button", { name: "Collapse decision card" }));
    expect(document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay")?.hidden).toBe(true);

    const chat = mockChatResult();
    chat.state.guidedInteraction = {
      ...openInteraction(),
      interaction_id: "interaction-overlay-2",
      title: "Pick a style",
    };
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);

    rerender(
      <AgentCanvasChatPanel
        workflow={roleMotionWorkflow}
        chatRevision={1}
        chatEvents={[]}
        onFocusNode={vi.fn()}
      />,
    );

    expect(document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay")?.hidden).toBe(false);
    expect(screen.getByRole("button", { name: "Collapse decision card" })).toBeTruthy();
  });
});

describe("brand treatment confirmation readiness", () => {
  afterEach(cleanup);

  it.each([false, true])("requires confirmed treatment steps even during recovery review (ready: %s)", brandTreatmentReady => {
    const chat = mockChatResult();
    panelMocks.useAgentCanvasChat.mockReturnValue({ ...chat, state: { ...chat.state,
      brandCardRecovery: { interactionId: "old", phase: "review", needsQuestion: false, error: null },
    } });
    render(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()}
      brandMode brandStage="treatment" brandTreatmentReady={brandTreatmentReady} />);
    expect(Boolean(screen.queryByRole("region", { name: "Treatment confirmation" }))).toBe(brandTreatmentReady);
    expect(Boolean(screen.queryByRole("button", { name: "Review treatment" }))).toBe(brandTreatmentReady);
  });

  it("opens confirmation for completed treatment without recovery", () => {
    render(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()}
      brandMode brandStage="treatment" brandTreatmentReady />);
    expect(screen.getByRole("button", { name: "Review treatment" })).toBeTruthy();
  });
});

describe("brand Skill sending outside the modal", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it.each([
    ["skill-stack", false], ["skill-stack", true],
    ["skill-stack-early", false], ["skill-stack-early", true],
  ] as const)("collapses the confirmed %s chat card while generation continues (manually closed: %s)", async (stage, manuallyClosed) => {
    const decisions = normalizeBrandDecisionPanelV1({
      project_id: roleMotionWorkflow.project_id, workflow_id: roleMotionWorkflow.workflow_id,
      mode: "brand", brand_name: "Brand",
      journey: { stage, stage_revision: 5, stage_status: "waiting_user" },
      open_card: { card_id: "skills-5", stage, stage_revision: 5, question: "Choose", options: [] },
      skill_stack: { entries: [
        { skill_id: "metaphor", version: "1.0.0", skill_kind: "creative_method", title: "Metaphor", selected: true },
        { skill_id: "quiet", version: "1.0.0", skill_kind: "audiovisual_style", title: "Quiet", selected: true },
      ] },
    });
    const confirmed = { ...decisions, journey: { ...decisions.journey, stage: "treatment" as const, stage_revision: 6 }, open_card: null };
    let accept!: (value: BrandDecisionPanelV1) => void;
    let generate!: (value: null) => void;
    vi.spyOn(agentCanvasApi, "brandCreativeMethodSkills").mockResolvedValue({ items: [{
      skill_id: "metaphor", version: "1.0.0", skill_kind: "creative_method", title: "Metaphor", summary: "A method",
    }] });
    vi.spyOn(agentCanvasApi, "listVideoSkills").mockResolvedValue({ catalog_version: "1", categories: [], next_cursor: null,
      items: [{ skill_id: "quiet", version: "1.0.0", title: "Quiet", summary: "A quiet style", category: "styles", tags: [], supported_use_cases: [], preview: null, display_order: 1 }] });
    vi.spyOn(agentCanvasApi, "brandSelectSkills").mockReturnValue(new Promise(resolve => { accept = resolve; }));
    vi.spyOn(agentCanvasApi, "brandNextQuestion").mockReturnValue(new Promise(resolve => { generate = resolve; }));
    vi.spyOn(agentCanvasApi, "brandDecisions").mockResolvedValue(confirmed);
    const chat = mockChatResult();
    const interaction: GuidedInteractionV1 = {
      interaction_id: "skills-interaction-5", workflow_id: decisions.workflow_id,
      session_id: "session-1", checkpoint_id: "checkpoint-1", kind: "concept_choice",
      status: "open", response_locale: "en-US", expected_session_revision: 5, revision: 5,
      title: "Choose Skills", context: "Review the recommended Skills",
      content: {
        content_kind: "concept_choice", proposal_id: null, stage, stage_revision: 5,
        action_id: "skills-5", occurrence_id: null, capability_id: `brand_${stage}`,
        allow_custom: false, allow_exclusion: false,
        options: [{ option_id: "adjust", title: "Adjust Skills", summary: "Change the combination",
          difference_tags: [], recommended: false, reference_preview: [] }],
      },
      allowed_actions: ["select"], submit_path: "/guided-interactions/skills-interaction-5/submit",
      created_at: "2026-09-15T00:00:00Z", updated_at: "2026-09-15T00:00:00Z",
    };
    chat.state.guidedInteraction = interaction;
    panelMocks.useAgentCanvasChat.mockReturnValue(chat);
    const onUpdated = vi.fn();
    const onClose = vi.fn();
    const panel = (open: boolean, collapsed: boolean) => <AgentCanvasChatPanel workflow={roleMotionWorkflow}
      chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()} brandMode brandStage={stage}
      brandDecisions={decisions} brandSkillPickerOpen={open} collapsed={collapsed}
      onBrandSkillPickerClose={onClose} onBrandDecisionsUpdated={onUpdated} />;
    const view = render(panel(true, false));
    await screen.findByRole("radio", { name: "Quiet" });
    const overlay = document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay");
    expect(overlay?.hidden).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Save and send" }));
    expect(screen.queryByRole("status", { name: "Skills confirmed" })).toBeNull();
    if (manuallyClosed) {
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      expect(onClose).toHaveBeenCalledOnce();
      view.rerender(panel(false, true));
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(screen.queryByRole("status")).toBeNull();
      expect(screen.getByRole("button", { name: "Open AdCraft Bot panel" })).toBeTruthy();
    } else {
      expect(onClose).not.toHaveBeenCalled();
    }
    await act(async () => accept(confirmed));
    expect(onClose).toHaveBeenCalledOnce();
    view.rerender(panel(false, manuallyClosed));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("status", { name: "Skills confirmed" })).toBeTruthy();
    view.rerender(panel(false, false));
    const confirmedOverlay = document.querySelector<HTMLElement>(".agent-chat__current-interaction--overlay");
    if (!manuallyClosed) expect(confirmedOverlay).toBe(overlay);
    expect(confirmedOverlay?.hidden).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /Choose Skills.*Working/ }));
    expect((screen.getByRole("radio", { name: /Adjust Skills/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(chat.actions.submitGuidedInteraction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Collapse decision card" }));
    expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledOnce();
    expect(onUpdated).toHaveBeenCalledWith(confirmed);
    await act(async () => generate(null));
    expect(chat.actions.refresh).toHaveBeenCalledOnce();
    expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();
    view.rerender(panel(true, false));
    expect((await screen.findByRole("button", { name: "Proposal sent" })).hasAttribute("disabled")).toBe(true);
    expect(onClose).toHaveBeenCalledOnce();
    chat.state.guidedInteraction = { ...interaction, interaction_id: "next-direction", revision: 6,
      title: "Choose creative direction", content: { ...interaction.content,
        capability_id: "brand_hypothesis", stage: "hypothesis", stage_revision: 6, action_id: "direction-6" } };
    view.rerender(panel(false, false));
    expect(screen.getByRole("button", { name: "Collapse decision card" })).toBeTruthy();
  });
});

it.each(["request", "persisted"])("offers a Brand retry after %s continuation failure without resubmitting a choice", (source) => {
  const base = mockChatResult();
  const retry = vi.fn();
  const chat = {
    ...base,
    state: { ...base.state, brandNextQuestionIssue: source === "request" ? "Could not load the next step." : null },
    actions: { ...base.actions, retryBrandNextQuestion: retry },
  };
  panelMocks.useAgentCanvasChat.mockReturnValue(chat);
  const decisions = normalizeBrandDecisionPanelV1({
    project_id: roleMotionWorkflow.project_id, workflow_id: roleMotionWorkflow.workflow_id,
    mode: "brand", brand_name: "Brand",
    journey: { stage: "treatment", stage_revision: 15, stage_status: "ready" },
    continuation: source === "persisted" ? { status: "failed", attempt_count: 1, retryable: true, error_code: "agent_structured_output_invalid" } : null,
  });
  const view = render(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={0} chatEvents={[]} onFocusNode={vi.fn()}
    brandMode brandStage="treatment" brandDecisions={decisions} />);
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(retry).toHaveBeenCalledOnce();
  expect(chat.actions.submitGuidedInteraction).not.toHaveBeenCalled();
  view.rerender(<AgentCanvasChatPanel workflow={roleMotionWorkflow} chatRevision={1} chatEvents={[]} onFocusNode={vi.fn()}
    brandMode brandStage="treatment" brandDecisions={{ ...decisions, open_card: {
      card_id: "next-card", stage: "treatment", stage_revision: 16, question: "Choose camera", options: [],
    } }} />);
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
});
