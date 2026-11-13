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
  vi.spyOn(agentCanvasApi, "listVideoSkills").mockResolvedValue({ catalog_version: "1", categories: [], next_cursor: null,
    items: ["style-a", "style-b", "style-c", "platform-default"].map((skill_id, index) => ({ skill_id, version: "1.0.0", title: skill_id,
      summary: "", category: "styles", tags: [], supported_use_cases: [], preview: null, display_order: index })) });
  vi.spyOn(agentCanvasApi, "brandDecisions").mockResolvedValue(saved);
  vi.spyOn(agentCanvasApi, "brandSelectSkills").mockResolvedValue(saved);
  vi.spyOn(agentCanvasApi, "brandNextQuestion").mockResolvedValue(null);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

async function findMethod(name: RegExp) {
  fireEvent.click(await screen.findByRole("tab", { name: /创意风格 Skill|Creative Skills/ }));
  return screen.findByLabelText(name);
}
function showStyles() { fireEvent.click(screen.getByRole("tab", { name: /视听风格 Skill|Audiovisual Skills/ })); }
function showMethods() { fireEvent.click(screen.getByRole("tab", { name: /创意风格 Skill|Creative Skills/ })); }

function setup() {
  const onClose = vi.fn();
  const onUpdated = vi.fn();
  const onConfirmed = vi.fn();
  const onConversationRefresh = vi.fn();
  render(<BrandSkillPicker decisions={initial} responseLocale="zh-CN" onClose={onClose} onUpdated={onUpdated} onConfirmed={onConfirmed} onConversationRefresh={onConversationRefresh} />);
  return { onClose, onUpdated, onConfirmed, onConversationRefresh };
}

it("announces confirmation after it is saved, before the next question finishes", async () => {
  let accept!: (value: typeof confirmed) => void;
  vi.mocked(agentCanvasApi.brandSelectSkills).mockReturnValue(new Promise(resolve => { accept = resolve; }));
  vi.mocked(agentCanvasApi.brandNextQuestion).mockReturnValue(new Promise(() => {}));
  const { onConfirmed } = setup();
  await findMethod(/metaphor/);
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
  expect(onConfirmed).not.toHaveBeenCalled();
  await act(async () => accept(confirmed));
  expect(onConfirmed).toHaveBeenCalledExactlyOnceWith(confirmed);
  expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledOnce();
});

it("keeps a failed confirmation editable without announcing success", async () => {
  vi.mocked(agentCanvasApi.brandSelectSkills).mockRejectedValue(new Error("Offline"));
  const { onConfirmed, onClose } = setup();
  await findMethod(/metaphor/);
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
  await screen.findByRole("alert");
  expect(onConfirmed).not.toHaveBeenCalled();
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "保存并发送" }).hasAttribute("disabled")).toBe(false);
});

it.each([
  ["brand-memory", "campaign", false],
  ["campaign", "skill-stack-early", false],
  ["skill-stack", "skill-stack", true],
] as const)("only announces Skill changes inside the reopened Skill panel (%s to %s)", async (from, to, shouldNotify) => {
  const props = { open: false, responseLocale: "en-US", onClose: vi.fn(), onUpdated: vi.fn(), onConversationRefresh: vi.fn() };
  const view = render(<BrandSkillPicker {...props} decisions={{ ...initial, journey: { ...initial.journey, stage: from } }} />);
  const next = { ...saved, journey: { ...saved.journey, stage: to } };
  view.rerender(<BrandSkillPicker {...props} decisions={next} />);
  expect(screen.queryByRole("status")).toBeNull();
  view.rerender(<BrandSkillPicker {...props} open decisions={next} />);
  await waitFor(() => expect(screen.queryByText("Loading Skills. Please wait…")).toBeNull());
  expect(Boolean(screen.queryByText("The selection changed. Review the latest combination."))).toBe(shouldNotify);
});

it("shows recommendations and cancels without writing", async () => {
  const { onClose } = setup();
  await findMethod(/metaphor/);
  expect(screen.getByLabelText(/metaphor/).closest("label")?.title).toContain("方法推荐理由");
  showStyles();
  expect(screen.getAllByRole("radio")).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(onClose).toHaveBeenCalledOnce();
  expect(agentCanvasApi.brandSelectSkills).not.toHaveBeenCalled();
});

