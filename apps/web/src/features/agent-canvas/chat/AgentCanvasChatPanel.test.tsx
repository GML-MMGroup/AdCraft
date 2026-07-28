import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatProposalCardV2 } from "../../../types-v2.ts";
import { ProposalCard } from "./AgentCanvasChatPanel.tsx";

const card: ChatProposalCardV2 = {
  item_type: "proposal",
  proposal: {
    proposal_id: "proposal-1",
    workflow_id: "workflow-1",
    turn_id: "turn-1",
    specialist: "character_designer",
    status: "pending",
    options: [{
      option_id: "option-1",
      display_name: "Hero",
      summary_prompt: "A focused campaign hero",
      semantic_role: "character",
      proposed_node_type: "image",
      reference_node_ids: [],
      reference_image_asset_ids: [],
    }],
    workflow_revision: 1,
    selection_actor: null,
  },
  sequence: 4,
  created_at: "2026-07-28T00:00:00Z",
};

describe("ProposalCard", () => {
  afterEach(() => cleanup());

  it("requires an explicit Select step before choosing the next action", () => {
    const onSelect = vi.fn().mockResolvedValue(undefined);
    render(
      <ProposalCard
        card={card}
        pending={false}
        onSelect={onSelect}
        onRevise={vi.fn()}
        onSkip={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Hero/ }));
    expect(screen.getByRole("button", { name: "Select" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Generate now" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate now" }));

    expect(onSelect).toHaveBeenCalledWith("proposal-1", "option-1", "generate_now");
  });
});
