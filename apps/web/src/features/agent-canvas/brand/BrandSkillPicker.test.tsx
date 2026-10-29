import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  await waitFor(() => expect(screen.getByRole("button", { name: "保存并发送" }).hasAttribute("disabled")).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
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
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
  fireEvent.click(await screen.findByRole("button", { name: "重试下一步" }));
  await waitFor(() => expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledTimes(2));
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();
});

it("optimistically acknowledges sending and continues after the panel is closed", async () => {
  let confirm!: (value: typeof confirmed) => void;
  let generate!: (value: null) => void;
  let refresh!: () => void;
  vi.mocked(agentCanvasApi.brandSelectSkills).mockReturnValue(new Promise((resolve) => { confirm = resolve; }));
  vi.mocked(agentCanvasApi.brandNextQuestion).mockReturnValue(new Promise((resolve) => { generate = resolve; }));
  vi.mocked(agentCanvasApi.brandDecisions).mockResolvedValue(confirmed);
  const onClose = vi.fn();
  const onUpdated = vi.fn();
  const onConversationRefresh = vi.fn(() => new Promise<void>((resolve) => { refresh = resolve; }));
  const panel = (open: boolean) => <BrandSkillPicker open={open} decisions={initial} responseLocale="zh-CN"
    onClose={onClose} onUpdated={onUpdated} onConversationRefresh={onConversationRefresh} />;
  const view = render(panel(true));
  await screen.findByLabelText(/metaphor/);
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
  expect(screen.getByRole("status").textContent).toContain("方案已发送");
  fireEvent.click(screen.getByRole("button", { name: "方案已发送" }));
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();
  expect(agentCanvasApi.brandNextQuestion).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "关闭" }));
  expect(onClose).toHaveBeenCalledOnce();
  view.rerender(panel(false));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.body.style.overflow).not.toBe("hidden");
  expect(screen.getByRole("status").textContent).toContain("方案已发送");

  await act(async () => confirm(confirmed));
  expect(onUpdated).toHaveBeenCalledWith(confirmed);
  expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledOnce();
  await act(async () => generate(null));
  expect(onConversationRefresh).toHaveBeenCalledOnce();
  await act(async () => refresh());
  expect(onClose).toHaveBeenCalledOnce();
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();

  view.rerender(panel(true));
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(screen.getByRole("status").textContent).toContain("方案已发送");
  expect(screen.getByRole("button", { name: "方案已发送" }).hasAttribute("disabled")).toBe(true);
});

it("allows Escape while sending and keeps the panel open when background work completes", async () => {
  let confirm!: (value: typeof confirmed) => void;
  vi.mocked(agentCanvasApi.brandSelectSkills).mockReturnValue(new Promise((resolve) => { confirm = resolve; }));
  vi.mocked(agentCanvasApi.brandDecisions).mockResolvedValue(confirmed);
  const { onClose, onConversationRefresh } = setup();
  await screen.findByLabelText(/metaphor/);
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
  fireEvent.keyDown(window, { key: "Escape" });
  expect(onClose).toHaveBeenCalledOnce();
  await act(async () => confirm(confirmed));
  await waitFor(() => expect(onConversationRefresh).toHaveBeenCalledOnce());
  expect(onClose).toHaveBeenCalledOnce();
  expect(screen.getByRole("dialog")).toBeTruthy();
});

it("reports a failed optimistic send while closed and preserves the selection for retry", async () => {
  let reject!: (reason: Error) => void;
  vi.mocked(agentCanvasApi.brandSelectSkills).mockReturnValue(new Promise((_, fail) => { reject = fail; }));
  const onOpen = vi.fn();
  const panel = (open: boolean) => <BrandSkillPicker open={open} onOpen={onOpen} decisions={initial} responseLocale="zh-CN"
    onClose={vi.fn()} onUpdated={vi.fn()} onConversationRefresh={vi.fn()} />;
  const view = render(panel(true));
  fireEvent.click(await screen.findByLabelText(/ritual/));
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
  view.rerender(panel(false));
  await act(async () => reject(new Error("Offline")));
  expect(screen.getByRole("alert").textContent).toContain("保存失败");
  expect(screen.queryByText("方案已发送")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "查看方案" }));
  expect(onOpen).toHaveBeenCalledOnce();
  view.rerender(panel(true));
  expect((screen.getByLabelText(/ritual/) as HTMLInputElement).checked).toBe(true);
  expect(screen.getByRole("button", { name: "保存并发送" }).hasAttribute("disabled")).toBe(false);
  expect(agentCanvasApi.brandNextQuestion).not.toHaveBeenCalled();
});

