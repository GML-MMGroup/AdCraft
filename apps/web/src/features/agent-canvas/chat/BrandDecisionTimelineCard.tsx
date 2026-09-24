import type { BrandDecisionPanelV1, BrandStageV2 } from "../brand/brandDecisions.ts";

const STAGE_LABELS: Record<BrandStageV2, string> = {
  "brand-memory": "Brand Memory",
  campaign: "Campaign",
  hypothesis: "Hypothesis",
  adspec: "AdSpec",
  "skill-stack": "Skill Stack",
  treatment: "Treatment",
  production: "Production",
};

const STAGE_ORDER: BrandStageV2[] = [
  "brand-memory",
  "campaign",
  "hypothesis",
  "adspec",
  "skill-stack",
  "treatment",
];

const ADSPEC_STATE_LABELS = {
  locked: "Locked",
  open: "Open",
  variable: "Variable",
} as const;

function stageValues(decisions: BrandDecisionPanelV1, stage: BrandStageV2) {
  return decisions.slot_values.filter((slot) => slot.stage === stage);
}

function hasStageContent(decisions: BrandDecisionPanelV1, stage: BrandStageV2) {
  if (stageValues(decisions, stage).length > 0) return true;
  if (stage === "hypothesis") return Boolean(decisions.selected_hypothesis_id);
  if (stage === "adspec") return Boolean(decisions.adspec?.items.length);
  if (stage === "skill-stack") return Boolean(decisions.skill_stack?.entries.some((entry) => entry.selected));
  return stage === "treatment" && decisions.treatment_steps.length > 0;
}

export function BrandDecisionTimelineCard({
  decisions,
}: {
  decisions: BrandDecisionPanelV1;
}) {
  const selectedHypothesis = decisions.hypotheses.find(
    (candidate) => candidate.candidate_id === decisions.selected_hypothesis_id,
  );
  const selectedSkills = decisions.skill_stack?.entries.filter((entry) => entry.selected) ?? [];
  const visibleStages = STAGE_ORDER.filter((stage) => hasStageContent(decisions, stage));

  if (visibleStages.length === 0) return null;

  return (
    <article className="agent-chat__brand-decision-card" aria-label="Brand decisions">
      <header className="agent-chat__brand-decision-card-header">
        <div>
          <span>Brand decisions</span>
          <strong>{decisions.brand_name || "Brand project"}</strong>
        </div>
        <small>{decisions.treatment_locked ? "Locked" : "Confirmed so far"}</small>
      </header>
      <div className="agent-chat__brand-decision-card-body">
        {visibleStages.map((stage) => {
          const values = stageValues(decisions, stage);
          return (
            <section key={stage} className="agent-chat__brand-decision-stage">
              <h3>{STAGE_LABELS[stage]}</h3>
              {values.length > 0 ? (
                <ul>
                  {values.map((slot) => <li key={slot.slot_id}>{slot.value}</li>)}
                </ul>
              ) : null}
              {stage === "hypothesis" && selectedHypothesis ? (
                <div className="agent-chat__brand-decision-highlight">
                  <strong>{selectedHypothesis.label}</strong>
                  <p>{selectedHypothesis.insight}</p>
                </div>
              ) : null}
              {stage === "adspec" && decisions.adspec ? (
                <div className="agent-chat__brand-decision-adspec">
                  {(Object.keys(ADSPEC_STATE_LABELS) as Array<keyof typeof ADSPEC_STATE_LABELS>).map((state) => {
                    const items = decisions.adspec?.items.filter((item) => item.state === state) ?? [];
                    if (items.length === 0) return null;
                    return (
                      <div key={state}>
                        <small>{ADSPEC_STATE_LABELS[state]}</small>
                        <ul>{items.map((item) => <li key={item.item_key}>{item.item_text}</li>)}</ul>
                      </div>
                    );
                  })}
                </div>
              ) : null}
              {stage === "skill-stack" && selectedSkills.length > 0 ? (
                <ul>
                  {selectedSkills.map((entry) => <li key={entry.skill_id}>{entry.title}</li>)}
                </ul>
              ) : null}
              {stage === "treatment" ? (
                <ul>
                  {decisions.treatment_steps.map((step) => (
                    <li key={step.step_key}>
                      <strong>{step.step_key}</strong>: {step.selected_label}
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
          );
        })}
      </div>
    </article>
  );
}
