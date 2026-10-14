import { useTranslation } from "../../../i18n/useTranslation";
import type { BrandBriefSummary, BrandTreatmentDocument } from "./brandDecisions";
import { TreatmentSections } from "./TreatmentSections";
export function BriefView({ title, brief, responseLocale = "en-US" }: { title: string; brief?: BrandBriefSummary | null; responseLocale?: string }) {
  const t = useTranslation(responseLocale);
  return <section><h3>{title}</h3>{!brief ? <p>{t("Not provided")}</p> : <>
    {[...brief.values.map(value => ({value,inherited:false})),...brief.inherited_values.map(value => ({value,inherited:true}))].map(({value,inherited},index) => <p key={`${value.slot_id}-${index}`}>
      <strong>{({fact:t("Fact"),assumption:t("Assumption"),constraint:t("Constraint"),preference:t("Preference")})[value.kind]}</strong> · {value.provenance === "user_confirmed" ? t("User confirmed") : t("Agent recommended")}{inherited ? ` · ${t("Inherited from brand profile")}` : ""}<br/>{value.value}
    </p>)}
    {brief.unresolved_fields.length > 0 && <p>{t("Unresolved: {items}. No defaults are added.", { items: brief.unresolved_fields.join("、") })}</p>}
  </>}</section>;
}
export function TreatmentDocumentView({ document: doc, responseLocale = "en-US" }: { document: BrandTreatmentDocument; responseLocale?: string }) {
  const t = useTranslation(responseLocale);
  return <>
    <BriefView title={t("Brand profile")} brief={doc.brand_profile} responseLocale={responseLocale}/><BriefView title={t("Campaign brief")} brief={doc.campaign_brief} responseLocale={responseLocale}/>
    <section><h3>{t("Selected creative hypothesis")}</h3>{doc.selected_hypothesis ? <>
      <h4>{doc.selected_hypothesis.label}</h4>
      {([[t("Insight"),'insight'],[t("Mechanism"),'mechanism'],[t("Assumption"),'hypothesis'],[t("Product role"),'product_role'],[t("Opening mechanism"),'hook_mechanism'],[t("Why"),'why']] as const).map(([label,key]) => <p key={key}><strong>{label}</strong><br/>{doc.selected_hypothesis?.[key] ?? t("Not provided")}</p>)}
    </> : <p>{t("Not provided")}</p>}</section>
    <section><h3>{t("AdSpec")}</h3>{doc.adspec?.items.map(item => <p key={item.item_key}>{item.item_text} · {item.state}</p>) ?? t("Not provided")}</section>
    <section><h3>{t("Skills and versions")}</h3>{doc.skill_stack?.entries.map(skill => <p key={`${skill.skill_kind}-${skill.skill_id}`}>{skill.title} · {skill.version ?? t("Version not provided")} · {skill.selected ? t("Selected") : t("Not selected")}<br/>{skill.reason}</p>) ?? t("Not provided")}</section>
    <section><h3>{t("Product presentation")}</h3><TreatmentSections detail={{sections:doc.product_presentation}}/></section>
    <section><h3>{t("Authorized asset references (metadata only)")}</h3>{doc.authorized_asset_references.length === 0 ? <p>{t("Not provided")}</p> : doc.authorized_asset_references.map(ref => <details key={ref.binding_id}><summary>{ref.display_name}</summary><pre>{JSON.stringify(ref,null,2)}</pre></details>)}<p>{t("References only apply to this Workflow and target node; they are not linked automatically to other nodes.")}</p></section>
    <section><h3>{t("Execution limitations")}</h3>{doc.execution_limitations.map(item => <p key={item}>{item === "sound_effects_and_mixing_not_automated" ? t("Environmental sound, effects and music intent are retained; sound effects and mixing are not automated.") : item}</p>)}</section>
  </>;
}
