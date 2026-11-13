import { renderMarkdownAwareText } from "../canvas/AgentCanvasMarkdown.tsx";
import { useUiLocale } from "../../../i18n/locale.tsx";
import type { UiMessageKey } from "../../../i18n/uiMessages";
import { skillDisplayTitle } from "../skills/skillDisplayCopy.ts";
import { useTranslation } from "../../../i18n/useTranslation";
import { ChevronDownIcon, ConfirmIcon, DocumentIcon } from "../../../icons.tsx";
import type { BrandBriefSummary, BrandTreatmentDocument } from "./brandDecisions";
import { TreatmentSections } from "./TreatmentSections";

const BRIEF_LABELS: Record<string, UiMessageKey> = {
  brand_name: "Brand name", brand_audience: "Audience", brand_tone: "Brand tone",
  brand_product_focus: "Product focus", brand_product_identity: "Product",
  brand_personality: "Brand personality", brand_positioning: "Positioning",
  brand_price_band: "Price band", brand_product_visual: "Product visual",
  brand_avoid: "Avoid", brand_required_elements: "Required elements", brand_assets: "Brand assets",
  campaign_name: "Campaign name", campaign_aspect_ratio: "Format", campaign_duration: "Duration",
  campaign_goal: "Goal", campaign_platform: "Channel", campaign_audience: "Audience",
  campaign_core_message: "Core message", campaign_cta: "Call to action", campaign_non_goals: "Non-goals",
};

export function BriefView({ title, brief, responseLocale = "en-US" }: { title: string; brief?: BrandBriefSummary | null; responseLocale?: string }) {
  const t = useTranslation(responseLocale);
  return <section className="treatment-review__brief">
    <h3>{title}</h3>
    {!brief ? <p className="treatment-review__muted">{t("Not provided")}</p> : <>
      <dl className="treatment-review__brief-fields">
        {[...brief.values.map(value => ({ value, inherited: false })), ...brief.inherited_values.map(value => ({ value, inherited: true }))].map(({ value, inherited }, index) => (
          <div key={`${value.slot_id}-${index}`}>
            <dt>{BRIEF_LABELS[value.slot_id] ? t(BRIEF_LABELS[value.slot_id]) : value.slot_id.replaceAll("_", " ")}</dt>
            <dd>{value.value}<small>
              {t(({ fact: "Fact", assumption: "Assumption", constraint: "Constraint", preference: "Preference" } as const)[value.kind])}
              {" · "}{t(value.provenance === "user_confirmed" ? "User confirmed" : "Agent recommended")}
              {inherited ? ` · ${t("Inherited from brand profile")}` : ""}
            </small></dd>
          </div>
        ))}
      </dl>
      {brief.unresolved_fields.length > 0 && <p className="treatment-review__unresolved">{t("Unresolved: {items}. No defaults are added.", {
        items: brief.unresolved_fields.map(key => BRIEF_LABELS[key] ? t(BRIEF_LABELS[key]) : key).join("、"),
      })}</p>}
    </>}
  </section>;
}

