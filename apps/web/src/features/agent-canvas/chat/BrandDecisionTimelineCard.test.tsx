import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BrandDecisionPanelV1 } from "../brand/brandDecisions.ts";
import { BrandDecisionTimelineCard } from "./BrandDecisionTimelineCard.tsx";

const decisions: BrandDecisionPanelV1 = {
  project_id: "project-1",
  workflow_id: "workflow-1",
  mode: "brand",
  brand_name: "Northstar",
  journey: {
    policy_version: "brand_professional_v1",
    stage: "production",
    treatment_substep: null,
    stage_revision: 8,
    stage_status: "ready",
  },
  slot_values: [
    {
      slot_id: "audience",
      stage: "brand-memory",
      value: "Curious urban runners",
      kind: "fact",
      provenance: "user_confirmed",
      confirmed_at: "2026-09-23T00:00:00Z",
    },
    {
      slot_id: "goal",
      stage: "campaign",
      value: "Build category recognition",
      kind: "constraint",
      provenance: "agent_recommended",
      confirmed_at: "2026-09-23T00:01:00Z",
    },
  ],
  open_card: null,
  hypotheses: [{
    candidate_id: "hypothesis-1",
    label: "A quiet starting line",
    insight: "Small rituals create recognition.",
    mechanism: "Identity cue",
    hypothesis: "A ritual earns attention.",
    product_role: "The trigger",
    hook_mechanism: "Micro moment",
    why: null,
  }],
  selected_hypothesis_id: "hypothesis-1",
  adspec: { items: [{ item_key: "duration", item_text: "15 seconds", state: "locked" }] },
  skill_stack: { entries: [{
    skill_kind: "creative_method",
    skill_id: "identity",
    title: "Identity Transformation",
    selected: true,
    version: "1.0",
    reason: null,
  }] },
  treatment_steps: [],
  treatment_locked: true,
};

describe("BrandDecisionTimelineCard", () => {
  it("renders confirmed brand context as readable timeline sections", () => {
    render(<BrandDecisionTimelineCard decisions={decisions} />);

    expect(screen.getByRole("article", { name: "Brand decisions" })).toBeTruthy();
    expect(screen.getByText("Brand Memory")).toBeTruthy();
    expect(screen.getByText("Curious urban runners")).toBeTruthy();
    expect(screen.getByText("Campaign")).toBeTruthy();
    expect(screen.getByText("Build category recognition")).toBeTruthy();
    expect(screen.getByText("A quiet starting line")).toBeTruthy();
    expect(screen.getByText("15 seconds")).toBeTruthy();
    expect(screen.getByText("Identity Transformation")).toBeTruthy();
    expect(screen.getAllByText("Locked").length).toBe(2);
  });
});
