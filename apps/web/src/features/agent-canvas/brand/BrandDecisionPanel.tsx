import { useUiLocale } from "../../../i18n/locale.tsx";
import { skillDisplayTitle } from "../skills/skillDisplayCopy.ts";
import { useTranslation } from "../../../i18n/useTranslation";
import type { UiMessageKey } from "../../../i18n/uiMessages";
import { BrandDecisionContent } from "./BrandDecisionContent.tsx";
import { TREATMENT_STEP_LABELS } from "./treatmentStepLabels.ts";
import { BRAND_STAGE_LABELS as STAGE_LABELS } from "./brandStageLabels.ts";
import { DecisionChevron } from "./DecisionChevron.tsx";
import { BrandStageIcon } from "./BrandStageIcon.tsx";
import { BrandProjectName } from "./BrandProjectName.tsx";
import { useId, useState } from "react";
import type { PresentationStreamView } from "../runtime/useAgentCanvasPresentationStreams.ts";
import type {
  BrandDecisionPanelV1,
  BrandStageV2,
} from "./brandDecisions.ts";
import "./brand-decision-panel.css";

const STAGE_ORDER: BrandStageV2[] = [
  "brand-memory",
  "campaign",
  "skill-stack-early",
  "hypothesis",
  "adspec",
  "skill-stack",
  "treatment",
  "production",
];

const STAGE_STATUS_LABELS: Record<
  BrandDecisionPanelV1["journey"]["stage_status"],
  UiMessageKey
> = {
  ready: "Ready",
  working: "Working",
  waiting_user: "Waiting for you",
  completed: "Completed",
};

function stagePreview(decisions: BrandDecisionPanelV1, stage: BrandStageV2, locale: string): string[] {
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
  if ((stage === "skill-stack" || stage === "skill-stack-early")) {
    return decisions.skill_stack?.entries
      .filter((entry) => entry.selected)
      .map((entry) => skillDisplayTitle(entry, locale)) ?? [];
  }
  if (stage === "treatment") return decisions.treatment_steps.map((step) => step.selected_label);
  return decisions.open_card?.stage === stage ? [decisions.open_card.question] : [];
}

