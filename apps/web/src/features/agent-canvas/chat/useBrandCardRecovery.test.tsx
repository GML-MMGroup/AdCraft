import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { LocaleProvider } from "../../../i18n/locale";
import type { GuidedSessionStateV2 } from "../../../types-v2";
import type { BrandDecisionPanelV1 } from "../brand/brandDecisions";
import { useBrandCardRecovery } from "./useBrandCardRecovery";

const api = vi.hoisted(() => ({ brandNextQuestion: vi.fn(), brandDecisions: vi.fn(), agentCanvasCreativeSession: vi.fn() }));
vi.mock("../../../api/agentCanvasApi", () => ({ agentCanvasApi: api }));
const panel = { workflow_id: "w", journey: { stage: "treatment" }, open_card: { card_id: "new-card" },
  treatment_steps: [{ step_key: "hook", selected_label: "Retained Hook", detail: "Confirmed design" }] } as unknown as BrandDecisionPanelV1;
const completeSteps = (["hook", "story", "character", "scene", "visual", "camera", "editing", "sound"] as const)
  .map(step_key => ({ ...panel.treatment_steps[0], step_key }));
const session = { workflow_id: "w", revision: 9, interaction: {
  interaction_id: "new", revision: 2, expected_session_revision: 9, status: "open",
  content: { content_kind: "concept_choice", capability_id: "brand_treatment" },
} } as unknown as GuidedSessionStateV2;
beforeEach(() => {
  vi.resetAllMocks();
  api.brandNextQuestion.mockResolvedValue(panel.open_card);
  api.brandDecisions.mockResolvedValue(panel);
  api.agentCanvasCreativeSession.mockResolvedValue(session);
});
afterEach(cleanup);
function setup() {
  const onDecisions = vi.fn(); const onSession = vi.fn(); const refreshTimeline = vi.fn().mockResolvedValue(undefined);
  const hook = renderHook(({ workflowId, busy }) => useBrandCardRecovery({ workflowId, busy, onDecisions, onSession, refreshTimeline }), {
    initialProps: { workflowId: "w", busy: false },
  });
  act(() => hook.result.current.markStale("old", true));
  return { ...hook, onDecisions, onSession, refreshTimeline };
}

it("requires a click, replaces authority, keeps confirmed details and permanently fences the old card", async () => {
  const h = setup();
  expect(api.brandNextQuestion).not.toHaveBeenCalled();
  expect(h.result.current.blocksSubmission("old")).toBe(true);
  await act(async () => { await h.result.current.refresh(); });
  expect(api.brandNextQuestion).toHaveBeenCalledExactlyOnceWith("w");
  expect(h.onDecisions).toHaveBeenCalledExactlyOnceWith(panel);
  expect(h.onSession).toHaveBeenCalledExactlyOnceWith(session);
  expect(panel.treatment_steps).toEqual([{ step_key: "hook", selected_label: "Retained Hook", detail: "Confirmed design" }]);
  expect(h.result.current.state).toBeNull();
  expect(h.result.current.blocksSubmission("old")).toBe(true);
  expect(h.result.current.blocksSubmission("new")).toBe(false);
  await act(async () => { await h.result.current.refresh(); });
  expect(api.brandNextQuestion).toHaveBeenCalledOnce();
});

it("waits for a running chat turn without automatically refreshing when it finishes", async () => {
  const h = setup(); h.rerender({ workflowId: "w", busy: true });
  await act(async () => { await h.result.current.refresh(); });
  expect(api.brandNextQuestion).not.toHaveBeenCalled();
  h.rerender({ workflowId: "w", busy: false });
  expect(api.brandNextQuestion).not.toHaveBeenCalled();
  await act(async () => { await h.result.current.refresh(); });
  expect(api.brandNextQuestion).toHaveBeenCalledOnce();
});

it("coalesces rapid clicks and does not write or publish to a newly opened workflow", async () => {
  let finish!: (value: unknown) => void;
  api.brandNextQuestion.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const h = setup(); let request!: Promise<void>;
  act(() => { request = h.result.current.refresh(); void h.result.current.refresh(); });
  expect(api.brandNextQuestion).toHaveBeenCalledOnce();
  h.rerender({ workflowId: "other", busy: false });
  await act(async () => { finish(panel.open_card); await request; });
  expect(h.result.current.state).toBeNull();
  expect(api.brandDecisions).not.toHaveBeenCalled();
  expect(h.onDecisions).not.toHaveBeenCalled();
});

it("shows generation errors and leaves recovery available without an automatic retry", async () => {
  api.brandNextQuestion.mockRejectedValueOnce(new Error("Creative model unavailable"));
  const h = setup();
  await act(async () => { await h.result.current.refresh(); });
  expect(h.result.current.state).toMatchObject({ phase: "error", needsQuestion: true, error: "Creative model unavailable" });
  expect(h.onDecisions).not.toHaveBeenCalled();
  expect(api.brandNextQuestion).toHaveBeenCalledOnce();
  await act(async () => { await h.result.current.refresh(); });
  expect(h.result.current.state).toBeNull();
});