it("starts the continuation even if the user leaves before confirmation returns", async () => {
  let confirm!: (value: typeof confirmed) => void;
  vi.mocked(agentCanvasApi.brandSelectSkills).mockReturnValue(new Promise(resolve => { confirm = resolve; }));
  const onUpdated = vi.fn();
  const onConversationRefresh = vi.fn();
  const view = render(<BrandSkillPicker decisions={initial} responseLocale="en-US" onClose={vi.fn()}
    onUpdated={onUpdated} onConversationRefresh={onConversationRefresh} />);
  await screen.findByLabelText(/metaphor/);
  fireEvent.click(screen.getByRole("button", { name: "Save and send" }));
  view.unmount();
  await act(async () => confirm(confirmed));
  expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledOnce();
  expect(onUpdated).not.toHaveBeenCalled();
  expect(onConversationRefresh).not.toHaveBeenCalled();
});

it("reports and retries a continuation failure from the closed-panel notice without resending", async () => {
  vi.mocked(agentCanvasApi.brandSelectSkills).mockResolvedValue(confirmed);
  vi.mocked(agentCanvasApi.brandNextQuestion).mockRejectedValueOnce(new Error("Offline"));
  vi.mocked(agentCanvasApi.brandDecisions).mockResolvedValue(confirmed);
  const onConversationRefresh = vi.fn();
  const panel = (open: boolean) => <BrandSkillPicker open={open} decisions={initial} responseLocale="zh-CN"
    onClose={vi.fn()} onUpdated={vi.fn()} onConversationRefresh={onConversationRefresh} />;
  const view = render(panel(true));
  await screen.findByLabelText(/metaphor/);
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
  view.rerender(panel(false));
  expect((await screen.findByRole("alert")).textContent).toContain("选择已保存");
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  await waitFor(() => expect(onConversationRefresh).toHaveBeenCalledOnce());
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();
  expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole("status").textContent).toContain("方案已发送");
});

it.each(["decisions", "conversation"])("retries only reads after generation succeeds and %s refresh fails", async (failedRead) => {
  vi.mocked(agentCanvasApi.brandSelectSkills).mockResolvedValue(confirmed);
  vi.mocked(agentCanvasApi.brandDecisions).mockResolvedValue(confirmed);
  const { onClose, onConversationRefresh } = setup();
  if (failedRead === "decisions") {
    vi.mocked(agentCanvasApi.brandDecisions).mockRejectedValueOnce(new Error("Offline"));
  } else {
    onConversationRefresh.mockRejectedValueOnce(new Error("Offline"));
  }
  await screen.findByLabelText(/metaphor/);
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
  await screen.findByRole("alert");
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "重试下一步" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
  await waitFor(() => expect(onConversationRefresh).toHaveBeenCalledTimes(failedRead === "conversation" ? 2 : 1));
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();
  expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledOnce();
  expect(agentCanvasApi.brandDecisions).toHaveBeenCalledTimes(2);
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
  expect(screen.getByRole("button", { name: "保存并发送" }).hasAttribute("disabled")).toBe(true);
  expect((screen.getByLabelText(/metaphor/) as HTMLInputElement).checked).toBe(false);
});

it("keeps later stages read-only", async () => {
  render(<BrandSkillPicker decisions={confirmed} responseLocale="en" onClose={vi.fn()} onUpdated={vi.fn()} onConversationRefresh={vi.fn()} />);
  await screen.findByText("Skills cannot be edited at the current stage.");
  expect(screen.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true);
  expect(agentCanvasApi.brandSelectSkills).not.toHaveBeenCalled();
});
