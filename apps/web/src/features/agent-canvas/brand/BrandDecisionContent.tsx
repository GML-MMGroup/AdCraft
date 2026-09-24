import type { ReactNode } from "react";
import type { BrandDecisionPanelV1, BrandHypothesisCandidateV1, BrandStageV2 } from "./brandDecisions.ts";
import { TreatmentSections } from "./TreatmentSections.tsx";

const SLOT_LABELS: Record<string, string> = {
  brand_name: "Brand name", brand_audience: "Audience", brand_tone: "Brand tone",
  brand_product_focus: "Product focus", brand_product_identity: "Product",
  campaign_aspect_ratio: "Format", campaign_duration: "Duration",
  campaign_goal: "Goal", campaign_platform: "Channel",
};
const HYPOTHESIS_FIELDS = [
  ["insight", "Insight"], ["mechanism", "Mechanism"], ["hypothesis", "Creative direction"],
  ["product_role", "Product role"], ["hook_mechanism", "Hook"], ["why", "Rationale"],
] as const;
const TREATMENT_ORDER = ["hook", "story", "character", "scene", "visual", "camera", "editing", "sound"] as const;

/** Native disclosures keep long copy reachable without hiding it behind a line clamp. */
function DecisionDetail({ title, label, children, open = false }: {
  title: string; label?: string; children: ReactNode; open?: boolean;
}) {
  return <details className="brand-decision-detail" open={open}>
    <summary>{label ? <small>{label}</small> : null}<span>{title}</span></summary>
    <div className="brand-decision-detail__body">{children}</div>
  </details>;
}

function HypothesisDetail({ candidate, selected }: { candidate: BrandHypothesisCandidateV1; selected: boolean }) {
  return <DecisionDetail title={candidate.label} label={selected ? "Selected direction" : "Alternative"} open={selected}>
    <dl className="brand-decision-fields">
      {HYPOTHESIS_FIELDS.map(([key, label]) => candidate[key] ? <div key={key}>
        <dt>{label}</dt><dd>{candidate[key]}</dd>
      </div> : null)}
    </dl>
  </DecisionDetail>;
}

export function BrandDecisionContent({ decisions, stage }: { decisions: BrandDecisionPanelV1; stage: BrandStageV2 }) {
  const slots = decisions.slot_values.filter(slot => slot.stage === stage);
  const card = decisions.open_card?.stage === stage ? decisions.open_card : null;
  const selected = decisions.hypotheses.find(candidate => candidate.candidate_id === decisions.selected_hypothesis_id);
  const alternatives = decisions.hypotheses.filter(candidate => candidate.candidate_id !== decisions.selected_hypothesis_id);
  return <>
    {slots.length ? <dl className="brand-decision-fields">
      {slots.map(slot => <div key={slot.slot_id}>
        <dt>{SLOT_LABELS[slot.slot_id] ?? slot.slot_id.replaceAll("_", " ")}</dt>
        <dd>{slot.value}{slot.provenance === "agent_recommended" ? <small className="brand-decision-source">Agent recommended</small> : null}</dd>
      </div>)}
    </dl> : null}
    {card ? <div className="brand-decision-pending">
      <p className="brand-decision-caption">Pending your choice</p><p>{card.question}</p>
      {card.options.map(option => <DecisionDetail key={option.option_id} title={option.label}>
        {option.why ? <p>{option.why}</p> : null}<TreatmentSections detail={option.detail}/>
      </DecisionDetail>)}
    </div> : null}
    {stage === "hypothesis" ? <>
      {selected ? <HypothesisDetail key={selected.candidate_id} candidate={selected} selected/> : null}
      {alternatives.length ? <DecisionDetail title={selected ? `Other directions (${alternatives.length})` : `Candidate directions (${alternatives.length})`}>
        {alternatives.map(candidate => <HypothesisDetail key={candidate.candidate_id} candidate={candidate} selected={false}/>)}
      </DecisionDetail> : null}
    </> : null}
    {stage === "adspec" && decisions.adspec ? <div className="brand-decision-spec">
      {(["locked", "open", "variable"] as const).map(state => {
        const items = decisions.adspec!.items.filter(item => item.state === state);
        if (!items.length) return null;
        return <section key={state}>
          <h3>{({ locked: "Locked", open: "To resolve", variable: "Creative freedom" })[state]} <small>{items.length}</small></h3>
          <ul>{items.map(item => <li key={item.item_key}>{item.item_text}</li>)}</ul>
        </section>;
      })}
    </div> : null}
    {stage === "skill-stack" && decisions.skill_stack ? <div className="brand-decision-skills">
      {(["creative_method", "audiovisual_style"] as const).map(kind => {
        const entries = decisions.skill_stack!.entries.filter(entry => entry.skill_kind === kind);
        if (!entries.length) return null;
        const chosen = entries.filter(entry => entry.selected);
        const other = entries.filter(entry => !entry.selected);
        const renderSkill = (entry: typeof entries[number]) => <DecisionDetail key={entry.skill_id} title={entry.title} label={entry.selected ? "Selected" : "Alternative"}>
          {entry.reason ? <p>{entry.reason}</p> : <p>No rationale provided.</p>}
        </DecisionDetail>;
        return <section key={kind}><h3>{kind === "creative_method" ? "Creative method" : "Audiovisual style"}</h3>
          {chosen.map(renderSkill)}
          {other.length ? <DecisionDetail title={`Other options (${other.length})`}>{other.map(renderSkill)}</DecisionDetail> : null}
        </section>;
      })}
    </div> : null}
    {stage === "treatment" ? <div className="brand-decision-treatment">
      {TREATMENT_ORDER.flatMap((key, index) => {
        const step = decisions.treatment_steps.find(item => item.step_key === key);
        return step ? [<DecisionDetail key={key} title={step.selected_label} label={`${String(index + 1).padStart(2, "0")} / ${key}`} open={decisions.journey.treatment_substep === key}>
          <TreatmentSections detail={step.structured_detail}/>
          {!step.structured_detail?.sections.length && step.detail ? <p>{step.detail}</p> : null}
        </DecisionDetail>] : [];
      })}
    </div> : null}
  </>;
}
