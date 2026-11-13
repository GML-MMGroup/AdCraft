import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  it("edits the project name and submits the trimmed name to the project's save action", async () => {
    const onRenameProject = vi.fn().mockResolvedValue(true);
    const props = { decisions, refreshing: false, onRefresh: vi.fn(), projectName: "Untitled Project", onRenameProject };
    const view = render(<BrandDecisionPanel {...props} />);
    expect(screen.getByRole("heading", { name: "Untitled Project" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Rename project" }));
    const input = screen.getByRole("textbox", { name: "Project name" }) as HTMLInputElement;
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("Untitled Project");
    fireEvent.change(input, { target: { value: "  夏日新品广告  " } });
    fireEvent.submit(screen.getByRole("form", { name: "Rename project" }));
    await waitFor(() => expect(onRenameProject).toHaveBeenCalledWith("project-1", "夏日新品广告"));
    await waitFor(() => expect(screen.queryByRole("textbox", { name: "Project name" })).toBeNull());
    view.rerender(<BrandDecisionPanel {...props} projectName="夏日新品广告" />);
    expect(screen.getByRole("heading", { name: "夏日新品广告" })).toBeTruthy();
    expect(screen.queryByText("Untitled Project")).toBeNull();
  });

  it("cancels name changes without saving and prevents blank or duplicate submissions", () => {
    const onRenameProject = vi.fn();
    render(<BrandDecisionPanel decisions={decisions} refreshing={false} onRefresh={vi.fn()}
      projectName="Summer campaign" onRenameProject={onRenameProject} />);
    fireEvent.click(screen.getByRole("button", { name: "Rename project" }));
    const input = screen.getByRole("textbox", { name: "Project name" });
    fireEvent.change(input, { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Confirm rename" }).hasAttribute("disabled")).toBe(true);
    fireEvent.submit(screen.getByRole("form", { name: "Rename project" }));
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "Project name" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Rename project" }));
    expect((screen.getByRole("textbox", { name: "Project name" }) as HTMLInputElement).value).toBe("Summer campaign");
    fireEvent.submit(screen.getByRole("form", { name: "Rename project" }));
    expect(onRenameProject).not.toHaveBeenCalled();
  });

  it.each([false, new Error("Offline")])("keeps the name draft after a failed save so it can be retried (%s)", async (failure) => {
    const onRenameProject = failure instanceof Error
      ? vi.fn().mockRejectedValueOnce(failure).mockResolvedValue(true)
      : vi.fn().mockResolvedValueOnce(failure).mockResolvedValue(true);
    render(<BrandDecisionPanel decisions={decisions} refreshing={false} onRefresh={vi.fn()}
      projectName="Original title" onRenameProject={onRenameProject} />);
    fireEvent.click(screen.getByRole("button", { name: "Rename project" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Project name" }), { target: { value: "New title" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm rename" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Unable to rename"));
    expect((screen.getByRole("textbox", { name: "Project name" }) as HTMLInputElement).value).toBe("New title");
    fireEvent.click(screen.getByRole("button", { name: "Confirm rename" }));
    await waitFor(() => expect(screen.queryByRole("textbox", { name: "Project name" })).toBeNull());
    expect(onRenameProject).toHaveBeenCalledTimes(2);
  });

  it("keeps pending renames locked and ignores IME confirmation", async () => {
    let finish!: (saved: boolean) => void;
    const onRenameProject = vi.fn(() => new Promise<boolean>(resolve => { finish = resolve; }));
    render(<BrandDecisionPanel decisions={decisions} refreshing={false} onRefresh={vi.fn()}
      onRenameProject={onRenameProject} />);
    fireEvent.click(screen.getByRole("button", { name: "Rename project" }));
    const input = screen.getByRole("textbox", { name: "Project name" });
    fireEvent.change(input, { target: { value: "春季广告" } });
    expect(fireEvent.keyDown(input, { key: "Enter", isComposing: true, keyCode: 229 })).toBe(false);
    expect(onRenameProject).not.toHaveBeenCalled();
    fireEvent.submit(screen.getByRole("form", { name: "Rename project" }));
    fireEvent.submit(screen.getByRole("form", { name: "Rename project" }));
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onRenameProject).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Renaming project" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Cancel rename" }).hasAttribute("disabled")).toBe(true);
    await act(async () => finish(true));
    expect(screen.queryByRole("textbox", { name: "Project name" })).toBeNull();
  });

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
  it("places persisted brand thinking directly above an open option card", () => {
    const panel = normalizeBrandDecisionPanelV1({
      ...decisions,
      journey: { ...decisions.journey, stage: "brand-memory", stage_revision: 2 },
      open_card: {
        card_id: "card-memory", stage: "brand-memory", stage_revision: 2,
        target_slot_id: "brand_tone", question: "Choose the brand tone",
        options: [{ option_id: "tone-1", label: "Quiet confidence", why: null }],
      },
    });
    render(<BrandDecisionPanel decisions={panel} refreshing={false} onRefresh={vi.fn()} presentationStreams={[{
      stream_id: "stream-brand", status: "completed", generation_id: "brand-gen:workflow-1:2",
      reasoning_text: "I compared the tone options.", text: "", reasoning_started_at: 1_000,
      answer_started_at: 3_000, terminal_at_ms: 4_000, last_sequence_no: 3, stream_kind: "assistant",
      turn_id: null, node_id: null, authoritative_id: "card-memory", error_code: null,
      protocol_error: null, last_event_type: "committed", last_event: null,
    }]} />);
    const pending = screen.getByText("Choose the brand tone").closest(".brand-decision-pending")!;
    expect(pending.previousElementSibling?.classList.contains("agent-chat__thinking")).toBe(true);
    expect(screen.getByText("Thought for 3s")).toBeTruthy();
  });
});
