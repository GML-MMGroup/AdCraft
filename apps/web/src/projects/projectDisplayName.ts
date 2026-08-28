import type {
  AgentCanvasChatViewTimelineV2,
  GuidedSessionStateV2,
} from "../types-v2.ts";

const PLACEHOLDER_PROJECT_NAMES = new Set([
  "untitled project",
  "new project",
]);

export function isPlaceholderProjectName(value: string): boolean {
  return PLACEHOLDER_PROJECT_NAMES.has(value.trim().toLocaleLowerCase());
}

export function firstUserMessageFromTimeline(
  timeline: AgentCanvasChatViewTimelineV2,
): string | null {
  const items = timeline.presentationItems?.map((entry) => entry.item) ?? timeline.items;
  const message = items.find((item) => (
    item.item_type === "message"
    && item.speaker === "user"
    && item.text.trim().length > 0
  ));
  return message?.item_type === "message" ? message.text.trim() : null;
}

export function goalSummaryFromCreativeSession(
  session: GuidedSessionStateV2,
): string | null {
  const summary = session.goal.summary.trim();
  return summary.length > 0 ? summary : null;
}

export function resolveProjectDisplayName({
  projectName,
  firstUserMessage,
  goalSummary,
}: {
  projectName: string;
  firstUserMessage?: string | null;
  goalSummary?: string | null;
}): string {
  const name = projectName.trim();
  if (name && !isPlaceholderProjectName(name)) return name;
  const request = firstUserMessage?.trim();
  if (request) return request;
  const summary = goalSummary?.trim();
  if (summary) return summary;
  return name || "Untitled Project";
}