it("saves multiple methods and one style, then confirms using the new card", async () => {
  const { onUpdated, onConfirmed } = setup();
  fireEvent.click(await findMethod(/ritual/));
  showStyles();
  fireEvent.click(screen.getByLabelText(/style-b/));
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(saved));
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenLastCalledWith("w1", expect.objectContaining({ card_id: "card-5", confirm: false, creative_methods: methods.map(({ skill_id, version }) => ({ skill_id, version })), audiovisual_style: { skill_id: "style-b", version: "1.0.0" } }));
  expect(agentCanvasApi.brandNextQuestion).not.toHaveBeenCalled();
  expect(onConfirmed).not.toHaveBeenCalled();
  vi.mocked(agentCanvasApi.brandSelectSkills).mockResolvedValue(confirmed);
  await waitFor(() => expect(screen.getByRole("button", { name: "保存并发送" }).hasAttribute("disabled")).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
  await waitFor(() => expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledOnce());
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenLastCalledWith("w1", expect.objectContaining({ card_id: "card-6", expected_stage_revision: 6, confirm: true }));
});

it("blocks an empty method selection and duplicate submissions", async () => {
  setup();
  fireEvent.click(await findMethod(/metaphor/));
  expect(screen.getByRole("button", { name: "保存" }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByLabelText(/ritual/));
  vi.mocked(agentCanvasApi.brandSelectSkills).mockReturnValue(new Promise(() => {}));
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  fireEvent.click(screen.getByRole("button", { name: "正在保存…" }));
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();
});

it("refreshes stale decisions without automatically resubmitting", async () => {
  setup();
  await findMethod(/metaphor/);
  vi.mocked(agentCanvasApi.brandSelectSkills).mockRejectedValue(new V2ApiError({ status: 409, code: "brand_stage_action_mismatch", message: "Stale", details: {}, violations: [], suggestedActions: [], payload: null }));
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await screen.findByRole("alert");
  expect(agentCanvasApi.brandDecisions).toHaveBeenCalledWith("w1");
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();
  expect(agentCanvasApi.brandNextQuestion).not.toHaveBeenCalled();
});

it("retries only the next question after a committed confirmation", async () => {
  const { onConfirmed } = setup();
  await findMethod(/metaphor/);
  vi.mocked(agentCanvasApi.brandSelectSkills).mockResolvedValue(confirmed);
  vi.mocked(agentCanvasApi.brandNextQuestion).mockRejectedValueOnce(new Error("Unavailable"));
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
  fireEvent.click(await screen.findByRole("button", { name: "重试下一步" }));
  await waitFor(() => expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledTimes(2));
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();
  expect(onConfirmed).toHaveBeenCalledExactlyOnceWith(confirmed);
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
  await findMethod(/metaphor/);
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
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.queryByRole("button", { name: "查看方案" })).toBeNull();
  expect(screen.queryByRole("button", { name: "收起提示" })).toBeNull();

  await act(async () => confirm(confirmed));
  expect(onUpdated).toHaveBeenCalledWith(confirmed);
  expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledOnce();
  await act(async () => generate(null));
  expect(onConversationRefresh).toHaveBeenCalledOnce();
  await act(async () => refresh());
  expect(onClose).toHaveBeenCalledOnce();
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledOnce();
  expect(screen.queryByRole("status")).toBeNull();

  view.rerender(panel(true));
  expect(screen.getByRole("dialog")).toBeTruthy();
  await findMethod(/metaphor/);
  expect(screen.getByRole("status").textContent).toContain("方案已发送");
  expect(screen.getByRole("button", { name: "方案已发送" }).hasAttribute("disabled")).toBe(true);
});

it("allows Escape while sending and keeps the panel open when background work completes", async () => {
  let confirm!: (value: typeof confirmed) => void;
  vi.mocked(agentCanvasApi.brandSelectSkills).mockReturnValue(new Promise((resolve) => { confirm = resolve; }));
  vi.mocked(agentCanvasApi.brandDecisions).mockResolvedValue(confirmed);
  const { onClose, onConversationRefresh } = setup();
  await findMethod(/metaphor/);
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
  fireEvent.keyDown(window, { key: "Escape" });
  expect(onClose).toHaveBeenCalledOnce();
  await act(async () => confirm(confirmed));
  await waitFor(() => expect(onConversationRefresh).toHaveBeenCalledOnce());
  expect(onClose).toHaveBeenCalledOnce();
  expect(screen.getByRole("dialog")).toBeTruthy();
});

