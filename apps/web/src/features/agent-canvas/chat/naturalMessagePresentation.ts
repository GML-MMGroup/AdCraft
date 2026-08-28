import type { ChatTimelineItemV2 } from "../../../types-v2.ts";

export interface NaturalMessagePresentation {
  messageId: string;
  showAgentIdentity: boolean;
  startsSpeakerRun: boolean;
}

export function projectNaturalMessagePresentation(
  items: ChatTimelineItemV2[],
): Map<string, NaturalMessagePresentation> {
  const projected = new Map<string, NaturalMessagePresentation>();
  let previousSpeaker: "user" | "adcraft_video_agent" | null = null;

  items.forEach((item) => {
    if (item.item_type !== "message") {
      previousSpeaker = null;
      return;
    }
    const startsSpeakerRun = previousSpeaker !== item.speaker;
    projected.set(item.message_id, {
      messageId: item.message_id,
      showAgentIdentity: item.speaker === "adcraft_video_agent" && startsSpeakerRun,
      startsSpeakerRun,
    });
    previousSpeaker = item.speaker;
  });

  return projected;
}