export function TreatmentDocumentView({ document: doc, view = "overview", responseLocale = "en-US" }: {
  document: BrandTreatmentDocument; view?: "overview" | "foundation" | "execution"; responseLocale?: string;
}) {
  const t = useTranslation(responseLocale);
  const locale = useUiLocale(responseLocale);
  const selectedSkills = doc.skill_stack?.entries.filter(skill => skill.selected) ?? [];
  const otherSkills = doc.skill_stack?.entries.filter(skill => !skill.selected) ?? [];

  if (view === "overview") {
    const hypothesis = doc.selected_hypothesis;
    const details = hypothesis ? ([
      ["insight", "Insight"], ["mechanism", "Mechanism"], ["product_role", "Product role"],
      ["hook_mechanism", "Opening mechanism"], ["why", "Why"],
    ] as const).filter(([key]) => hypothesis[key]?.trim()) : [];
    if (doc.full_script) return <section className="treatment-review__creative-summary">
      <h3>{doc.full_script.title}</h3>{renderMarkdownAwareText(doc.full_script.screenplay)}
    </section>;
    return <>
      <section className="treatment-review__creative-summary">
        <p className="treatment-review__eyebrow">{t("Selected creative hypothesis")}</p>
        <h3>{hypothesis?.label || t("Treatment overview")}</h3>
        <p className="treatment-review__lead">{hypothesis?.hypothesis || t("Not provided")}</p>
        {details.length > 0 && <details className="treatment-review__disclosure">
          <summary>{t("Creative rationale")}<ChevronDownIcon /></summary>
          <dl className="treatment-review__rationale">
            {details.map(([key, label]) => <div key={key}><dt>{t(label)}</dt><dd>{hypothesis?.[key]}</dd></div>)}
          </dl>
        </details>}
      </section>
      {selectedSkills.length > 0 && <div className="treatment-review__selected-skills" aria-label={t("Selected skills")}>
        {selectedSkills.map(skill => <span key={`${skill.skill_kind}-${skill.skill_id}`}>
          <small>{t(skill.skill_kind === "creative_method" ? "Creative method" : "Audiovisual style")}</small>
          <strong>{skillDisplayTitle(skill, locale)}</strong>
        </span>)}
      </div>}
    </>;
  }

  if (view === "foundation") return <>
    <div className="treatment-review__page-heading"><p className="treatment-review__eyebrow">{t("Project context")}</p><h3>{t("Brand and campaign")}</h3><p>{t("The brief behind this creative direction.")}</p></div>
    <div className="treatment-review__brief-grid">
      <BriefView title={t("Brand profile")} brief={doc.brand_profile} responseLocale={responseLocale} />
      <BriefView title={t("Campaign requirements")} brief={doc.campaign_brief} responseLocale={responseLocale} />
    </div>
  </>;

  const renderSkill = (skill: typeof selectedSkills[number]) => <div className="treatment-review__skill" key={`${skill.skill_kind}-${skill.skill_id}`}>
    <div><span>{t(skill.skill_kind === "creative_method" ? "Creative method" : "Audiovisual style")}</span><small>{skill.version ? `v${skill.version}` : t("Version not provided")}</small></div>
    <h4>{skillDisplayTitle(skill, locale)}</h4>
    {skill.reason && <p>{skill.reason}</p>}
  </div>;

  return <>
    <div className="treatment-review__page-heading"><p className="treatment-review__eyebrow">{t("Production handoff")}</p><h3>{t("Production notes")}</h3><p>{t("Review the requirements, references and production scope.")}</p></div>
    <section className="treatment-review__document-section">
      <h3>{t("AdSpec")}</h3>
      {doc.adspec ? <div className="treatment-review__spec-groups">
        {(["locked", "open", "variable"] as const).map(state => {
          const items = doc.adspec!.items.filter(item => item.state === state);
          if (!items.length) return null;
          return <div key={state} className={`treatment-review__spec-group is-${state}`}>
            <h4>{state === "locked" && <ConfirmIcon />}{t(({ locked: "Locked", open: "To resolve", variable: "Creative freedom" } as const)[state])}<span>{items.length}</span></h4>
            <ul>{items.map(item => <li key={item.item_key}>{item.item_text}</li>)}</ul>
          </div>;
        })}
      </div> : <p className="treatment-review__muted">{t("Not provided")}</p>}
    </section>
    <section className="treatment-review__document-section">
      <h3>{t("Skills and versions")}</h3>
      <div className="treatment-review__skills-grid">{selectedSkills.map(renderSkill)}</div>
      {otherSkills.length > 0 && <details className="treatment-review__disclosure"><summary>{t("Other skill candidates")}<ChevronDownIcon /></summary><div className="treatment-review__skills-grid">{otherSkills.map(renderSkill)}</div></details>}
      {!doc.skill_stack?.entries.length && <p className="treatment-review__muted">{t("Not provided")}</p>}
    </section>
    <section className="treatment-review__document-section">
      <h3>{t("Product presentation")}</h3><div className="treatment-review__step-copy"><TreatmentSections detail={{ sections: doc.product_presentation }} /></div>
    </section>
    <section className="treatment-review__document-section">
      <h3>{t("Asset references")}</h3>
      {!doc.authorized_asset_references.length ? <p className="treatment-review__muted">{t("No asset references have been added.")}</p> : doc.authorized_asset_references.map(ref => (
        <details className="treatment-review__disclosure" key={ref.binding_id}>
          <summary><span><DocumentIcon />{ref.display_name}</span><ChevronDownIcon /></summary>
          <dl className="treatment-review__reference-details">
            <div><dt>{t("Input role")}</dt><dd>{ref.input_role}</dd></div>
            <div><dt>{t("Asset ID")}</dt><dd>{ref.asset_id}</dd></div>
            <div><dt>{t("Version ID")}</dt><dd>{ref.version_id}</dd></div>
            <div><dt>{t("Target node")}</dt><dd>{ref.target_node_id}</dd></div>
          </dl>
        </details>
      ))}
      {doc.authorized_asset_references.length > 0 && <p className="treatment-review__muted">{t("References only apply to this Workflow and target node; they are not linked automatically to other nodes.")}</p>}
    </section>
    {doc.execution_limitations.length > 0 && <section className="treatment-review__scope-note">
      <h3>{t("Execution limitations")}</h3>
      {doc.execution_limitations.map(item => <p key={item}>{item === "sound_effects_and_mixing_not_automated"
        ? t("Environmental sound, effects and music intent are retained; sound effects and mixing are not automated.") : item}</p>)}
    </section>}
  </>;
}