it("preserves a failed send and the selection for retry when the panel is reopened", async () => {
  let reject!: (reason: Error) => void;
  vi.mocked(agentCanvasApi.brandSelectSkills).mockReturnValue(new Promise((_, fail) => { reject = fail; }));
  const panel = (open: boolean) => <BrandSkillPicker open={open} decisions={initial} responseLocale="zh-CN"
    onClose={vi.fn()} onUpdated={vi.fn()} onConversationRefresh={vi.fn()} />;
  const view = render(panel(true));
  fireEvent.click(await findMethod(/ritual/));
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
  view.rerender(panel(false));
  await act(async () => reject(new Error("Offline")));
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByText("方案已发送")).toBeNull();
  view.rerender(panel(true));
  expect(screen.getByRole("alert").textContent).toContain("保存失败");
  expect((await findMethod(/ritual/) as HTMLInputElement).checked).toBe(true);
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
  await findMethod(/metaphor/);
  fireEvent.click(screen.getByRole("button", { name: "Save and send" }));
  view.unmount();
  await act(async () => confirm(confirmed));
  expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledOnce();
  expect(onUpdated).not.toHaveBeenCalled();
  expect(onConversationRefresh).not.toHaveBeenCalled();
});

it("retries a background continuation failure after reopening the panel without resending", async () => {
  vi.mocked(agentCanvasApi.brandSelectSkills).mockResolvedValue(confirmed);
  vi.mocked(agentCanvasApi.brandNextQuestion).mockRejectedValueOnce(new Error("Offline"));
  vi.mocked(agentCanvasApi.brandDecisions).mockResolvedValue(confirmed);
  const onConversationRefresh = vi.fn();
  const panel = (open: boolean) => <BrandSkillPicker open={open} decisions={initial} responseLocale="zh-CN"
    onClose={vi.fn()} onUpdated={vi.fn()} onConversationRefresh={onConversationRefresh} />;
  const view = render(panel(true));
  await findMethod(/metaphor/);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
    view.rerender(panel(false));
  });
  expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledOnce();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByRole("status")).toBeNull();
  view.rerender(panel(true));
  expect((await screen.findByRole("alert")).textContent).toContain("选择已保存");
  fireEvent.click(screen.getByRole("button", { name: "重试下一步" }));
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
  await findMethod(/metaphor/);
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
  await findMethod(/metaphor/);
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
  fireEvent.click(await findMethod(/ritual/));
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
  await findMethod(/metaphor/);
  expect(screen.getByRole("button", { name: "保存并发送" }).hasAttribute("disabled")).toBe(true);
  expect((screen.getByLabelText(/metaphor/) as HTMLInputElement).checked).toBe(false);
});

it("keeps later stages read-only", async () => {
  render(<BrandSkillPicker decisions={confirmed} responseLocale="en" onClose={vi.fn()} onUpdated={vi.fn()} onConversationRefresh={vi.fn()} />);
  await screen.findByText("Skills cannot be edited at the current stage.");
  expect(screen.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true);
  expect(agentCanvasApi.brandSelectSkills).not.toHaveBeenCalled();
});

it("enables selection when the skill card arrives at the current stage revision", async () => {
  const waiting = { ...initial, open_card: null, skill_stack: null };
  const props = { responseLocale: "zh-CN", onClose: vi.fn(), onUpdated: vi.fn(), onConversationRefresh: vi.fn() };
  const view = render(<BrandSkillPicker {...props} decisions={waiting} open={false} />);

  view.rerender(<BrandSkillPicker {...props} decisions={initial} open />);

  const method = await findMethod(/ritual/);
  expect(method.matches(":disabled")).toBe(false);
  expect(screen.queryByText("当前阶段不可修改 Skills。")).toBeNull();
  expect((screen.getByLabelText(/metaphor/) as HTMLInputElement).checked).toBe(true);
  fireEvent.click(method);
  showStyles();
  fireEvent.click(screen.getByLabelText(/style-b/));
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledWith("w1", expect.objectContaining({
    card_id: "card-5", expected_stage_revision: 5, confirm: false,
    creative_methods: methods.map(({ skill_id, version }) => ({ skill_id, version })),
    audiovisual_style: { skill_id: "style-b", version: "1.0.0" },
  })));
});

