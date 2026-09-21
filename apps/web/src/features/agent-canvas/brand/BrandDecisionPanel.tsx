import { useCallback, useMemo, useState } from "react";
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

const ADSPEC_COLUMNS: Array<{
  key: "locked" | "open" | "variable";
  label: string;
}> = [
  { key: "locked", label: "Locked" },
  { key: "open", label: "Open" },
  { key: "variable", label: "Variable" },
];

function stageIndex(stage: BrandStageV2) {
  return STAGE_ORDER.indexOf(stage);
}

export function BrandDecisionPanel({
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
  const [collapsedStages, setCollapsedStages] = useState<ReadonlySet<BrandStageV2>>(
    () => new Set(),
  );
  const currentStageIndex = stageIndex(decisions.journey.stage);

  const slotsByStage = useMemo(() => {
    const grouped = new Map<BrandStageV2, BrandDecisionPanelV1["slot_values"]>();
    for (const slot of decisions.slot_values) {
      const list = grouped.get(slot.stage) ?? [];
      list.push(slot);
      grouped.set(slot.stage, list);
    }
    return grouped;
  }, [decisions.slot_values]);

  const toggleStage = useCallback((stage: BrandStageV2) => {
    setCollapsedStages((current) => {
      const next = new Set(current);
      if (next.has(stage)) next.delete(stage);
      else next.add(stage);
      return next;
    });
  }, []);

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
          const stageSlots = slotsByStage.get(stage) ?? [];
          const isCurrent = stage === decisions.journey.stage;
          const isCompleted = stageIndex(stage) < currentStageIndex;
          const expanded = isCurrent || (isCompleted && !collapsedStages.has(stage));
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
                onClick={() => toggleStage(stage)}
              >
                <span>{STAGE_LABELS[stage]}</span>
                {isCurrent ? <span className="brand-decision-panel__tag">Now</span> : null}
                {!isCurrent && isCompleted ? <span className="brand-decision-panel__tag is-muted">Done</span> : null}
                <span className="brand-decision-panel__chevron" aria-hidden="true">{expanded ? "–" : "+"}</span>
              </button>
              {expanded ? (
                <div className="brand-decision-panel__section-body">
                  {!hasContent ? <p className="brand-decision-panel__empty">No decisions yet.</p> : null}
                  {stageSlots.length > 0 ? (
                    <ul className="brand-decision-panel__slots">
                      {stageSlots.map((slot) => (
                        <li key={slot.slot_id}>
                          <span className="brand-decision-panel__slot-value">{slot.value}</span>
                          {slot.provenance === "agent_recommended" ? (
                            <span className="brand-decision-panel__recommended">Agent recommended</span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {decisions.open_card && decisions.open_card.stage === stage ? (
                    <div className="brand-decision-panel__open-card">
                      <p>{decisions.open_card.question}</p>
                      <ul>
                        {decisions.open_card.options.map((option) => (
                          <li key={option.option_id}>
                            <details>
                              <summary>{option.label}</summary>
                              {option.why ? <p>{option.why}</p> : null}
                            </details>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {stage === "hypothesis" && decisions.hypotheses.length > 0 ? (
                    <ul className="brand-decision-panel__hypotheses">
                      {decisions.hypotheses.map((candidate) => (
                        <li
                          key={candidate.candidate_id}
                          className={candidate.candidate_id === decisions.selected_hypothesis_id ? "is-selected" : ""}
                        >
                          <strong>{candidate.label}</strong>
                          <p>{candidate.insight}</p>
                          {candidate.why ? <p className="brand-decision-panel__why">{candidate.why}</p> : null}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {stage === "adspec" && decisions.adspec ? (
                    <div className="brand-decision-panel__adspec">
                      {ADSPEC_COLUMNS.map((column) => (
                        <div key={column.key}>
                          <h3>{column.label}</h3>
                          <ul>
                            {decisions.adspec?.items
                              .filter((item) => item.state === column.key)
                              .map((item) => <li key={item.item_key}>{item.item_text}</li>)}
                          </ul>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {stage === "skill-stack" && decisions.skill_stack ? (
                    <div className="brand-decision-panel__skills">
                      {(["creative_method", "audiovisual_style"] as const).map((kind) => {
                        const entries = decisions.skill_stack?.entries.filter((entry) => entry.skill_kind === kind) ?? [];
                        if (entries.length === 0) return null;
                        return (
                          <div key={kind}>
                            <h3>{kind === "creative_method" ? "Creative method" : "Audiovisual style"}</h3>
                            <ul>
                              {entries.map((entry) => (
                                <li key={entry.skill_id}>
                                  <span aria-hidden="true">{entry.selected ? "☑" : "☐"}</span>
                                  {entry.title}
                                  {entry.reason ? <p className="brand-decision-panel__option-why">{entry.reason}</p> : null}
                                </li>
                              ))}
                            </ul>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                  {stage === "skill-stack" && isCurrent && onChooseSkills ? (
                    <button type="button" className="brand-decision-panel__option"
                      disabled={refreshing || decisions.open_card?.stage !== "skill-stack"}
                      onClick={onChooseSkills}>选择 Skills / Choose Skills</button>
                  ) : null}
                  {stage === "treatment" && decisions.treatment_steps.length > 0 ? (
                    <>
                      <ul className="brand-decision-panel__treatment">
                        {decisions.treatment_steps.map((step) => (
                          <li key={step.step_key}>
                            <strong>{step.step_key}</strong>
                            <span>{step.selected_label}</span>
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                </div>
              ) : null}
            </section>
          );
        })}
      </div>
    </aside>
  );
}