it.each(["panel", "session", "timeline"])("retries GETs only after generation succeeds but %s read fails", async failure => {
  const h = setup();
  if (failure === "panel") api.brandDecisions.mockRejectedValueOnce(new Error("Read failed"));
  if (failure === "session") api.agentCanvasCreativeSession.mockRejectedValueOnce(new Error("Read failed"));
  if (failure === "timeline") h.refreshTimeline.mockRejectedValueOnce(new Error("Read failed"));
  await act(async () => { await h.result.current.refresh(); });
  expect(h.result.current.state).toMatchObject({ phase: "error", needsQuestion: false });
  expect(h.onDecisions).not.toHaveBeenCalled();
  await act(async () => { await h.result.current.refresh(); });
  expect(api.brandNextQuestion).toHaveBeenCalledOnce();
  expect(h.result.current.state).toBeNull();
});

it.each([null, { ...session, interaction: null }, { ...session, interaction: { ...session.interaction, status: "closed" } }])("handles 204 through Treatment review with all eight steps confirmed (session: %s)", async completedSession => {
  api.brandNextQuestion.mockResolvedValue(null);
  api.brandDecisions.mockResolvedValue({ ...panel, open_card: null, treatment_steps: completeSteps });
  api.agentCanvasCreativeSession.mockResolvedValue(completedSession);
  const h = setup();
  await act(async () => { await h.result.current.refresh(); });
  expect(h.result.current.state).toMatchObject({ phase: "review", needsQuestion: false, error: null });
  expect(h.result.current.blocksAutomaticQuestion()).toBe(true);
});

it.each([0, 7])("keeps refresh available while the next treatment card is being prepared with %s confirmed steps", async count => {
  api.brandNextQuestion.mockResolvedValue(null);
  api.brandDecisions.mockResolvedValue({ ...panel, open_card: null, treatment_steps: completeSteps.slice(0, count) });
  api.agentCanvasCreativeSession.mockResolvedValue({ ...session, interaction: null });
  const h = setup();
  await act(async () => { await h.result.current.refresh(); });
  expect(h.result.current.state).toMatchObject({
    phase: "error", needsQuestion: true,
    error: "The next treatment question is still being prepared. Refresh again in a moment.",
  });
  expect(h.result.current.blocksAutomaticQuestion()).toBe(true);

  api.brandDecisions.mockResolvedValue(panel);
  api.agentCanvasCreativeSession.mockResolvedValue(session);
  await act(async () => { await h.result.current.refresh(); });
  expect(api.brandNextQuestion).toHaveBeenCalledTimes(2);
  expect(h.result.current.state).toBeNull();
  expect(h.result.current.blocksSubmission("new")).toBe(false);
});

it("localizes the message while a treatment question is being prepared", async () => {
  api.brandDecisions.mockResolvedValue({ ...panel, open_card: null, treatment_steps: [] });
  api.agentCanvasCreativeSession.mockResolvedValue(null);
  const h = renderHook(() => useBrandCardRecovery({
    workflowId: "w", busy: false, refreshTimeline: vi.fn().mockResolvedValue(undefined), onSession: vi.fn(),
  }), { wrapper: ({ children }) => <LocaleProvider initialLocale="zh-CN">{children}</LocaleProvider> });
  act(() => h.result.current.markStale("old", true));
  await act(async () => { await h.result.current.refresh(); });
  expect(h.result.current.state).toMatchObject({ phase: "error", needsQuestion: true,
    error: "下一个创意方案问题仍在准备中，请稍后再次刷新。" });
});

it("releases recovery when authoritative state has already moved to production", async () => {
  api.brandDecisions.mockResolvedValue({ ...panel, journey: { stage: "production" }, open_card: null });
  const h = setup();
  await act(async () => { await h.result.current.refresh(); });
  expect(h.result.current.state).toBeNull();
  expect(h.result.current.blocksSubmission("production-question")).toBe(false);
});

it("reloads a closed interaction without requesting another question or reusing its selection", async () => {
  const h = setup(); act(() => h.result.current.markStale("old", false));
  await act(async () => { await h.result.current.refresh(); });
  expect(api.brandNextQuestion).not.toHaveBeenCalled();
  expect(h.onSession).toHaveBeenCalledExactlyOnceWith(session);
  expect(h.result.current.blocksSubmission("old")).toBe(true);
});

it("keeps the old card blocked if reads still return its superseded identity", async () => {
  api.agentCanvasCreativeSession.mockResolvedValue({ ...session, interaction: { ...session.interaction, interaction_id: "old" } });
  const h = setup();
  await act(async () => { await h.result.current.refresh(); });
  expect(h.result.current.state?.phase).toBe("error");
  expect(h.result.current.blocksSubmission("old")).toBe(true);
});