it("preserves the editable draft on repeated or incomplete same-revision reads", async () => {
  const props = { responseLocale: "zh-CN", onClose: vi.fn(), onUpdated: vi.fn(), onConversationRefresh: vi.fn() };
  const view = render(<BrandSkillPicker {...props} decisions={initial} />);
  fireEvent.click(await findMethod(/ritual/));
  showStyles();
  fireEvent.click(screen.getByLabelText(/style-b/));

  for (const decisions of [structuredClone(initial), { ...initial, open_card: null, skill_stack: null }]) {
    view.rerender(<BrandSkillPicker {...props} decisions={decisions} />);
    showMethods();
    expect((screen.getByLabelText(/ritual/) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByLabelText(/ritual/).matches(":disabled")).toBe(false);
    showStyles();
    expect((screen.getByLabelText(/style-b/) as HTMLInputElement).checked).toBe(true);
  }

  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledWith("w1", expect.objectContaining({
    creative_methods: methods.map(({ skill_id, version }) => ({ skill_id, version })),
    audiovisual_style: { skill_id: "style-b", version: "1.0.0" },
  })));
});

it.each([4, 6])("does not enable a late card with mismatched revision %s", async (stage_revision) => {
  const waiting = { ...initial, open_card: null, skill_stack: null };
  const props = { responseLocale: "zh-CN", onClose: vi.fn(), onUpdated: vi.fn(), onConversationRefresh: vi.fn() };
  const view = render(<BrandSkillPicker {...props} decisions={waiting} open={false} />);
  view.rerender(<BrandSkillPicker {...props} decisions={{ ...initial, open_card: { ...initial.open_card!, stage_revision } }} open />);
  await screen.findByText("正在准备推荐组合，请稍候…");
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.queryByRole("radio")).toBeNull();
  expect(screen.queryByRole("button", { name: "保存" })).toBeNull();
  expect(agentCanvasApi.brandSelectSkills).not.toHaveBeenCalled();
});

it("shows only a loading state until the creative catalog is ready", async () => {
  let resolve!: (value: { items: typeof methods }) => void;
  vi.mocked(agentCanvasApi.brandCreativeMethodSkills).mockReturnValue(new Promise(done => { resolve = done; }));
  setup();
  expect(screen.getByRole("status").textContent).toContain("正在加载技能");
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.queryByRole("radio")).toBeNull();
  expect(screen.queryByRole("button", { name: "保存" })).toBeNull();
  expect(screen.queryByRole("button", { name: "重新加载" })).toBeNull();
  expect(screen.getByRole("button", { name: "取消" })).toBeTruthy();
  await act(async () => resolve({ items: methods }));
  showMethods();
  expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  showStyles();
  expect(screen.getAllByRole("radio")).toHaveLength(4);
  expect(screen.getByRole("button", { name: "保存" }).hasAttribute("disabled")).toBe(false);
});

