import type {
  AgentCapabilityIdV2,
  CanvasRuntimeEventV2,
  ChatExpertActivityV2,
  ChatTimelineItemV2,
} from "../../../types-v2.ts";

const CAPABILITY_IDS = new Set<AgentCapabilityIdV2>([
  "world_setting",
  "product_design",
  "prop_design",
  "character_design",
  "scene_design",
  "script_authoring",
  "storyboard_design",
  "video_direction",
  "bgm_direction",
  "quick_media",
]);

const EXPERT_ACTIVITY_EVENTS = new Set([
  "expert_activity_started",
  "expert_activity_completed",
  "expert_activity_failed",
]);

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function capabilityValue(payload: Record<string, unknown>): AgentCapabilityIdV2 | null {
  const value = stringValue(payload.capability_id);
  return CAPABILITY_IDS.has(value as AgentCapabilityIdV2)
    ? value as AgentCapabilityIdV2
    : null;
}

export function projectChatEvents(
  events: CanvasRuntimeEventV2[],
): ChatTimelineItemV2[] {
  const activities = new Map<string, ChatExpertActivityV2>();
  const latestSequenceByActivity = new Map<string, number>();

  events.forEach((event) => {
    const payload = event.payload ?? {};
    if (EXPERT_ACTIVITY_EVENTS.has(event.event_type)) {
      const capabilityId = capabilityValue(payload);
      const capabilityDisplayName = stringValue(payload.capability_display_name);
      const turnId = stringValue(payload.turn_id, event.turn_id ?? "");
      const operation = stringValue(payload.operation, "planning");
      if (!capabilityId || !capabilityDisplayName || !turnId) return;
      const key = stringValue(payload.activity_id, `${turnId}:${capabilityId}:${operation}`);
      const latestSequence = latestSequenceByActivity.get(key);
      if (latestSequence !== undefined && event.seq <= latestSequence) return;
      const previous = activities.get(key);
      const status: ChatExpertActivityV2["status"] = event.event_type === "expert_activity_completed"
        ? "completed"
        : event.event_type === "expert_activity_failed"
          ? "failed"
          : "working";
      if (previous && previous.status !== "working") return;
      latestSequenceByActivity.set(key, event.seq);
      activities.set(key, {
        item_type: "expert_activity",
        activity_id: key,
        turn_id: turnId,
        capability_id: capabilityId,
        capability_display_name: capabilityDisplayName,
        operation,
        status,
        sequence: previous?.sequence ?? event.seq,
        started_at: previous?.started_at ?? event.created_at,
        finished_at: status === "working" ? null : event.created_at,
        message: status === "failed" ? stringValue(payload.message, stringValue(payload.error_message)) || null : null,
        error_code: stringValue(payload.error_code) || null,
        elapsed_ms: typeof payload.elapsed_ms === "number" && payload.elapsed_ms >= 0
          ? Math.floor(payload.elapsed_ms)
          : null,
        attempt_stage: ["initial", "transport_retry", "structured_repair", "fallback"].includes(
          stringValue(payload.attempt_stage),
        )
          ? stringValue(payload.attempt_stage) as ChatExpertActivityV2["attempt_stage"]
          : null,
        retryable: payload.retryable === true,
        validation_paths: Array.isArray(payload.validation_paths)
          ? payload.validation_paths.filter((path): path is string => typeof path === "string")
          : [],
        operation_policy_id: stringValue(payload.operation_policy_id) || null,
        suggested_actions: Array.isArray(payload.suggested_actions)
          ? payload.suggested_actions.filter(
            (action): action is ChatExpertActivityV2["suggested_actions"][number] => (
              action === "retry" || action === "revise_request"
            ),
          )
          : [],
        completion_mode: payload.completion_mode === "deterministic_fallback"
          ? "deterministic_fallback"
          : null,
        warning_code: payload.warning_code === "specialist_materialization_fallback"
          ? "specialist_materialization_fallback"
          : null,
      });
    }
  });

  return [...activities.values()]
    .sort((left, right) => left.sequence - right.sequence);
}
