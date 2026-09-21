import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { agentCanvasApi, V2ApiError } from "../../../api/agentCanvasApi.ts";
import { normalizeBrandDecisionPanelV1 } from "./brandDecisionNormalizers.ts";
import { BrandSkillPicker } from "./BrandSkillPicker.tsx";

const methods = ["metaphor", "ritual"].map((skill_id) => ({ skill_id, version: "1.0.0", skill_kind: "creative_method" as const, title: skill_id, summary: `${skill_id} summary` }));
const initial = normalizeBrandDecisionPanelV1({
  project_id: "p1", workflow_id: "w1", mode: "brand", brand_name: "Brand",
  journey: { stage: "skill-stack", stage_revision: 5, stage_status: "waiting_user" },
  open_card: { card_id: "card-5", stage: "skill-stack", stage_revision: 5, question: "Choose", options: [] },
  skill_stack: { entries: [
    { ...methods[0], selected: true, reason: "方法推荐理由" },
    ...["style-a", "style-b", "style-c"].map((skill_id, index) => ({ skill_id, version: "1.0.0", skill_kind: "audiovisual_style", title: skill_id, selected: index === 0, reason: `推荐 ${skill_id}` })),
  ] },
});
const saved = { ...initial, journey: { ...initial.journey, stage_revision: 6 }, open_card: { ...initial.open_card!, card_id: "card-6", stage_revision: 6 } };
const confirmed = { ...saved, journey: { ...saved.journey, stage: "treatment" as const }, open_card: null };

beforeEach(() => {
  vi.spyOn(agentCanvasApi, "brandCreativeMethodSkills").mockResolvedValue({ items: methods });
  vi.spyOn(agentCanvasApi, "brandDecisions").mockResolvedValue(saved);
  vi.spyOn(agentCanvasApi, "brandSelectSkills").mockResolvedValue(saved);
  vi.spyOn(agentCanvasApi, "brandNextQuestion").mockResolvedValue(null);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function setup() {
  const onClose = vi.fn();
  const onUpdated = vi.fn();
  const onConversationRefresh = vi.fn();
  render(<BrandSkillPicker decisions={initial} responseLocale="zh-CN" onClose={onClose} onUpdated={onUpdated} onConversationRefresh={onConversationRefresh} />);
  return { onClose, onUpdated, onConversationRefresh };
}

it("shows recommendations and cancels without writing", async () => {
  const { onClose } = setup();
  await screen.findByLabelText(/metaphor/);
  expect(screen.getByText("方法推荐理由")).toBeTruthy();
  expect(screen.getAllByRole("radio")).toHaveLength(3);
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(onClose).toHaveBeenCalledOnce();
  expect(agentCanvasApi.brandSelectSkills).not.toHaveBeenCalled();
});

it("saves multiple methods and one style, then confirms using the new card", async () => {
  const { onUpdated } = setup();
  fireEvent.click(await screen.findByLabelText(/ritual/));
  fireEvent.click(screen.getByLabelText(/style-b/));
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(saved));
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenLastCalledWith("w1", expect.objectContaining({ card_id: "card-5", confirm: false, creative_methods: methods.map(({ skill_id, version }) => ({ skill_id, version })), audiovisual_style: { skill_id: "style-b", version: "1.0.0" } }));
  expect(agentCanvasApi.brandNextQuestion).not.toHaveBeenCalled();
  vi.mocked(agentCanvasApi.brandSelectSkills).mockResolvedValue(confirmed);
  await waitFor(() => expect(screen.getByRole("button", { name: "确认并继续" }).hasAttribute("disabled")).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "确认并继续" }));
  await waitFor(() => expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledOnce());
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenLastCalledWith("w1", expect.objectContaining({ card_id: "card-6", expected_stage_revision: 6, confirm: true }));
});

