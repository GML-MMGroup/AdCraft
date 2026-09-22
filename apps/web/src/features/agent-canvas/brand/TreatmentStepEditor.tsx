import { useRef, useState } from "react";
import { agentCanvasApi } from "../../../api/agentCanvasApi";
import type { BrandDecisionPanelV1, BrandTreatmentStepResultV1 } from "./brandDecisions";

const fields = {
  hook: ["action_sequence", "product_role"], story: ["setup", "progression", "resolution", "product_role"],
  character: ["identity", "appearance", "performance"], scene: ["spaces", "boundaries"],
  visual: ["color_and_light", "materials", "wardrobe"], camera: ["people_camera", "product_shots", "prohibited_shots"],
  editing: ["opening", "middle", "ending"], sound: ["ambience", "effects", "music_entry", "progression"],
} as const;
const titles: Record<string, string> = {action_sequence:"动作顺序",product_role:"产品角色",setup:"铺垫",progression:"推进",resolution:"结局",identity:"身份",appearance:"外观",performance:"表演",spaces:"空间",boundaries:"空间边界",color_and_light:"色彩与光线",materials:"材质",wardrobe:"服装",people_camera:"人物镜头",product_shots:"产品镜头",prohibited_shots:"禁止镜头",opening:"开场",middle:"中段",ending:"结尾",ambience:"环境声",effects:"音效",music_entry:"音乐进入"};
export function TreatmentStepEditor({ step, panel, onSaved, onCancel }: {
  step: BrandTreatmentStepResultV1; panel: BrandDecisionPanelV1;
  onSaved: (panel: BrandDecisionPanelV1) => void; onCancel: () => void;
}) {
  const [label, setLabel] = useState(step.selected_label);
  const [sections, setSections] = useState(() => fields[step.step_key].map(key => step.structured_detail?.sections.find(s => s.key === key) ?? {key,title:titles[key],text:""}));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const valid = label.trim() && label.length <= 160 && sections.every(s => s.title.trim() && s.title.length <= 80 && s.text.trim() && s.text.length <= 400);
  return <form onSubmit={async event => {
    event.preventDefault(); if (!valid || inFlight.current) return;
    inFlight.current = true; setPending(true); setError("");
    try { onSaved(await agentCanvasApi.brandEditTreatment(panel.workflow_id, step.step_key, {expected_stage_revision:panel.journey.stage_revision,selected_label:label,detail:{sections}})); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "保存失败。输入已保留，请检查内容或重新载入最新审阅。"); }
    finally { inFlight.current = false; setPending(false); }
  }}>
    <label>方案标签<input value={label} maxLength={160} onChange={e => setLabel(e.target.value)} disabled={pending}/></label>
    {sections.map((section,index) => <fieldset key={section.key} disabled={pending}><legend>{titles[section.key]}</legend>
      <label>段落标题<input value={section.title} maxLength={80} onChange={e => setSections(current => current.map((s,i) => i === index ? {...s,title:e.target.value} : s))}/></label>
      <label>段落内容<textarea rows={4} value={section.text} maxLength={400} onChange={e => setSections(current => current.map((s,i) => i === index ? {...s,text:e.target.value} : s))}/></label>
    </fieldset>)}
    {error && <p role="alert">{error}</p>}
    <button type="submit" disabled={!valid || pending}>保存修改</button><button type="button" disabled={pending} onClick={onCancel}>取消编辑</button>
  </form>;
}