it("hides partial choices on catalog failure and reveals them after retry", async () => {
  vi.mocked(agentCanvasApi.brandCreativeMethodSkills).mockRejectedValueOnce(new Error("Offline"));
  setup();
  expect((await screen.findByRole("alert")).textContent).toContain("加载失败");
  expect(screen.queryByRole("radio")).toBeNull();
  expect(screen.queryByRole("button", { name: "保存并发送" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
  await findMethod(/metaphor/);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole("button", { name: "保存" }).hasAttribute("disabled")).toBe(false);
  expect(agentCanvasApi.brandCreativeMethodSkills).toHaveBeenCalledTimes(2);
  expect(agentCanvasApi.brandSelectSkills).not.toHaveBeenCalled();
});

it("waits for recommendations even after the creative catalog has loaded", async () => {
  const props = { responseLocale: "zh-CN", onClose: vi.fn(), onUpdated: vi.fn(), onConversationRefresh: vi.fn() };
  const view = render(<BrandSkillPicker {...props} decisions={{ ...initial, open_card: null, skill_stack: null }} />);
  await screen.findByText("正在准备推荐组合，请稍候…");
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.queryByRole("radio")).toBeNull();
  expect(screen.queryByRole("button", { name: "保存" })).toBeNull();
  view.rerender(<BrandSkillPicker {...props} decisions={initial} />);
  expect((await findMethod(/metaphor/) as HTMLInputElement).checked).toBe(true);
  showStyles();
  expect(screen.getAllByRole("radio")).toHaveLength(4);
});

it("offers recovery for an empty catalog without showing partial options", async () => {
  vi.mocked(agentCanvasApi.brandCreativeMethodSkills).mockResolvedValueOnce({ items: [] });
  setup();
  expect((await screen.findByRole("alert")).textContent).toContain("暂无可选创意方法");
  expect(screen.queryByRole("radio")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
  await findMethod(/metaphor/);
  expect(screen.queryByRole("alert")).toBeNull();
});

it("ignores a failed request from a closed dialog after reopening succeeds", async () => {
  let reject!: (reason: Error) => void;
  vi.mocked(agentCanvasApi.brandCreativeMethodSkills).mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
  const props = { decisions: initial, responseLocale: "zh-CN", onClose: vi.fn(), onUpdated: vi.fn(), onConversationRefresh: vi.fn() };
  const view = render(<BrandSkillPicker {...props} open />);
  view.rerender(<BrandSkillPicker {...props} open={false} />);
  expect(screen.queryByRole("dialog")).toBeNull();
  view.rerender(<BrandSkillPicker {...props} open />);
  fireEvent.click(await findMethod(/ritual/));
  await act(async () => reject(new Error("Late failure")));
  expect(screen.queryByRole("alert")).toBeNull();
  expect((screen.getByLabelText(/ritual/) as HTMLInputElement).checked).toBe(true);
  expect(screen.getByRole("button", { name: "保存" }).hasAttribute("disabled")).toBe(false);
});


it("confirms an early combination and continues to creative directions", async () => {
  const early = normalizeBrandDecisionPanelV1({ ...initial,
    journey: { ...initial.journey, stage: "skill-stack-early" },
    open_card: { ...initial.open_card!, stage: "skill-stack-early" },
  });
  const next = { ...early, early_skills_confirmed: true,
    journey: { ...early.journey, stage: "hypothesis" as const, stage_revision: 6 }, open_card: null };
  vi.mocked(agentCanvasApi.brandSelectSkills).mockResolvedValue(next);
  vi.mocked(agentCanvasApi.brandDecisions).mockResolvedValue(next);
  render(<BrandSkillPicker decisions={early} responseLocale="zh-CN" onClose={vi.fn()} onUpdated={vi.fn()} onConversationRefresh={vi.fn()} />);
  await findMethod(/metaphor/);
  fireEvent.click(screen.getByRole("button", { name: "保存并发送" }));
  await waitFor(() => expect(agentCanvasApi.brandNextQuestion).toHaveBeenCalledOnce());
  expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledWith("w1", expect.objectContaining({ confirm: true, card_id: "card-5" }));
});


it("shows Chinese and original catalog titles across tabs and locales while saving skill identities", async () => {
  const method = { skill_id: "absence-reveal", version: "1.0.0", skill_kind: "creative_method" as const, title: "Absence Reveal", summary: "Prove the product by removing it." };
  vi.mocked(agentCanvasApi.brandCreativeMethodSkills).mockResolvedValue({ items: [method] });
  vi.mocked(agentCanvasApi.listVideoSkills).mockResolvedValue({ catalog_version: "1", categories: [], next_cursor: null,
    items: [
      { skill_id: "platform-default", title: "Platform Default" },
      { skill_id: "industrial-product-commercial", title: "工业产品功能广告" },
    ].map(skill => ({ ...skill, version: "1.0.0", summary: "", category: "styles", tags: [], supported_use_cases: [], preview: null, display_order: 0 })),
  });
  const decisions = { ...initial, skill_stack: { entries: [
    { ...method, selected: true, reason: "匹配产品需求" },
    { skill_id: "platform-default", version: "1.0.0", skill_kind: "audiovisual_style" as const, title: "Platform Default", selected: true, reason: "均衡表达" },
  ] } };
  const props = { decisions, onClose: vi.fn(), onUpdated: vi.fn(), onConversationRefresh: vi.fn() };
  const view = render(<BrandSkillPicker {...props} responseLocale="zh-CN" />);
  await findMethod(/Absence Reveal/);
  expect(screen.getByText("缺席揭示")).toBeTruthy();
  expect(screen.getByText("Absence Reveal")).toBeTruthy();
  expect(screen.getByLabelText("缺席揭示 / Absence Reveal").closest("label")?.title).toContain("先展示产品缺席时的生活");
  showStyles();
  expect(screen.getByLabelText("平台默认风格 / Platform Default")).toBeTruthy();
  expect(screen.getByLabelText("工业产品功能广告 / Industrial Product Commercial")).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: /已选 Skill/ }));
  expect(screen.getByLabelText("缺席揭示 / Absence Reveal")).toBeTruthy();
  expect(screen.getByLabelText("平台默认风格 / Platform Default")).toBeTruthy();
  showMethods();
  view.rerender(<BrandSkillPicker {...props} responseLocale="en-US" />);
  expect(screen.getByText("缺席揭示")).toBeTruthy();
  expect(screen.getByText("Absence Reveal")).toBeTruthy();
  expect(screen.getByLabelText("缺席揭示 / Absence Reveal").closest("label")?.title).toContain("Prove the product by removing it.");
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledWith("w1", expect.objectContaining({
    creative_methods: [{ skill_id: "absence-reveal", version: "1.0.0" }],
    audiovisual_style: { skill_id: "platform-default", version: "1.0.0" },
  })));
});

