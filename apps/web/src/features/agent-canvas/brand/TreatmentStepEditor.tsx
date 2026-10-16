import type { UiMessageKey } from "../../../i18n/uiMessages";
import { useTranslation } from "../../../i18n/useTranslation";
import { useRef, useState } from "react";
import { agentCanvasApi } from "../../../api/agentCanvasApi";
import type { BrandDecisionPanelV1, BrandTreatmentStepResultV1 } from "./brandDecisions";

const fields = {
  hook: ["action_sequence", "product_role"], story: ["setup", "progression", "resolution", "product_role"],
  character: ["identity", "appearance", "performance"], scene: ["spaces", "boundaries"],
  visual: ["color_and_light", "materials", "wardrobe"], camera: ["people_camera", "product_shots", "prohibited_shots"],
  editing: ["opening", "middle", "ending"], sound: ["ambience", "effects", "music_entry", "progression"],
} as const;
const titles: Record<string, UiMessageKey> = {action_sequence:"Action sequence",product_role:"Product role",setup:"Setup",progression:"Progression",resolution:"Resolution",identity:"Identity",appearance:"Appearance",performance:"Performance",spaces:"Spaces",boundaries:"Boundaries",color_and_light:"Color and light",materials:"Materials",wardrobe:"Wardrobe",people_camera:"People camera",product_shots:"Product shots",prohibited_shots:"Prohibited shots",opening:"Opening",middle:"Middle",ending:"Ending",ambience:"Ambience",effects:"Effects",music_entry:"Music entry"};
export function TreatmentStepEditor({ step, panel, responseLocale = "en-US", onSaved, onCancel }: {
  step: BrandTreatmentStepResultV1; panel: BrandDecisionPanelV1; responseLocale?: string;
  onSaved: (panel: BrandDecisionPanelV1) => void; onCancel: () => void;
}) {
  const t = useTranslation(responseLocale);
  const [label, setLabel] = useState(step.selected_label);
  const [sections, setSections] = useState(() => fields[step.step_key].map(key => step.structured_detail?.sections.find(s => s.key === key) ?? {key,title:t(titles[key]),text:""}));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const valid = label.trim() && label.length <= 160 && sections.every(s => s.title.trim() && s.title.length <= 80 && s.text.trim() && s.text.length <= 400);
  return <form onSubmit={async event => {
    event.preventDefault(); if (!valid || inFlight.current) return;
    inFlight.current = true; setPending(true); setError("");
    try { onSaved(await agentCanvasApi.brandEditTreatment(panel.workflow_id, step.step_key, {expected_stage_revision:panel.journey.stage_revision,selected_label:label,detail:{sections}})); }
    catch (cause) { setError(cause instanceof Error ? cause.message : t("Save failed. Your input was kept; check the content or reload the latest review.")); }
    finally { inFlight.current = false; setPending(false); }
  }}>
    <label>{t("Treatment label")}<input value={label} maxLength={160} onChange={e => setLabel(e.target.value)} disabled={pending}/></label>
    {sections.map((section,index) => <fieldset key={section.key} disabled={pending}><legend>{t(titles[section.key])}</legend>
      <label>{t("Section title")}<input value={section.title} maxLength={80} onChange={e => setSections(current => current.map((s,i) => i === index ? {...s,title:e.target.value} : s))}/></label>
      <label>{t("Section content")}<textarea rows={4} value={section.text} maxLength={400} onChange={e => setSections(current => current.map((s,i) => i === index ? {...s,text:e.target.value} : s))}/></label>
    </fieldset>)}
    {error && <p role="alert">{error}</p>}
    <button type="submit" disabled={!valid || pending}>{t("Save changes")}</button><button type="button" disabled={pending} onClick={onCancel}>{t("Cancel editing")}</button>
  </form>;
}
