import type {
  CanvasRuntimeEventV2,
  ChatExpertActivityV2,
  ChatTimelineItemV2,
  SpecialistAgentNameV2,
} from "../../../types-v2.ts";

const SPECIALISTS = new Set<SpecialistAgentNameV2>([
  "script_writer",
  "product_designer",
  "prop_designer",
  "character_designer",
  "scene_designer",
  "storyboard_artist",
  "video_director",
  "bgm_director",
  "quick_media_agent",
]);

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function specialistValue(payload: Record<string, unknown>): SpecialistAgentNameV2 | null {
  const value = stringValue(payload.specialist, stringValue(payload.specialist_name));
  return SPECIALISTS.has(value as SpecialistAgentNameV2)
    ? value as SpecialistAgentNameV2
    : null;
}

function specialistLabel(specialist: SpecialistAgentNameV2): string {
  return specialist
    .split("_")
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

export function projectChatEvents(
  events: CanvasRuntimeEventV2[],
): ChatTimelineItemV2[] {
  const activities = new Map<string, ChatExpertActivityV2>();

  events.forEach((event) => {
    const payload = event.payload ?? {};
    if (event.event_type.startsWith("specialist_activity_")) {
      const specialist = specialistValue(payload);
      const turnId = stringValue(payload.turn_id);
      if (!specialist || !turnId) return;
      const key = stringValue(payload.activity_id, `${turnId}:${specialist}`);
      const previous = activities.get(key);
      const status = event.event_type.endsWith("_completed")
        ? "completed"
        : event.event_type.endsWith("_failed")
          ? "failed"
          : "working";
      activities.set(key, {
        item_type: "expert_activity",
        activity_id: key,
        turn_id: turnId,
        specialist,
        display_name: stringValue(
          payload.display_name,
          stringValue(payload.label, specialistLabel(specialist)),
        ),
        operation: stringValue(payload.operation, "planning"),
        status,
        sequence: previous?.sequence ?? event.seq,
        started_at: previous?.started_at ?? event.created_at,
        finished_at: status === "working" ? null : event.created_at,
      });
    }
  });

  return [...activities.values()]
    .sort((left, right) => left.sequence - right.sequence);
}
