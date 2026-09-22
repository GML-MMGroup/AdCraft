import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { agentCanvasApi } from "../../../api/agentCanvasApi";
import { normalizeBrandDecisionPanelV1, normalizeBrandOptionCardV1 } from "./brandDecisionNormalizers";
import { TreatmentStepEditor } from "./TreatmentStepEditor";
vi.mock("../../../api/agentCanvasApi",()=>({agentCanvasApi:{brandEditTreatment:vi.fn()}}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const detail={sections:[{key:"action_sequence",title:"开场",text:"电梯门合上。"},{key:"product_role",title:"产品角色",text:"香水标志私人时间开始。"}]};
const panel=normalizeBrandDecisionPanelV1({project_id:"p",workflow_id:"w",mode:"brand",brand_name:"B",journey:{stage:"treatment",stage_revision:12},treatment_steps:[{step_key:"hook",selected_label:"开场方案",detail:"历史投影",structured_detail:detail,confirmed_at:"2026-01-01"}]});
it("preserves authored candidate and selected-step titles/text verbatim",()=>{
  const card=normalizeBrandOptionCardV1({card_id:"c",stage:"treatment",stage_revision:12,question:"选择",options:[{option_id:"o",label:"简短标签",detail}]});
  expect(card.options[0].detail).toEqual(detail);expect(panel.treatment_steps[0].structured_detail).toEqual(detail);
});
it("sends exact sections and revision, retaining user text on 422",async()=>{
  vi.mocked(agentCanvasApi.brandEditTreatment).mockRejectedValue(new Error("brand_treatment_detail_invalid"));
  render(<TreatmentStepEditor panel={panel} step={panel.treatment_steps[0]} onSaved={vi.fn()} onCancel={vi.fn()}/>);
  const input=screen.getAllByLabelText("段落内容")[0];fireEvent.change(input,{target:{value:"修改后的开场"}});
  fireEvent.click(screen.getByRole("button",{name:"保存修改"}));await screen.findByRole("alert");
  expect((input as HTMLTextAreaElement).value).toBe("修改后的开场");
  expect(agentCanvasApi.brandEditTreatment).toHaveBeenCalledWith("w","hook",{expected_stage_revision:12,selected_label:"开场方案",detail:{sections:[{...detail.sections[0],text:"修改后的开场"},detail.sections[1]]}});
  await waitFor(()=>expect((screen.getByRole("button",{name:"保存修改"}) as HTMLButtonElement).disabled).toBe(false));
});
