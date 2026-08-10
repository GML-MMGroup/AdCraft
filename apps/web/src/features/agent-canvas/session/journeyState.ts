import type {
  GuidedJourneyStageV2,
  GuidedSessionStateV2,
} from "../../../types-v2.ts";

const JOURNEY_EVENTS = new Set([
  "journey_stage_started",
  "journey_stage_changed",
  "journey_stage_waiting_user",
  "journey_stage_failed",
]);

const JOURNEY_STAGES = new Set<GuidedJourneyStageV2>([
  "intake",
  "clarification",
  "world_setting",
  "foundation_design",
  "narrative_direction",
  "style_lock",
  "storyboard_plan",
  "storyboard_grids",
  "video_segments",
  "bgm",
  "editing_ready",
  "completed",
]);

export type JourneyEventProjectionV2 = {
  sessionRevision: number;
  stageRevision: number;
  stage: GuidedJourneyStageV2;
};

export function mergeGuidedSessionState(
  current: GuidedSessionStateV2 | null,
  candidate: GuidedSessionStateV2 | null,
): GuidedSessionStateV2 | null {
  if (!current || !candidate) return candidate ?? current;
  if (current.session_id !== candidate.session_id) return candidate;
  if (candidate.journey.stage_revision < current.journey.stage_revision) return current;
  if (
    candidate.journey.stage_revision === current.journey.stage_revision
    && candidate.revision < current.revision
  ) return current;
  return candidate;
}

export function journeyStageFromEvent(
  event: {
    event_type: string;
    payload: Record<string, unknown> | null;
  },
  current: GuidedSessionStateV2 | null,
): JourneyEventProjectionV2 | null {
  if (!JOURNEY_EVENTS.has(event.event_type) || !event.payload) return null;
  const { stage, stage_revision: rawStageRevision, session_revision: rawSessionRevision } = event.payload;
  if (
    typeof stage !== "string"
    || !JOURNEY_STAGES.has(stage as GuidedJourneyStageV2)
    || !Number.isInteger(rawStageRevision)
    || typeof rawStageRevision !== "number"
    || rawStageRevision < 1
    || !Number.isInteger(rawSessionRevision)
    || typeof rawSessionRevision !== "number"
    || rawSessionRevision < 1
  ) return null;
  if (
    current
    && (
      rawStageRevision < current.journey.stage_revision
      || (
        rawStageRevision === current.journey.stage_revision
        && rawSessionRevision < current.revision
      )
    )
  ) return null;
  return {
    sessionRevision: rawSessionRevision,
    stageRevision: rawStageRevision,
    stage: stage as GuidedJourneyStageV2,
  };
}