it("keeps draft selections across tabs and removes them from the selected gallery without writing", async () => {
  const activate = vi.spyOn(agentCanvasApi, "createAgentCanvasVideoSkillRun");
  setup();
  fireEvent.click(await findMethod(/ritual/));
  showStyles();
  fireEvent.click(screen.getByLabelText(/style-b/));
  fireEvent.click(screen.getByRole("tab", { name: /已选 Skill/ }));
  expect(screen.getAllByRole("checkbox")).toHaveLength(3);
  fireEvent.click(screen.getByLabelText("metaphor"));
  expect(screen.queryByLabelText("metaphor")).toBeNull();
  fireEvent.click(screen.getByLabelText("style-b"));
  expect(screen.getByRole("button", { name: "保存" }).hasAttribute("disabled")).toBe(true);
  showMethods();
  expect((screen.getByLabelText("ritual") as HTMLInputElement).checked).toBe(true);
  expect((screen.getByLabelText("metaphor") as HTMLInputElement).checked).toBe(false);
  showStyles();
  fireEvent.click(screen.getByLabelText("style-c"));
  expect(screen.getByRole("button", { name: "保存" }).hasAttribute("disabled")).toBe(false);
  expect(agentCanvasApi.brandSelectSkills).not.toHaveBeenCalled();
  expect(activate).not.toHaveBeenCalled();
});

it("limits creative selections to seven while allowing a selected card to be removed", async () => {
  const extra = Array.from({ length: 7 }, (_, index) => ({ ...methods[0], skill_id: `extra-${index}`, title: `Extra ${index}` }));
  vi.mocked(agentCanvasApi.brandCreativeMethodSkills).mockResolvedValue({ items: [...methods, ...extra] });
  setup();
  await findMethod(/metaphor/);
  for (let index = 0; index < 6; index += 1) fireEvent.click(screen.getByLabelText(`Extra ${index}`));
  expect(screen.getByLabelText("Extra 6").matches(":disabled")).toBe(true);
  expect(screen.getByLabelText("metaphor").matches(":disabled")).toBe(false);
  fireEvent.click(screen.getByLabelText("metaphor"));
  expect(screen.getByLabelText("Extra 6").matches(":disabled")).toBe(false);
  fireEvent.click(screen.getByLabelText("Extra 6"));
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(agentCanvasApi.brandSelectSkills).toHaveBeenCalledWith("w1", expect.objectContaining({ creative_methods: extra.map(({ skill_id, version }) => ({ skill_id, version })) })));
});

it("recovers a failed audiovisual catalog without exposing incomplete choices", async () => {
  vi.mocked(agentCanvasApi.listVideoSkills).mockRejectedValueOnce(new Error("Offline"));
  setup();
  expect((await screen.findByRole("alert")).textContent).toContain("加载失败");
  expect(screen.queryByRole("tab")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
  expect(await screen.findByRole("radio", { name: "style-b" })).toBeTruthy();
  expect(agentCanvasApi.listVideoSkills).toHaveBeenCalledTimes(2);
});

it("blocks a retired style version until it is replaced from the current catalog", async () => {
  const stale = { ...initial, skill_stack: { entries: initial.skill_stack!.entries.map(entry => entry.skill_id === "style-a" ? { ...entry, version: "0.9.0" } : entry) } };
  render(<BrandSkillPicker decisions={stale} responseLocale="zh-CN" onClose={vi.fn()} onUpdated={vi.fn()} onConversationRefresh={vi.fn()} />);
  await screen.findByRole("radio", { name: "style-b" });
  expect(screen.getByRole("button", { name: "保存" }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByRole("tab", { name: /已选 Skill/ }));
  expect(screen.getByText("需重新选择")).toBeTruthy();
  showStyles();
  fireEvent.click(screen.getByRole("radio", { name: "style-b" }));
  expect(screen.getByRole("button", { name: "保存" }).hasAttribute("disabled")).toBe(false);
});
