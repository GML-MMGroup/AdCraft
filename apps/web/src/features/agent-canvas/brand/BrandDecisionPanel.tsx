import { BrandDecisionContent } from "./BrandDecisionContent.tsx";
import { useId, useState } from "react";
import type {
  BrandDecisionPanelV1,
  BrandStageV2,
} from "./brandDecisions.ts";
import "./brand-decision-panel.css";

const STAGE_ORDER: BrandStageV2[] = [
  "brand-memory",
  "campaign",
  "hypothesis",
  "adspec",
  "skill-stack",
  "treatment",
  "production",
];

const STAGE_LABELS: Record<BrandStageV2, string> = {
  "brand-memory": "Brand Memory",
  campaign: "Campaign",
  hypothesis: "Hypothesis",
  adspec: "AdSpec",
  "skill-stack": "Skill Stack",
  treatment: "Treatment",
  production: "Production",
};

const STAGE_STATUS_LABELS: Record<
  BrandDecisionPanelV1["journey"]["stage_status"],
  string
> = {
  ready: "Ready",
  working: "Working",
  waiting_user: "Waiting for you",
  completed: "Completed",
};

function stageIndex(stage: BrandStageV2) {
  return STAGE_ORDER.indexOf(stage);
}

function stagePreview(decisions: BrandDecisionPanelV1, stage: BrandStageV2): string[] {
  const values = decisions.slot_values
    .filter((slot) => slot.stage === stage)
    .map((slot) => slot.value);
  if (values.length > 0) return values;
  if (stage === "hypothesis") {
    const selected = decisions.hypotheses.find(
      (candidate) => candidate.candidate_id === decisions.selected_hypothesis_id,
    );
    return selected ? [selected.label] : [];
  }
  if (stage === "adspec") return decisions.adspec?.items.map((item) => item.item_text) ?? [];
  if (stage === "skill-stack") {
    return decisions.skill_stack?.entries
      .filter((entry) => entry.selected)
      .map((entry) => entry.title) ?? [];
  }
  if (stage === "treatment") return decisions.treatment_steps.map((step) => step.selected_label);
  return decisions.open_card?.stage === stage ? [decisions.open_card.question] : [];
}

function BrandDecisionPanelContent({
  decisions,
  refreshing,
  onRefresh,
  onChooseSkills,
}: {
  decisions: BrandDecisionPanelV1;
  refreshing: boolean;
  onRefresh: () => void;
  onChooseSkills?: () => void;
}) {
  const [expandedStages, setExpandedStages] = useState<Partial<Record<BrandStageV2, boolean>>>({});
  const currentStageIndex = stageIndex(decisions.journey.stage);
  const panelId = useId();

  return (
    <aside className="brand-decision-panel" aria-label="Brand decision panel">
      <header className="brand-decision-panel__header">
        <div>
          <p className="brand-decision-panel__eyebrow">Brand decisions</p>
          <h2>{decisions.brand_name || "Brand project"}</h2>
          <p className="brand-decision-panel__stage">
            {STAGE_LABELS[decisions.journey.stage]}
            {" · "}
            {STAGE_STATUS_LABELS[decisions.journey.stage_status]}
            {decisions.journey.treatment_substep
              ? ` · ${decisions.journey.treatment_substep}`
              : ""}
          </p>
        </div>
        <button
          type="button"
          className="brand-decision-panel__refresh"
          onClick={onRefresh}
          disabled={refreshing}
        >
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </header>
      {decisions.treatment_locked ? (
        <p className="brand-decision-panel__locked" role="status">
          Treatment locked. Decisions are read-only.
        </p>
      ) : null}
      <div className="brand-decision-panel__sections">
        {STAGE_ORDER.map((stage) => {
          const stageSlots = decisions.slot_values.filter(slot => slot.stage === stage);
          const isCurrent = stage === decisions.journey.stage;
          const isCompleted = stageIndex(stage) < currentStageIndex;
          const expanded = expandedStages[stage] ?? isCurrent;
          const preview = stagePreview(decisions, stage);
          const hasContent =
            stageSlots.length > 0
            || (decisions.open_card?.stage === stage)
            || (stage === "hypothesis" && decisions.hypotheses.length > 0)
            || (stage === "adspec" && decisions.adspec !== null)
            || (stage === "skill-stack" && decisions.skill_stack !== null)
            || (stage === "treatment" && decisions.treatment_steps.length > 0);
          return (
            <section
              key={stage}
              className={`brand-decision-panel__section${isCurrent ? " is-current" : ""}`}
            >
              <button
                type="button"
                className="brand-decision-panel__section-toggle"
                aria-expanded={expanded}
                aria-controls={`${panelId}-${stage}`}
                onClick={() => setExpandedStages(current => ({ ...current, [stage]: !expanded }))}
              >
                <span className="brand-decision-panel__section-index" aria-hidden="true">
                  {String(stageIndex(stage) + 1).padStart(2, "0")}
                </span>
                <span>{STAGE_LABELS[stage]}</span>
                {isCurrent ? <span className="brand-decision-panel__tag">Now</span> : null}
                {!isCurrent && isCompleted ? <span className="brand-decision-panel__tag is-muted">Done</span> : null}
                <span className="brand-decision-panel__chevron" aria-hidden="true">{expanded ? "–" : "+"}</span>
              </button>
              {!expanded && preview.length > 0 ? (
                <div className="brand-decision-panel__section-preview" aria-label={`${STAGE_LABELS[stage]} summary`}>
                  {preview.slice(0, 2).map((value, index) => <span key={index}>{value}</span>)}
                  {preview.length > 2 ? <small>+{preview.length - 2} more</small> : null}
                </div>
              ) : null}
              <div id={`${panelId}-${stage}`} hidden={!expanded}>
                {expanded ? <div className="brand-decision-panel__section-body">
                  {!hasContent ? <p className="brand-decision-panel__empty">{stage === "production"
                    ? "Continue production on the canvas. Your creative brief is available above."
                    : "Decisions will appear here as you complete this stage in chat."}</p> : null}
                  <BrandDecisionContent decisions={decisions} stage={stage}/>
                  {stage === "skill-stack" && isCurrent && onChooseSkills ? (
                    <button type="button" className="brand-decision-panel__option"
                      disabled={refreshing || decisions.open_card?.stage !== "skill-stack"}
                      onClick={onChooseSkills}>Choose Skills</button>
                  ) : null}
                </div> : null}
              </div>
            </section>
          );
        })}
      </div>
    </aside>
  );
}

// Reset disclosure preferences only when navigating to a different workflow.
export function BrandDecisionPanel(props: Parameters<typeof BrandDecisionPanelContent>[0]) {
  return <BrandDecisionPanelContent key={props.decisions.workflow_id} {...props}/>;
}
