import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { agentCanvasApi } from "../../../api/agentCanvasApi";
import { normalizeBrandDecisionPanelV1 } from "../brand/brandDecisionNormalizers";
import { BrandTreatmentConfirmation } from "./BrandTreatmentConfirmation";
vi.mock("../../../api/agentCanvasApi", () => ({agentCanvasApi:{brandDecisions:vi.fn(),brandLockTreatment:vi.fn(),brandEditTreatment:vi.fn(),brandNextQuestion:vi.fn()}}));
function panel(digest = "a".repeat(64), complete = true) {
  return normalizeBrandDecisionPanelV1({project_id:"p",workflow_id:"w",mode:"brand",brand_name:"Brand",journey:{stage:"treatment",stage_revision:12},treatment_steps:[],treatment_locked:false,
    treatment_document:{schema_version:"2",review:{source_content_digest:"c".repeat(64)},brand_profile:{values:[],inherited_values:[],unresolved_fields:["audience"]},campaign_brief:{values:[],inherited_values:[],unresolved_fields:[]},selected_hypothesis:null,adspec:null,skill_stack:null,treatment_steps:[],product_presentation:[],authorized_asset_references:[],complete,missing_sections:complete?[]:["hook.product_role"],content_digest:digest,execution_limitations:["sound_effects_and_mixing_not_automated"]}});
}
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function() { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function() { this.removeAttribute("open"); };
  vi.mocked(agentCanvasApi.brandDecisions).mockResolvedValue(panel());
});
afterEach(() => {cleanup();vi.useRealTimers();vi.resetAllMocks();});
async function open() {
  render(<BrandTreatmentConfirmation workflowId="w" responseLocale="zh" onConfirmed={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button",{name:"打开最终审阅"}));
  await screen.findByText("方案内容完整");
}
it("confirms directly and sends precisely the displayed server digest", async () => {
  await open();
  const button=screen.getByRole("button",{name:"确认并锁定创意方案"}) as HTMLButtonElement;
  expect(button.disabled).toBe(false); fireEvent.click(button);fireEvent.click(button);
  expect(agentCanvasApi.brandLockTreatment).toHaveBeenCalledExactlyOnceWith("w","a".repeat(64));
  await waitFor(()=>expect(screen.queryByRole("dialog")).toBeNull());
});
it("retains the reviewed digest on production handoff failure", async () => {
  vi.mocked(agentCanvasApi.brandLockTreatment).mockRejectedValue({code:"requirement_persistence_failed"});
  await open();fireEvent.click(screen.getByRole("button",{name:"确认并锁定创意方案"}));await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button",{name:"确认并锁定创意方案"}));
  await waitFor(()=>expect(agentCanvasApi.brandLockTreatment).toHaveBeenCalledTimes(2));
  expect(vi.mocked(agentCanvasApi.brandLockTreatment).mock.calls.map(c=>c[1])).toEqual(["a".repeat(64),"a".repeat(64)]);
});
it("blocks stale digest and requires renewed review after refresh", async () => {
  vi.mocked(agentCanvasApi.brandLockTreatment).mockRejectedValue({code:"brand_context_stale"});await open();fireEvent.click(screen.getByRole("button",{name:"确认并锁定创意方案"}));await screen.findByRole("alert");
  expect((screen.getByRole("button",{name:"确认并锁定创意方案"}) as HTMLButtonElement).disabled).toBe(true);
  vi.mocked(agentCanvasApi.brandDecisions).mockResolvedValue(panel("b".repeat(64)));
  fireEvent.click(screen.getByRole("button",{name:"重新加载审阅"}));await waitFor(()=>expect(screen.queryByRole("alert")).toBeNull());
  fireEvent.click(screen.getByRole("button",{name:"确认并锁定创意方案"}));
  await waitFor(()=>expect(agentCanvasApi.brandLockTreatment).toHaveBeenLastCalledWith("w","b".repeat(64)));
});
it("keeps incomplete documents unconfirmable", async () => {
  vi.mocked(agentCanvasApi.brandDecisions).mockResolvedValue(panel("a".repeat(64),false));
  render(<BrandTreatmentConfirmation workflowId="w" responseLocale="zh" onConfirmed={vi.fn()}/>);fireEvent.click(screen.getByRole("button",{name:"打开最终审阅"}));await screen.findByText("方案尚不完整");
  expect((screen.getByRole("button",{name:"确认并锁定创意方案"}) as HTMLButtonElement).disabled).toBe(true);
});

it("allows the user to confirm without an AI assessment or retry call", async () => {
  const ready = panel();
  ready.treatment_document!.review = null;
  vi.mocked(agentCanvasApi.brandDecisions).mockResolvedValue(ready);
  await open();
  const button = screen.getByRole("button", {name:"确认并锁定创意方案"}) as HTMLButtonElement;
  expect(button.disabled).toBe(false);
  expect(screen.queryByRole("button", {name:"重试清单核对"})).toBeNull();
  expect(agentCanvasApi.brandNextQuestion).not.toHaveBeenCalled();
  fireEvent.click(button);
  expect(agentCanvasApi.brandLockTreatment).toHaveBeenCalledExactlyOnceWith("w", "a".repeat(64));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("times out a stalled review, aborts its request, and ignores it after a successful retry", async () => {
  vi.useFakeTimers();
  let finishOld!: (value: ReturnType<typeof panel>) => void;
  vi.mocked(agentCanvasApi.brandDecisions).mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; }));
  render(<BrandTreatmentConfirmation workflowId="w" responseLocale="zh" onConfirmed={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button", { name: "打开最终审阅" }));
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
  expect(screen.getByRole("alert").textContent).toContain("超时");
  expect(vi.mocked(agentCanvasApi.brandDecisions).mock.calls[0]![1]?.signal?.aborted).toBe(true);
  vi.mocked(agentCanvasApi.brandDecisions).mockResolvedValue(panel("b".repeat(64)));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "重新加载审阅" })); });
  expect(screen.queryByRole("alert")).toBeNull();
  await act(async () => { finishOld(panel("a".repeat(64))); });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "确认并锁定创意方案" })); });
  expect(agentCanvasApi.brandLockTreatment).toHaveBeenCalledExactlyOnceWith("w", "b".repeat(64));
});

it("allows closing a loading review and cancels the read", () => {
  vi.mocked(agentCanvasApi.brandDecisions).mockImplementationOnce(() => new Promise(() => {}));
  render(<BrandTreatmentConfirmation workflowId="w" responseLocale="zh" onConfirmed={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button", { name: "打开最终审阅" }));
  fireEvent.click(screen.getByRole("button", { name: /^(关闭|Close)$/ }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(vi.mocked(agentCanvasApi.brandDecisions).mock.calls[0]![1]?.signal?.aborted).toBe(true);
});

it("loads the review after Strict Mode cancels the first mount request", async () => {
  vi.mocked(agentCanvasApi.brandDecisions).mockImplementationOnce(() => new Promise(() => {}));
  render(<StrictMode><BrandTreatmentConfirmation workflowId="w" responseLocale="zh" onConfirmed={vi.fn()}/></StrictMode>);
  fireEvent.click(screen.getByRole("button", { name: "打开最终审阅" }));
  await screen.findByText("方案内容完整");
  expect(agentCanvasApi.brandDecisions).toHaveBeenCalledTimes(2);
  expect(vi.mocked(agentCanvasApi.brandDecisions).mock.calls[0]![1]?.signal?.aborted).toBe(true);
  expect((screen.getByRole("button", { name: "确认并锁定创意方案" }) as HTMLButtonElement).disabled).toBe(false);
});
