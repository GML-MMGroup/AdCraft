import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  ChatMessageV2,
  GuidedInteractionV1,
} from "../../../types-v2.ts";

const fixture = vi.hoisted(() => ({
  chat: null as unknown as ReturnType<typeof createChatFixture>,
  context: null as unknown as ReturnType<typeof createContextFixture>,
}));

vi.mock("./useAgentCanvasChat.ts", () => ({
  useAgentCanvasChat: () => fixture.chat,
}));

vi.mock("./useComposerContext.ts", () => ({
  useComposerContext: () => fixture.context,
}));

import { AgentCanvasChatPanel } from "./AgentCanvasChatPanel.tsx";

function message(id: string, text: string): ChatMessageV2 {
  return {
    item_type: "message",
    message_kind: "conversation",
    message_id: id,
    conversation_id: "conversation-1",
    speaker: "adcraft_video_agent",
    text,
    linked_node_ids: [],
    script_node_id: null,
    proposal_id: null,
    capability_id: null,
    sequence: Number(id.at(-1)),
    created_at: "2026-08-27T05:00:00Z",
  };
}

function interaction(): GuidedInteractionV1 {
  return {
    interaction_id: "interaction-1",
    workflow_id: "workflow-1",
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
          option_id: "duration-30",
          title: "30 seconds",
          summary: "Balanced runtime.",
          difference_tags: [],
          recommended: true,
          reference_preview: [],
        }],
        allow_custom: true,
        allow_skip: false,
        required: true,
      }],
    },
    allowed_actions: ["answer"],
    submit_path: "/submit",
    created_at: "2026-08-27T05:00:00Z",
    updated_at: "2026-08-27T05:00:00Z",
  };
}

function createChatFixture() {
  return {
    state: {
      items: [message("message-1", "First answer."), message("message-2", "Second answer.")],
      guidanceSession: null,
      guidedInteraction: null,
      guidanceAwaiting: null,
      currentSessionActions: [],
      continuations: [],
      turnsById: {},
      retryingSourceTurnIds: {},
      retryableFailedTurn: null,
      loading: false,
      sending: false,
      agentWorking: false,
      postReadyCheckpoint: null,
      agentWaitingForModel: false,
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
      submit: vi.fn().mockResolvedValue(true),
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

function createContextFixture() {
  return {
    view: {
      skill: { title: "Quiet Product Film", summary: "Restrained cinematography." },
      assets: [{
        assetId: "asset-1",
        displayName: "Hero image",
        mediaType: "image" as const,
        thumbnailUrl: "/preview/asset-1",
      }],
      nodes: [{ nodeId: "node-1", title: "Product Main", nodeType: "image" as const }],
      uploadState: "idle" as const,
    },
    selectedNodeIds: ["node-1"],
    selectedAssetIds: ["asset-1"],
    availableImageAssets: [{
      asset_id: "asset-1",
      display_name: "Hero image",
      media_type: "image",
    }],
    uploadIssue: null,
    actions: {
      toggleNode: vi.fn(),
      toggleAsset: vi.fn(),
      removeNode: vi.fn(),
      removeAsset: vi.fn(),
      upload: vi.fn(),
      clearMessageContext: vi.fn(),
      clearUploadIssue: vi.fn(),
    },
  };
}

const workflow = {
  workflow_id: "workflow-1",
  nodes: [{ node_id: "node-1", title: "Product Main", node_type: "image" }],
  assets: [],
  active_style_skill: { title: "Quiet Product Film" },
} as AgentCanvasWorkflowV2;

function renderPanel() {
  return render(
    <AgentCanvasChatPanel
      workflow={workflow}
      chatRevision={0}
      chatEvents={[]}
      onFocusNode={vi.fn()}
    />,
  );
}

describe("Agent Conversation Shell v2", () => {
  beforeEach(() => {
    fixture.chat = createChatFixture();
    fixture.context = createContextFixture();
  });

  afterEach(cleanup);

  it("orders Timeline, Decision Dock, Recovery, Context Tray, and Composer", () => {
    fixture.chat.state.guidedInteraction = interaction();
    fixture.chat.state.composerRecovery = {
      scope: "composer",
      title: "Response could not be submitted",
      message: "Your message is still here. Try sending it again.",
      technicalDetail: "send_failed",
      action: "retry",
    };
    renderPanel();

    const panel = document.querySelector(".agent-chat")!;
    const timeline = panel.querySelector(".agent-chat__timeline-shell")!;
    const dock = panel.querySelector(".agent-chat__current-interaction")!;
    const recovery = panel.querySelector(":scope > .agent-chat__recovery")!;
    const contextTray = panel.querySelector(":scope > .agent-chat__context-tray")!;
    const composer = panel.querySelector(":scope > .agent-chat__composer")!;
    const follows = (left: Element, right: Element) => Boolean(
      left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING,
    );

    expect(follows(timeline, dock)).toBe(true);
    expect(follows(dock, recovery)).toBe(true);
    expect(follows(recovery, contextTray)).toBe(true);
    expect(follows(contextTray, composer)).toBe(true);
  });

  it("preserves draft and context on failure, then clears only after acceptance", async () => {
    let finish!: (accepted: boolean) => void;
    fixture.chat.actions.submit.mockImplementation(() => new Promise<boolean>((resolve) => {
      finish = resolve;
    }));
    renderPanel();
    const textarea = screen.getByRole("textbox", { name: "Message AdCraft Video Agent" }) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Use these references." } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(textarea.value).toBe("Use these references.");
    expect(fixture.context.actions.clearMessageContext).not.toHaveBeenCalled();
    finish(false);
    await waitFor(() => expect(fixture.chat.actions.submit).toHaveBeenCalledOnce());
    expect(textarea.value).toBe("Use these references.");
    expect(screen.getByText("Skill · Quiet Product Film")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    finish(true);
    await waitFor(() => expect(textarea.value).toBe(""));
    expect(fixture.context.actions.clearMessageContext).toHaveBeenCalledOnce();
  });

  it("renders one Agent identity per run and keeps context out of composer chips", () => {
    renderPanel();

    expect(screen.getAllByText("AdCraft Video Agent")).toHaveLength(2);
    expect(document.querySelectorAll(".agent-chat__message-identity")).toHaveLength(1);
    expect(document.querySelector(".agent-chat__mentions")).toBeNull();
    expect(screen.getByRole("button", { name: "Mention node or image asset" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Upload context images" })).toBeTruthy();
  });

  it("keeps Timeline recovery inside Timeline ownership", () => {
    fixture.chat.state.timelineRecovery = {
      scope: "timeline",
      title: "Conversation could not be refreshed",
      message: "The last available conversation is still shown.",
      technicalDetail: "timeline_failed",
      action: "refresh",
    };
    renderPanel();

    const alert = screen.getByRole("alert");
    expect(alert.closest(".agent-chat__timeline")).toBeTruthy();
    expect(document.querySelector(":scope > .agent-chat__recovery")).toBeNull();
  });
});
