import type { GuidedJourneyStageV2, GuidedSessionStateV2 } from "../../../types-v2.ts";
import { CharacterOccurrenceProgress } from "./CharacterOccurrenceProgress.tsx";

const PRODUCTION_STAGES: Array<{ stage: GuidedJourneyStageV2; label: string }> = [
  { stage: "intake", label: "Intake" },
  { stage: "world_view", label: "World View" },
  { stage: "product", label: "Product" },
  { stage: "props", label: "Props" },
  { stage: "character", label: "Character" },
  { stage: "scene", label: "Scene" },
  { stage: "narrative_direction", label: "Narrative Direction" },
  { stage: "style_lock", label: "Style Lock" },
  { stage: "storyboard_plan", label: "Storyboard Plan" },
  { stage: "storyboard_grids", label: "Storyboard Grids" },
  { stage: "videos", label: "Videos" },
  { stage: "bgm", label: "BGM" },
  { stage: "editing", label: "Editing" },
  { stage: "completed", label: "Completed" },
];

const STAGE_INDEX = new Map(PRODUCTION_STAGES.map(({ stage }, index) => [stage, index]));

const PROGRESS_GROUPS: Array<{ label: string; stages: GuidedJourneyStageV2[] }> = [
  { label: "Creative", stages: ["world_view", "product", "props", "character", "scene"] },
  { label: "Storyboard", stages: ["narrative_direction", "style_lock", "storyboard_plan", "storyboard_grids"] },
  { label: "Delivery", stages: ["videos", "bgm", "editing"] },
];

function completedStages(
  stages: GuidedJourneyStageV2[],
  currentStage: GuidedJourneyStageV2,
  currentStatus: GuidedSessionStateV2["journey"]["stage_status"],
): number {
  if (currentStage === "completed") return stages.length;
  const currentIndex = STAGE_INDEX.get(currentStage) ?? 0;
  return stages.filter((stage) => {
    const stageIndex = STAGE_INDEX.get(stage) ?? 0;
    return stageIndex < currentIndex || (stageIndex === currentIndex && currentStatus === "completed");
  }).length;
}

export function GuidanceSessionProgress({ session }: { session: GuidedSessionStateV2 }) {
  const journey = session.journey;
  const currentStage = PRODUCTION_STAGES.find(({ stage }) => stage === journey.stage)!;
  const stageStatus = journey.stage === "completed"
    ? "Completed"
    : `${currentStage.label} · ${journey.stage_status.replaceAll("_", " ")}`;

  return (
    <section className="agent-chat__recipe agent-chat__recipe--compact" aria-label="Guidance progress">
      <header>
        <strong>{session.goal.summary}</strong>
        <span>{stageStatus}</span>
      </header>
      <div className="agent-chat__progress-groups" aria-label="Production progress">
        {PROGRESS_GROUPS.map((group) => (
          <span key={group.label}>
            {group.label} {completedStages(group.stages, journey.stage, journey.stage_status)}/{group.stages.length}
          </span>
        ))}
      </div>
      <CharacterOccurrenceProgress journey={journey} />
    </section>
  );
}
