import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { v2Api, V2ApiError } from "../../../api/v2Client.ts";
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
  interactive = true,
}: {
  decisions: BrandDecisionPanelV1;
  refreshing: boolean;
  onRefresh: () => void;
  interactive?: boolean;
}) {
  const [collapsedStages, setCollapsedStages] = useState<ReadonlySet<BrandStageV2>>(
    () => new Set(),
  );
  const [activeCard, setActiveCard] = useState<BrandDecisionPanelV1["open_card"]>(null);
  const [cardLoading, setCardLoading] = useState(false);
  const [cardError, setCardError] = useState<string | null>(null);
  const [pendingOptionId, setPendingOptionId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [locking, setLocking] = useState(false);
  const loadedQuestionKeyRef = useRef<string | null>(null);

  const currentStageIndex = stageIndex(decisions.journey.stage);
  const questionFlowActive = interactive && !decisions.treatment_locked
    && decisions.journey.stage !== "production";

  const loadNextQuestion = useCallback(async () => {
    if (!interactive) return;
    setCardLoading(true);
    setCardError(null);
    try {
      const card = await v2Api.brandNextQuestion(decisions.workflow_id);
      loadedQuestionKeyRef.current = `${card.stage}:${card.stage_revision}`;
      setActiveCard(card);
    } catch {
      loadedQuestionKeyRef.current = null;
      setActiveCard(null);
      setCardError("Could not load the next question. Use retry to fetch a fresh card.");
    } finally {
      setCardLoading(false);
    }
  }, [decisions.workflow_id, interactive]);

  useEffect(() => {
    if (!questionFlowActive) {
      loadedQuestionKeyRef.current = null;
      setActiveCard(null);
      setCardError(null);
      return undefined;
    }
    const key = `${decisions.journey.stage}:${decisions.journey.stage_revision}`;
    if (loadedQuestionKeyRef.current === key) return undefined;
    void loadNextQuestion();
    return undefined;
  }, [
    decisions.journey.stage,
    decisions.journey.stage_revision,
    loadNextQuestion,
    questionFlowActive,
  ]);

  const handleOptionSelect = useCallback(async (optionId: string, label: string) => {
    if (!activeCard) return;
    setPendingOptionId(optionId);
    setActionError(null);
    try {
      if (activeCard.stage === "hypothesis") {
        await v2Api.brandSelectHypothesis(decisions.workflow_id, optionId);
      } else if (activeCard.stage === "treatment") {
        await v2Api.brandSelectTreatment(decisions.workflow_id, {
          card_id: activeCard.card_id,
          option_id: optionId,
          selected_label: label,
          detail: "",
        });
      } else {
        await v2Api.brandSelectSlot(decisions.workflow_id, {
          card_id: activeCard.card_id,
          option_id: optionId,
          value_text: label,
          provenance: "user_confirmed",
        });
      }
      loadedQuestionKeyRef.current = null;
      setActiveCard(null);
      onRefresh();
    } catch (error) {
      if (error instanceof V2ApiError && error.status === 409) {
        setActionError("This question expired. Loading the latest card.");
        loadedQuestionKeyRef.current = null;
        setActiveCard(null);
        void loadNextQuestion();
      } else {
        setActionError(error instanceof Error ? error.message : "Selection failed. Try again.");
      }
    } finally {
      setPendingOptionId(null);
    }
  }, [activeCard, decisions.workflow_id, loadNextQuestion, onRefresh]);

  const handleLockTreatment = useCallback(async () => {
    setLocking(true);
    setActionError(null);
    try {
      await v2Api.brandLockTreatment(decisions.workflow_id);
      loadedQuestionKeyRef.current = null;
      setActiveCard(null);
      onRefresh();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Locking treatment failed. Try again.");
    } finally {
      setLocking(false);
    }
  }, [decisions.workflow_id, onRefresh]);

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
      {actionError ? (
        <p className="brand-decision-panel__action-error" role="alert">{actionError}</p>
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
                  {questionFlowActive && activeCard && activeCard.stage === stage ? (
                    <div className="brand-decision-panel__open-card">
                      <p>{activeCard.question}</p>
                      <ul>
                        {activeCard.options.map((option) => (
                          <li key={option.option_id}>
                            <button
                              type="button"
                              className="brand-decision-panel__option"
                              disabled={pendingOptionId !== null}
                              onClick={() => {
                                void handleOptionSelect(option.option_id, option.label);
                              }}
                            >
                              {pendingOptionId === option.option_id ? "Submitting…" : option.label}
                            </button>
                            {option.why ? <p className="brand-decision-panel__option-why">{option.why}</p> : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : questionFlowActive && cardLoading && stage === decisions.journey.stage ? (
                    <p className="brand-decision-panel__empty">Loading question…</p>
                  ) : questionFlowActive && cardError && stage === decisions.journey.stage ? (
                    <div>
                      <p className="brand-decision-panel__empty">{cardError}</p>
                      <button
                        type="button"
                        className="brand-decision-panel__option"
                        onClick={() => {
                          void loadNextQuestion();
                        }}
                      >
                        Retry
                      </button>
                    </div>
                  ) : !questionFlowActive && decisions.open_card && decisions.open_card.stage === stage ? (
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
                                </li>
                              ))}
                            </ul>
                          </div>
                        );
                      })}
                    </div>
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
                      {questionFlowActive && decisions.treatment_steps.length >= 8 ? (
                        <button
                          type="button"
                          className="brand-decision-panel__option brand-decision-panel__lock"
                          disabled={locking || pendingOptionId !== null}
                          onClick={() => {
                            void handleLockTreatment();
                          }}
                        >
                          {locking ? "Locking…" : "Lock treatment"}
                        </button>
                      ) : null}
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
