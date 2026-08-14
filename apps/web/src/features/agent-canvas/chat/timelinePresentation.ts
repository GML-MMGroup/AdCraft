import type {
  ChatTimelineItemV2,
  ChatTimelinePresentationViewItemV2,
} from "../../../types-v2.ts";

type PresentationMessageKey =
  | "concept_proposal.review"
  | "planning_progress.next_action"
  | "expert_activity.working"
  | "expert_activity.completed"
  | "expert_activity.failed"
  | "draft.materialized"
  | "action.topic_deferred"
  | "action.element_excluded";

type PresentationTemplate = (
  args: Record<string, unknown>,
) => string | null;

const EN_MESSAGES: Record<PresentationMessageKey, PresentationTemplate> = {
  "concept_proposal.review": (args) => {
    const count = positiveIntegerArgument(args, "option_count");
    return count === null ? null : `Review ${count} option${count === 1 ? "" : "s"}.`;
  },
  "planning_progress.next_action": () => "Planning the next creative action.",
  "expert_activity.working": (args) => capabilityLabel(args, "is working."),
  "expert_activity.completed": (args) => capabilityLabel(args, "finished."),
  "expert_activity.failed": (args) => capabilityLabel(args, "failed."),
  "draft.materialized": (args) => {
    const count = positiveIntegerArgument(args, "created_node_count");
    return count === null ? null : `${count} Draft node${count === 1 ? "" : "s"} created.`;
  },
  "action.topic_deferred": () => "This topic was deferred.",
  "action.element_excluded": () => "This element was excluded.",
};

const ZH_MESSAGES: Record<PresentationMessageKey, PresentationTemplate> = {
  "concept_proposal.review": (args) => {
    const count = positiveIntegerArgument(args, "option_count");
    return count === null ? null : `请查看 ${count} 个方案。`;
  },
  "planning_progress.next_action": () => "正在规划下一项创作操作。",
  "expert_activity.working": (args) => capabilityLabel(args, "正在工作。"),
  "expert_activity.completed": (args) => capabilityLabel(args, "已完成。"),
  "expert_activity.failed": (args) => capabilityLabel(args, "失败。"),
  "draft.materialized": (args) => {
    const count = positiveIntegerArgument(args, "created_node_count");
    return count === null ? null : `已创建 ${count} 个草稿节点。`;
  },
  "action.topic_deferred": () => "该主题已暂缓处理。",
  "action.element_excluded": () => "该元素已排除。",
};

function positiveIntegerArgument(
  args: Record<string, unknown>,
  key: string,
): number | null {
  const value = args[key];
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : null;
}

function capabilityLabel(
  args: Record<string, unknown>,
  suffix: string,
): string | null {
  const label = args.capability_display_name;
  return typeof label === "string" && label.trim()
    ? `${label.trim()} ${suffix}`
    : null;
}

function localeMessages(locale: string): Record<PresentationMessageKey, PresentationTemplate> | null {
  const normalized = locale.toLocaleLowerCase();
  if (normalized === "en" || normalized.startsWith("en-")) return EN_MESSAGES;
  if (normalized === "zh" || normalized.startsWith("zh-")) return ZH_MESSAGES;
  return null;
}

function localizedMessage(item: ChatTimelinePresentationViewItemV2): string | null {
  if (!item.message_key) return null;
  const messages = localeMessages(item.response_locale);
  if (!messages) return null;
  const template = messages[item.message_key as PresentationMessageKey];
  return template ? template(item.message_args) : null;
}

function withLocalizedContent(
  item: ChatTimelineItemV2,
  content: string,
): ChatTimelineItemV2 {
  if (item.item_type === "message") return { ...item, text: content };
  if (item.item_type === "action_receipt") {
    return {
      ...item,
      action_receipt: {
        ...item.action_receipt,
        summary: content,
      },
    };
  }
  if (item.item_type === "expert_activity") {
    return {
      ...item,
      presentation_text: content,
    };
  }
  return item;
}

export function localizeTimelinePresentationItem(
  presentation: ChatTimelinePresentationViewItemV2,
): ChatTimelineItemV2 {
  const content = localizedMessage(presentation);
  return content ? withLocalizedContent(presentation.item, content) : presentation.item;
}

export function mergeTimelinePresentationItems(
  current: ReadonlyMap<string, ChatTimelinePresentationViewItemV2>,
  incoming: readonly ChatTimelinePresentationViewItemV2[],
): Map<string, ChatTimelinePresentationViewItemV2> {
  const merged = new Map(current);
  incoming.forEach((item) => {
    const previous = merged.get(item.presentation_key);
    if (!previous || item.presentation_revision > previous.presentation_revision) {
      merged.set(item.presentation_key, item);
    }
  });
  return merged;
}

export function visibleTimelinePresentationItems(
  items: ReadonlyMap<string, ChatTimelinePresentationViewItemV2>,
): ChatTimelineItemV2[] {
  return [...items.values()]
    .sort((left, right) => (
      left.item.sequence - right.item.sequence
      || left.presentation_key.localeCompare(right.presentation_key)
    ))
    .map(localizeTimelinePresentationItem);
}
