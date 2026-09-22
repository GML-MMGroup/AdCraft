import { expect, it } from "vitest";
import { normalizeAgentModelCallDetail } from "../agent-model-call-history";
import { callIntegrity } from "./callIntegrity";
it("keeps SDK and Pi usage, zero values and finish reasons with source paths", () => {
  const detail = normalizeAgentModelCallDetail({call_id:"c",request:{},outcome:{payload:{response:{usage:{completion_tokens:0},choices:[{finish_reason:"stop"}]},assistant_message:{usage:{input:42},stopReason:"toolUse"}}}});
  expect(callIntegrity(detail).metadata).toEqual(expect.arrayContaining([
    {path:"outcome.payload.response.usage",value:{completion_tokens:0}},
    {path:"outcome.payload.response.choices[0].finish_reason",value:"stop"},
    {path:"outcome.payload.assistant_message.stopReason",value:"toolUse"},
  ]));
});
it("reports actual capture_truncated and missing outcomes without implying running", () => {
  const detail = normalizeAgentModelCallDetail({call_id:"c",status:"incomplete",request:{complete:false,payload:{capture_truncated:true}},outcome:null});
  const result = callIntegrity(detail);
  expect(result.metadata).toEqual([]);
  expect(result.notices).toContain("request 内容已截断，缺失部分无法还原。");
  expect(result.notices).toContain("尚未记录到输出，也可能是记录丢失；无法判断是否运行中。");
});
