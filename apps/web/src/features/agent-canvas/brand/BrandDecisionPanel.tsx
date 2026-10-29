import { useTranslation } from "../../../i18n/useTranslation";
import type { UiMessageKey } from "../../../i18n/uiMessages";
import { BrandDecisionContent } from "./BrandDecisionContent.tsx";
import { DecisionChevron } from "./DecisionChevron.tsx";
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
  "hypothesis",
  "adspec",
  "skill-stack",
  "treatment",
  "production",
];

const STAGE_LABELS: Record<BrandStageV2, UiMessageKey> = {
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
  UiMessageKey
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
  presentationStreams = [],
}: {
  decisions: BrandDecisionPanelV1;
  refreshing: boolean;
  onRefresh: () => void;
  onChooseSkills?: () => void;
  presentationStreams?: readonly PresentationStreamView[];
}) {
  const t = useTranslation();
  const [expandedStages, setExpandedStages] = useState<Partial<Record<BrandStageV2, boolean>>>({});
  const currentStageIndex = stageIndex(decisions.journey.stage);
  const panelId = useId();

  return (
    <aside className="brand-decision-panel" aria-label={t("Brand decision panel")}>
      <header className="brand-decision-panel__header">
        <div>
          <p className="brand-decision-panel__eyebrow">{t("Brand decisions")}</p>
          <h2>{decisions.brand_name || t("Brand project")}</h2>
          <p className="brand-decision-panel__stage">
            {t(STAGE_LABELS[decisions.journey.stage])}
            {" · "}
            {t(STAGE_STATUS_LABELS[decisions.journey.stage_status])}
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
          {t(refreshing ? "Refreshing…" : "Refresh")}
        </button>
      </header>
      {decisions.treatment_locked ? (
        <p className="brand-decision-panel__locked" role="status">
          {t("Treatment locked. Decisions are read-only.")}
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
                <span className="brand-decision-panel__section-title">{t(STAGE_LABELS[stage])}</span>
                {isCurrent ? <span className="brand-decision-panel__tag">{t("Now")}</span> : null}
                {!isCurrent && isCompleted ? <span className="brand-decision-panel__tag is-muted">{t("Done")}</span> : null}
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
                  {stage === "skill-stack" && isCurrent && onChooseSkills ? (
                    <button type="button" className="brand-decision-panel__option"
                      disabled={refreshing || decisions.open_card?.stage !== "skill-stack"}
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
