import type {
  GuidedJourneyStageV2,
  GuidedSessionStateV2,
  JourneyElementDecisionV2,
} from "../../../types-v2.ts";

const PRODUCTION_STAGES: Array<{ stage: GuidedJourneyStageV2; label: string; documentOnly?: boolean }> = [
  { stage: "intake", label: "Intake" },
  { stage: "world_view", label: "World View" },
  { stage: "product", label: "Product" },
  { stage: "props", label: "Props" },
  { stage: "character", label: "Character" },
  { stage: "scene", label: "Scene" },
  { stage: "narrative_direction", label: "Narrative Direction", documentOnly: true },
  { stage: "style_lock", label: "Style Lock", documentOnly: true },
  { stage: "storyboard_plan", label: "Storyboard Plan", documentOnly: true },
  { stage: "storyboard_grids", label: "Storyboard Grids" },
  { stage: "videos", label: "Videos" },
  { stage: "bgm", label: "BGM" },
  { stage: "editing", label: "Editing" },
  { stage: "completed", label: "Completed" },
];

const STAGE_INDEX = new Map(PRODUCTION_STAGES.map(({ stage }, index) => [stage, index]));

function decisionLabel(decision: JourneyElementDecisionV2): string {
  return `${decision.element_kind.replaceAll("_", " ")} ${decision.occurrence_index}`;
}

export function GuidanceSessionProgress({ session }: { session: GuidedSessionStateV2 }) {
  const journey = session.journey;
  const currentStage = PRODUCTION_STAGES.find(({ stage }) => stage === journey.stage)!;
  const currentIndex = STAGE_INDEX.get(journey.stage) ?? 0;
  const activeDecision = journey.active_occurrence_id
    ? journey.decisions.find((decision) => decision.occurrence_id === journey.active_occurrence_id) ?? null
    : null;

  return (
    <section className="agent-chat__recipe" aria-label="Guidance progress">
      <header>
        <strong>{session.goal.summary}</strong>
        <span>{currentIndex + 1}/{PRODUCTION_STAGES.length}</span>
      </header>
      <div className="agent-chat__journey-stage" aria-current="step">
        <strong>{currentStage.label}</strong>
        <span>{journey.stage_status.replaceAll("_", " ")}</span>
        {currentStage.documentOnly ? <small>Read-only production document</small> : null}
      </div>
      {journey.decisions.length ? (
        <ol aria-label="Production decisions">
          {journey.decisions.map((decision) => (
            <li
              key={decision.decision_id}
              className={`is-${decision.outcome}${decision.occurrence_id === journey.active_occurrence_id ? " is-current" : ""}`}
            >
              <i aria-hidden="true" />
              <span>{decisionLabel(decision)}</span>
              <small>{decision.outcome}</small>
            </li>
          ))}
        </ol>
      ) : (
        <p>The agent is preparing the next creative decision.</p>
      )}
      <div className="agent-chat__completion" aria-label="Guidance completion">
        <span>Stage: {currentStage.label} · {journey.stage_status.replaceAll("_", " ")}</span>
        {activeDecision ? (
          <span>Current decision: {decisionLabel(activeDecision)} · {activeDecision.outcome}</span>
        ) : null}
        {session.creative_authority ? (
          <span>Direction: {session.creative_authority.authority === "user" ? "You" : "Director"}</span>
        ) : null}
        <span>Authoring: {session.completion.authoring.replaceAll("_", " ")}</span>
        <span>Delivery: {session.completion.delivery.replaceAll("_", " ")}</span>
      </div>
    </section>
  );
}