it("blocks an empty method selection and duplicate submissions", async () => {
  setup();
  fireEvent.click(await screen.findByLabelText(/metaphor/));
  expect(screen.getByRole("button", { name: "保存" }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByLabelText(/ritual/));
  vi.mocked(agentCanvasApi.brandSelectSkills).mockReturnValue(new Promise(() => {}));
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  fireEvent.click(screen.getByRole("button", { name: "正在保存…" }));
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();
});

it("refreshes stale decisions without automatically resubmitting", async () => {
  setup();
  await screen.findByLabelText(/metaphor/);
  vi.mocked(agentCanvasApi.brandSelectSkills).mockRejectedValue(new V2ApiError({ status: 409, code: "brand_stage_action_mismatch", message: "Stale", details: {}, violations: [], suggestedActions: [], payload: null }));
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await screen.findByRole("alert");
  expect(agentCanvasApi.brandDecisions).toHaveBeenCalledWith("w1");
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();
  expect(agentCanvasApi.brandNextQuestion).not.toHaveBeenCalled();
});

it("retries only the next question after a committed confirmation", async () => {
  setup();
  await screen.findByLabelText(/metaphor/);
  vi.mocked(agentCanvasApi.brandSelectSkills).mockResolvedValue(confirmed);
  vi.mocked(agentCanvasApi.brandNextQuestion).mockRejectedValueOnce(new Error("Unavailable"));
  fireEvent.click(screen.getByRole("button", { name: "确认并继续" }));
  fireEvent.click(await screen.findByRole("button", { name: "重试下一步" }));
  await waitFor(() => expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledTimes(2));
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();
});

it("keeps stale submissions blocked when the recovery read fails", async () => {
  setup();
  await screen.findByLabelText(/metaphor/);
  vi.mocked(agentCanvasApi.brandSelectSkills).mockRejectedValue(new V2ApiError({ status: 409, code: "brand_stage_action_mismatch", message: "Stale", details: {}, violations: [], suggestedActions: [], payload: null }));
  vi.mocked(agentCanvasApi.brandDecisions).mockRejectedValueOnce(new Error("Offline"));
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "保存" }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "保存" }).hasAttribute("disabled")).toBe(false));
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();
});

it("refreshes the catalog after invalid selection without losing the editable draft", async () => {
  setup();
  fireEvent.click(await screen.findByLabelText(/ritual/));
  vi.mocked(agentCanvasApi.brandSelectSkills).mockRejectedValue(new V2ApiError({ status: 422, code: "brand_skill_selection_invalid", message: "Invalid", details: {}, violations: [], suggestedActions: [], payload: null }));
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await screen.findByRole("alert");
  expect(agentCanvasApi.brandCreativeMethodSkills).toHaveBeenCalledTimes(2);
  expect((screen.getByLabelText(/ritual/) as HTMLInputElement).checked).toBe(true);
  expect(agentCanvasApi.brandNextQuestion).not.toHaveBeenCalled();
});

it("does not auto-upgrade unversioned historical choices", async () => {
  const legacy = { ...initial, skill_stack: { entries: initial.skill_stack!.entries.map((entry) => ({ ...entry, version: null })) } };
  render(<BrandSkillPicker decisions={legacy} responseLocale="zh-CN" onClose={vi.fn()} onUpdated={vi.fn()} onConversationRefresh={vi.fn()} />);
  await screen.findByLabelText(/metaphor/);
  expect(screen.getByRole("button", { name: "确认并继续" }).hasAttribute("disabled")).toBe(true);
  expect((screen.getByLabelText(/metaphor/) as HTMLInputElement).checked).toBe(false);
});

it("keeps later stages read-only", async () => {
  render(<BrandSkillPicker decisions={confirmed} responseLocale="en" onClose={vi.fn()} onUpdated={vi.fn()} onConversationRefresh={vi.fn()} />);
  await screen.findByText("Skills cannot be edited at the current stage.");
  expect(screen.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true);
  expect(agentCanvasApi.brandSelectSkills).not.toHaveBeenCalled();
});
