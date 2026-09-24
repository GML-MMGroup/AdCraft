import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { agentCanvasApi } from "../../../api/agentCanvasApi";
import { normalizeBrandDecisionPanelV1 } from "../brand/brandDecisionNormalizers";
import { BrandTreatmentConfirmation } from "./BrandTreatmentConfirmation";
vi.mock("../../../api/agentCanvasApi", () => ({agentCanvasApi:{brandDecisions:vi.fn(),brandLockTreatment:vi.fn(),brandEditTreatment:vi.fn()}}));
function panel(digest = "a".repeat(64), complete = true) {
  return normalizeBrandDecisionPanelV1({project_id:"p",workflow_id:"w",mode:"brand",brand_name:"Brand",journey:{stage:"treatment",stage_revision:12},treatment_steps:[],treatment_locked:false,
    treatment_document:{schema_version:"2",brand_profile:{values:[],inherited_values:[],unresolved_fields:["audience"]},campaign_brief:{values:[],inherited_values:[],unresolved_fields:[]},selected_hypothesis:null,adspec:null,skill_stack:null,treatment_steps:[],product_presentation:[],authorized_asset_references:[],complete,missing_sections:complete?[]:["hook.product_role"],content_digest:digest,execution_limitations:["sound_effects_and_mixing_not_automated"]}});
}
beforeEach(() => { HTMLDialogElement.prototype.showModal = function() {this.setAttribute("open","");}; vi.mocked(agentCanvasApi.brandDecisions).mockResolvedValue(panel()); });
afterEach(() => {cleanup();vi.resetAllMocks();});
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
