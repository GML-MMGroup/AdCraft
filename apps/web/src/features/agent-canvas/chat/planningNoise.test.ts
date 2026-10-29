import { describe, expect, it } from "vitest";

import type { ChatActionReceiptCardV2, ChatMessageV2, ChatProposalCardV2, ConceptProposalV2 } from "../../../types-v2.ts";
import { proposalReply } from "./conversationExchange.ts";
import { localizePromptPreparation, reducePlanningNoise } from "./planningNoise.ts";

function planning(sequence: number, metadata: Record<string, unknown>, text = "Status"): ChatMessageV2 {
  return {
    item_type: "message",
    message_kind: "planning_progress",
    message_id: `planning-${sequence}`,
    conversation_id: "conversation-1",
    speaker: "adcraft_video_agent",
    text,
    linked_node_ids: [],
    script_node_id: null,
    proposal_id: null,
    capability_id: null,
    sequence,
    created_at: "2026-10-19T00:00:00Z",
    metadata,
  };
}

function prompt(sequence: number, nodeId: string, status: string): ChatMessageV2 {
  return planning(sequence, {
    type: "prompt_preparation",
    node_id: nodeId,
    node_title: `Title ${nodeId}`,
    status,
    error_code: status === "failed" ? "agent_provider_timeout" : "None",
  }, `${nodeId}: ${status}`);
}

function round(sequence: number): ChatMessageV2 {
  return planning(sequence, { envelope_id: `envelope-${sequence}`, operation: "next_action" }, "Planning the next creative action.");
}

function receipt(sequence: number, proposalId: string): ChatActionReceiptCardV2 {
  return {
    item_type: "action_receipt",
    sequence,
    created_at: "2026-10-19T00:00:00Z",
    action_receipt: { receipt_id: `receipt-${sequence}`, proposal_id: proposalId, status: "applied" },
  } as ChatActionReceiptCardV2;
}

function proposal(overrides: Partial<ConceptProposalV2> = {}): ChatProposalCardV2 {
  return {
    item_type: "proposal",
    sequence: 3,
    created_at: "2026-10-19T00:00:00Z",
    proposal: {
      proposal_id: "proposal-1",
      capability_display_name: "Product Designer",
      options: [
        { option_id: "option-a", title: "Layered light", public_summary: "", key_decisions: [] },
        { option_id: "option-b", title: "Unlock ritual", public_summary: "", key_decisions: [] },
      ],
      availability: "applied",
      latest_application: { option_id: "option-b" },
      materialization: null,
      ...overrides,
    } as ConceptProposalV2,
  };
}

describe("reducePlanningNoise", () => {
  it("keeps one prompt row per node at its first place with the latest attempt", () => {
    const items = [
      prompt(1, "node-video", "queued"),
      prompt(2, "node-video", "superseded"),
      prompt(5, "node-video", "queued"),
      prompt(7, "node-video", "ready"),
    ];

    expect(reducePlanningNoise(items, { agentWorking: false })).toEqual([
      { ...items[3], message_id: "planning-1", sequence: 1 },
    ]);
  });

  it("drops nodes whose latest attempt was superseded but keeps failures", () => {
    const items = [prompt(1, "node-old", "queued"), prompt(2, "node-old", "superseded"), prompt(3, "node-bad", "failed")];

    expect(reducePlanningNoise(items, { agentWorking: false }).map((item) => item.sequence)).toEqual([3]);
  });

  it("shows a planning round only while it is the newest row of a working Agent", () => {
    const items = [round(1), prompt(2, "node-a", "ready"), round(3)];

    expect(reducePlanningNoise(items, { agentWorking: true }).map((item) => item.sequence)).toEqual([2, 3]);
    expect(reducePlanningNoise(items, { agentWorking: false }).map((item) => item.sequence)).toEqual([2]);
  });

  it("drops a queued Draft materialization once its receipt arrives", () => {
    const materialization = planning(1, { materialization_id: "materialization-1", proposal_id: "proposal-1", status: "queued" });

    expect(reducePlanningNoise([materialization], { agentWorking: true })).toEqual([materialization]);
    expect(reducePlanningNoise([materialization, receipt(2, "proposal-1")], { agentWorking: false })
      .map((item) => item.item_type)).toEqual(["action_receipt"]);
  });

  it("renders prompt status from metadata instead of the English template", () => {
    const t = (key: string) => (key === "Prompt ready" ? "提示词已就绪" : key === "Prompt preparation failed" ? "提示词准备失败" : key);

    expect(localizePromptPreparation(prompt(1, "node-a", "ready"), t).text).toBe("Title node-a · 提示词已就绪");
    expect(localizePromptPreparation(prompt(1, "node-a", "failed"), t).text).toBe("Title node-a · 提示词准备失败 (agent_provider_timeout)");
    expect(localizePromptPreparation(round(2), t).text).toBe("Planning the next creative action.");
  });
});

describe("proposalReply", () => {
  it("answers with the chosen option title", () => {
    expect(proposalReply(proposal())).toEqual({ letter: "B", title: "Unlock ritual" });
  });

  it("uses the optimistic choice until the application lands", () => {
    const open = proposal({ availability: "open", latest_application: null });

    expect(proposalReply(open, "option-a")).toEqual({ letter: "A", title: "Layered light" });
    expect(proposalReply(open)).toBeNull();
  });
});