function BrandDecisionPanelContent({
  decisions,
  refreshing,
  onRefresh,
  onChooseSkills,
  presentationStreams = [],
  projectName,
  onRenameProject,
}: {
  decisions: BrandDecisionPanelV1;
  refreshing: boolean;
  onRefresh: () => void;
  onChooseSkills?: () => void;
  presentationStreams?: readonly PresentationStreamView[];
  projectName?: string;
  onRenameProject?: (projectId: string, name: string) => Promise<boolean>;
}) {
  const t = useTranslation();
  const locale = useUiLocale();
  const [expandedStages, setExpandedStages] = useState<Partial<Record<BrandStageV2, boolean>>>({});
  const earlyRoute = decisions.early_skills_confirmed
    || ["brand-memory", "campaign", "skill-stack-early"].includes(decisions.journey.stage);
  const stages = STAGE_ORDER.filter(stage => stage !== (earlyRoute ? "skill-stack" : "skill-stack-early"));
  // Route selection belongs to the next visible creative stage in the workbench.
  const currentStage = decisions.journey.stage === "creative-route"
    ? earlyRoute ? "treatment" : "skill-stack"
    : decisions.journey.stage;
  const stageIndex = (stage: BrandStageV2) => stages.indexOf(stage);
  const currentStageIndex = stageIndex(currentStage);
  const panelId = useId();
  const substep = decisions.journey.treatment_substep;
  const substepLabel = substep ? TREATMENT_STEP_LABELS[substep] : null;

  return (
    <aside className="brand-decision-panel" aria-label={t("Brand decision panel")}>
      <header className="brand-decision-panel__header">
        <div>
          <p className="brand-decision-panel__eyebrow">{t("Brand decisions")}</p>
          <BrandProjectName name={projectName || decisions.brand_name || t("Untitled Project")}
            onRename={onRenameProject ? (name) => onRenameProject(decisions.project_id, name) : undefined} />
          <div className="brand-decision-panel__stage">
            <span>{t(STAGE_LABELS[currentStage])}{substep ? ` · ${substepLabel ? t(substepLabel) : substep}` : ""}</span>
            <span className={`brand-decision-panel__status is-${decisions.journey.stage_status}`}>
              <i aria-hidden="true" />{t(STAGE_STATUS_LABELS[decisions.journey.stage_status])}
            </span>
          </div>
        </div>
        <button
          type="button"
          className="brand-decision-panel__refresh"
          onClick={onRefresh}
          disabled={refreshing}
          aria-label={t(refreshing ? "Refreshing…" : "Refresh")}
          title={t(refreshing ? "Refreshing…" : "Refresh")}
        >
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M19 8a7.5 7.5 0 1 0 .6 7M19 3v5h-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <div className="brand-decision-panel__progress">
          <div className="brand-decision-panel__progress-track" aria-hidden="true">
            {stages.map((stage, index) => <span key={stage} className={index < currentStageIndex || (index === currentStageIndex && decisions.journey.stage_status === "completed") ? "is-complete" : index === currentStageIndex ? "is-current" : undefined} />)}
          </div>
          <span aria-label={t("Stage {current} of {total}", { current: currentStageIndex + 1, total: stages.length })}>
            {String(currentStageIndex + 1).padStart(2, "0")} / {String(stages.length).padStart(2, "0")}
          </span>
        </div>
      </header>
      <div className="brand-decision-panel__sections">
        {stages.map((stage) => {
          const stageSlots = decisions.slot_values.filter(slot => slot.stage === stage);
          const isCurrent = stage === currentStage;
          const isCompleted = stageIndex(stage) < currentStageIndex || (isCurrent && decisions.journey.stage_status === "completed");
          const expanded = expandedStages[stage] ?? isCurrent;
          const preview = stagePreview(decisions, stage, locale);
          const hasContent =
            stageSlots.length > 0
            || (decisions.open_card?.stage === stage)
            || (stage === "hypothesis" && decisions.hypotheses.length > 0)
            || (stage === "adspec" && decisions.adspec !== null)
            || ((stage === "skill-stack" || stage === "skill-stack-early") && decisions.skill_stack !== null)
            || (stage === "treatment" && decisions.treatment_steps.length > 0);
          return (
            <section
              key={stage}
              className={`brand-decision-panel__section${isCurrent ? " is-current" : ""}${isCompleted ? " is-completed" : !isCurrent ? " is-upcoming" : ""}`}
            >
              <button
                type="button"
                className="brand-decision-panel__section-toggle"
                aria-expanded={expanded}
                aria-current={isCurrent ? "step" : undefined}
                aria-controls={`${panelId}-${stage}`}
                onClick={() => setExpandedStages(current => ({ ...current, [stage]: !expanded }))}
              >
                <span className="brand-decision-panel__section-title">
                  <BrandStageIcon stage={stage} />
                  <span>{t(STAGE_LABELS[stage])}</span>
                </span>
                <span className={`brand-decision-panel__tag${isCompleted ? " is-complete" : !isCurrent ? " is-muted" : ""}`}>
                  {isCompleted ? <span aria-hidden="true">✓ </span> : null}{t(isCompleted ? "Done" : isCurrent ? "Now" : "Upcoming")}
                </span>
                <DecisionChevron />
              </button>
              {!expanded && preview.length > 0 ? (
                <div className="brand-decision-panel__section-preview" aria-label={t("{stage} summary", { stage: t(STAGE_LABELS[stage]) })}>
                  {preview.slice(0, 2).map((value, index) => <span key={index}>{value}</span>)}
                  {preview.length > 2 ? <small>{t("+{count} more", { count: preview.length - 2 })}</small> : null}
                </div>
              ) : null}
              <div id={`${panelId}-${stage}`} hidden={!expanded}>
                {expanded ? <div className="brand-decision-panel__section-body">
                  {!hasContent ? <p className="brand-decision-panel__empty">{t(stage === "production"
                    ? "Continue production on the canvas. Your creative brief is available above."
                    : "Decisions will appear here as you complete this stage in chat.")}</p> : null}
                  <BrandDecisionContent decisions={decisions} stage={stage} presentationStreams={presentationStreams}/>
                  {(stage === "skill-stack" || stage === "skill-stack-early") && isCurrent && onChooseSkills ? (
                    <button type="button" className="brand-decision-panel__option"
                      disabled={refreshing || decisions.open_card?.stage !== stage}
                      onClick={onChooseSkills}>{t("Choose Skills")}</button>
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
