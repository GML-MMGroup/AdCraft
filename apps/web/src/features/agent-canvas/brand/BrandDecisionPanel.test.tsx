import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { normalizeBrandDecisionPanelV1 } from "./brandDecisionNormalizers.ts";
import { BrandDecisionPanel } from "./BrandDecisionPanel.tsx";

const decisions = normalizeBrandDecisionPanelV1({
  project_id: "project-1", workflow_id: "workflow-1", mode: "brand", brand_name: "Northstar",
  journey: { stage: "production", stage_revision: 8, stage_status: "ready" },
  slot_values: [
    { slot_id: "brand_audience", stage: "brand-memory", value: "Curious urban runners", provenance: "user_confirmed", kind: "fact" },
    { slot_id: "brand_tone", stage: "brand-memory", value: "Quiet confidence", provenance: "agent_recommended", kind: "preference" },
    { slot_id: "brand_product_identity", stage: "brand-memory", value: "Running shoes", provenance: "user_confirmed", kind: "fact" },
    { slot_id: "campaign_goal", stage: "campaign", value: "Build recognition", provenance: "user_confirmed", kind: "constraint" },
  ],
  hypotheses: ["selected", "other"].map(candidate_id => ({ candidate_id, label: `${candidate_id} direction`, insight: "A morning ritual", mechanism: "Identity cue", hypothesis: "Make everyday routines memorable", product_role: "Ritual trigger", hook_mechanism: "A pause", why: "Fits the brief" })),
  selected_hypothesis_id: "selected",
  skill_stack: { entries: [
    { skill_id: "method", skill_kind: "creative_method", title: "Identity", selected: true, reason: "Connects a daily ritual to the product" },
    { skill_id: "other", skill_kind: "creative_method", title: "Visual metaphor", selected: false, reason: "An alternative rationale" },
  ] },
  treatment_steps: [{ step_key: "hook", selected_label: "Opening ritual", detail: "legacy detail", confirmed_at: "2026-09-23", structured_detail: { sections: [{ key: "action", title: "Action sequence", text: "A runner ties their shoes.\nThey step outside." }] } }],
});
afterEach(cleanup);
function setup(panel = decisions) { const onRefresh = vi.fn(); const result = render(<BrandDecisionPanel decisions={panel} refreshing={false} onRefresh={onRefresh}/>); return { ...result, onRefresh }; }
function expand(name: string) { fireEvent.click(screen.getByRole("button", { name: new RegExp(name) })); }

describe("BrandDecisionPanel", () => {
  it("keeps a compact summary and exposes labeled facts when expanded", () => {
    setup(); const memory = screen.getByRole("button", { name: /Brand Memory/ });
    expect(memory.getAttribute("aria-expanded")).toBe("false"); expect(screen.getByText("Curious urban runners")).toBeTruthy(); expect(screen.getByText("+1 more")).toBeTruthy();
    fireEvent.click(memory); expect(memory.getAttribute("aria-expanded")).toBe("true"); expect(screen.getByText("Audience")).toBeTruthy(); expect(screen.getByText("Running shoes")).toBeTruthy(); expect(screen.getByText("Agent recommended")).toBeTruthy();
    fireEvent.click(memory); expect(memory.getAttribute("aria-expanded")).toBe("false");
  });
  it("preserves manual expansion on refresh and opens a newly current stage", () => {
    const { rerender } = setup(); expand("Brand Memory"); const next = { ...decisions, journey: { ...decisions.journey, stage: "campaign" as const } }; rerender(<BrandDecisionPanel decisions={next} refreshing={false} onRefresh={vi.fn()}/>);
    expect(screen.getByRole("button", { name: /Brand Memory/ }).getAttribute("aria-expanded")).toBe("true"); expect(screen.getByRole("button", { name: /Campaign/ }).getAttribute("aria-expanded")).toBe("true");
    expand("Campaign"); expect(screen.getByRole("button", { name: /Campaign/ }).getAttribute("aria-expanded")).toBe("false");
    rerender(<BrandDecisionPanel decisions={{ ...next, workflow_id: "workflow-2" }} refreshing={false} onRefresh={vi.fn()}/>); expect(screen.getByRole("button", { name: /Brand Memory/ }).getAttribute("aria-expanded")).toBe("false");
  });
  it("shows all selected hypothesis fields and keeps alternatives behind a disclosure", () => {
    setup(); expand("Hypothesis"); const selected = screen.getByText("Selected direction").closest("details")!; expect(selected.open).toBe(true); expect(within(selected).getByText("Ritual trigger")).toBeTruthy(); expect(within(selected).getByText("Make everyday routines memorable")).toBeTruthy(); expect(screen.getByText("Other directions (1)").closest("details")!.open).toBe(false);
  });
  it("retains full treatment text and skill reasons in native disclosures", () => {
    setup(); expand("Treatment"); expand("Skill Stack"); const hook = screen.getByText("Opening ritual").closest("details")!; expect(hook.open).toBe(false); fireEvent.click(within(hook).getByText("Opening ritual")); expect(hook.open).toBe(true); expect(within(hook).getByText(/A runner ties their shoes/).textContent).toBe("A runner ties their shoes.\nThey step outside."); expect(screen.getByText("Connects a daily ritual to the product")).toBeTruthy(); expect(screen.getByText("Other options (1)").closest("details")!.open).toBe(false);
  });
  it("keeps refresh explicit and disables it while reading", () => {
    const { onRefresh, rerender } = setup(); expect(onRefresh).not.toHaveBeenCalled(); fireEvent.click(screen.getByRole("button", { name: "Refresh" })); expect(onRefresh).toHaveBeenCalledOnce(); rerender(<BrandDecisionPanel decisions={decisions} refreshing onRefresh={onRefresh}/>); expect(screen.getByRole("button", { name: "Refreshing…" }).hasAttribute("disabled")).toBe(true);
  });
});
