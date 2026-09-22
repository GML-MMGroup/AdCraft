import type { BrandBriefSummary, BrandTreatmentDocument } from "./brandDecisions";
import { TreatmentSections } from "./TreatmentSections";
export function BriefView({ title, brief }: { title: string; brief?: BrandBriefSummary | null }) {
  return <section><h3>{title}</h3>{!brief ? <p>未提供</p> : <>
    {[...brief.values.map(value => ({value,inherited:false})),...brief.inherited_values.map(value => ({value,inherited:true}))].map(({value,inherited},index) => <p key={`${value.slot_id}-${index}`}>
      <strong>{({fact:"事实",assumption:"假设",constraint:"约束",preference:"偏好"})[value.kind]}</strong> · {value.provenance === "user_confirmed" ? "用户确认" : "Agent 推荐"}{inherited ? " · 从品牌资料继承" : ""}<br/>{value.value}
    </p>)}
    {brief.unresolved_fields.length > 0 && <p>尚未明确：{brief.unresolved_fields.join("、")}。不补充默认值。</p>}
  </>}</section>;
}
export function TreatmentDocumentView({ document: doc }: { document: BrandTreatmentDocument }) {
  return <>
    <BriefView title="品牌资料" brief={doc.brand_profile}/><BriefView title="Campaign Brief" brief={doc.campaign_brief}/>
    <section><h3>选定创意假设</h3>{doc.selected_hypothesis ? <>
      <h4>{doc.selected_hypothesis.label}</h4>
      {([['洞察','insight'],['机制','mechanism'],['假设','hypothesis'],['产品角色','product_role'],['开场机制','hook_mechanism'],['推荐理由','why']] as const).map(([label,key]) => <p key={key}><strong>{label}</strong><br/>{doc.selected_hypothesis?.[key] ?? "未提供"}</p>)}
    </> : <p>未提供</p>}</section>
    <section><h3>AdSpec</h3>{doc.adspec?.items.map(item => <p key={item.item_key}>{item.item_text} · {item.state}</p>) ?? "未提供"}</section>
    <section><h3>Skills 与版本</h3>{doc.skill_stack?.entries.map(skill => <p key={`${skill.skill_kind}-${skill.skill_id}`}>{skill.title} · {skill.version ?? "版本未提供"} · {skill.selected ? "已选" : "未选"}<br/>{skill.reason}</p>) ?? "未提供"}</section>
    <section><h3>产品呈现</h3><TreatmentSections detail={{sections:doc.product_presentation}}/></section>
    <section><h3>授权素材引用（仅元数据）</h3>{doc.authorized_asset_references.length === 0 ? <p>未提供</p> : doc.authorized_asset_references.map(ref => <details key={ref.binding_id}><summary>{ref.display_name}</summary><pre>{JSON.stringify(ref,null,2)}</pre></details>)}<p>引用仅对记录中的 Workflow 和目标节点有效，不会自动连接到其他节点。</p></section>
    <section><h3>执行限制</h3>{doc.execution_limitations.map(item => <p key={item}>{item === "sound_effects_and_mixing_not_automated" ? "环境声、音效与音乐进入意图会保留；当前不自动生成音效或完成混音。" : item}</p>)}</section>
  </>;
}
