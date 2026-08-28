import type {
  AgentCapabilityIdV2,
  CapabilityProposalOptionV2,
  ChatActionReceiptCardV2,
  ChatCapabilityActivityV2,
  ChatMessageV2,
  ChatProposalCardV2,
  ChatTimelineItemV2,
} from "../../../types-v2.ts";

export type StageThreadStatus = "working" | "waiting_user" | "completed" | "failed" | "superseded";

export interface StageThreadUnit {
  unit_type: "stage_thread";
  key: string;
  capability_id: AgentCapabilityIdV2;
  capability_display_name: string;
  sequence: number;
  status: StageThreadStatus;
  planning: ChatMessageV2[];
  activities: ChatCapabilityActivityV2[];
  proposals: ChatProposalCardV2[];
  receipts: ChatActionReceiptCardV2[];
  selected_option: CapabilityProposalOptionV2 | null;
  completed_activity_count: number;
}

export interface StageTimelineItemUnit {
  unit_type: "item";
  key: string;
  sequence: number;
  item: ChatTimelineItemV2;
}

export type StageTimelineUnit = StageThreadUnit | StageTimelineItemUnit;

export interface StageThreadProjectionOptions {
  showUnassociatedPlanning?: boolean;
}

interface StageThreadBuilder {
  capability_id: AgentCapabilityIdV2;
  capability_display_name: string;
  planning: ChatMessageV2[];
  activities: ChatCapabilityActivityV2[];
  proposals: ChatProposalCardV2[];
  receipts: ChatActionReceiptCardV2[];
}

const FAILED_RECEIPT_STATUSES = new Set([
  "applied_with_run_error",
  "not_applied",
  "rejected",
  "failed",
]);

function itemKey(item: ChatTimelineItemV2): string {
  switch (item.item_type) {
    case "message": return `message:${item.message_id}`;
    case "artifact": return `artifact:${item.artifact_id}`;
    case "proposal": return `proposal:${item.proposal.proposal_id}`;
    case "proposal_pointer": return `proposal-pointer:${item.proposal_id}`;
    case "expert_activity": return `activity:${item.activity_id}`;
    case "command_plan": return `command:${item.command_plan.plan_id}`;
    case "action_receipt": return `receipt:${item.action_receipt.receipt_id}`;
    case "agent_document": return `document:${item.document_id}:${item.revision}`;
    case "decision_bundle": return `decision:${item.decision_bundle.bundle_id}`;
    case "decision_bundle_pointer": return `decision-pointer:${item.bundle_id}`;
  }
}

function threadBuilder(
  builders: Map<AgentCapabilityIdV2, StageThreadBuilder>,
  capabilityId: AgentCapabilityIdV2,
  displayName: string,
): StageThreadBuilder {
  const existing = builders.get(capabilityId);
  if (existing) {
    if (!existing.capability_display_name && displayName) existing.capability_display_name = displayName;
    return existing;
  }
  const created: StageThreadBuilder = {
    capability_id: capabilityId,
    capability_display_name: displayName,
    planning: [],
    activities: [],
    proposals: [],
    receipts: [],
  };
  builders.set(capabilityId, created);
  return created;
}

function selectedOption(proposals: ChatProposalCardV2[]): CapabilityProposalOptionV2 | null {
  const applied = [...proposals]
    .sort((left, right) => right.sequence - left.sequence)
    .find(({ proposal }) => (
      proposal.latest_application !== null
      || proposal.materialization?.status === "completed"
    ));
  if (!applied) return null;
  const optionId = applied.proposal.latest_application?.option_id
    ?? applied.proposal.materialization?.option_id
    ?? null;
  return optionId
    ? applied.proposal.options.find((option) => option.option_id === optionId) ?? null
    : null;
}

function threadStatus(builder: StageThreadBuilder): StageThreadStatus {
  const candidates: Array<{ sequence: number; status: StageThreadStatus }> = [];
  for (const activity of builder.activities) {
    candidates.push({ sequence: activity.sequence, status: activity.status });
  }
  for (const card of builder.proposals) {
    const materialization = card.proposal.materialization;
    const status: StageThreadStatus = materialization?.status === "failed"
      ? "failed"
      : materialization?.status === "queued" || materialization?.status === "working"
        ? "working"
        : card.proposal.availability === "open"
          ? "waiting_user"
          : card.proposal.availability === "applied"
            ? "completed"
            : "superseded";
    candidates.push({ sequence: card.sequence, status });
  }
  for (const card of builder.receipts) {
    const status: StageThreadStatus = FAILED_RECEIPT_STATUSES.has(card.action_receipt.status)
      ? "failed"
      : card.action_receipt.status === "applied"
        ? "completed"
        : "superseded";
    candidates.push({ sequence: card.sequence, status });
  }
  candidates.sort((left, right) => right.sequence - left.sequence);
  return candidates[0]?.status ?? "superseded";
}

function latestDocuments(items: ChatTimelineItemV2[]): Set<ChatTimelineItemV2> {
  const latestById = new Map<string, Extract<ChatTimelineItemV2, { item_type: "agent_document" }>>();
  for (const item of items) {
    if (item.item_type !== "agent_document") continue;
    const current = latestById.get(item.document_id);
    if (!current || item.revision > current.revision) latestById.set(item.document_id, item);
  }
  return new Set(latestById.values());
}

export function buildStageThreadTimeline(
  items: ChatTimelineItemV2[],
  options: StageThreadProjectionOptions = {},
): StageTimelineUnit[] {
  const builders = new Map<AgentCapabilityIdV2, StageThreadBuilder>();
  const proposalCapabilities = new Map<string, { id: AgentCapabilityIdV2; name: string }>();
  const absorbedReceiptIds = new Set<string>();
  const latestDocumentItems = latestDocuments(items);

  for (const item of items) {
    if (item.item_type !== "proposal") continue;
    proposalCapabilities.set(item.proposal.proposal_id, {
      id: item.proposal.capability_id,
      name: item.proposal.capability_display_name,
    });
    if (item.proposal.latest_application?.receipt_id) {
      absorbedReceiptIds.add(item.proposal.latest_application.receipt_id);
    }
  }

  const standalone: StageTimelineItemUnit[] = [];
  let latestUnassociatedPlanning: ChatMessageV2 | null = null;
  for (const item of items) {
    if (item.item_type === "expert_activity") {
      threadBuilder(builders, item.capability_id, item.capability_display_name).activities.push(item);
      continue;
    }
    if (item.item_type === "proposal") {
      threadBuilder(
        builders,
        item.proposal.capability_id,
        item.proposal.capability_display_name,
      ).proposals.push(item);
      continue;
    }
    if (item.item_type === "action_receipt" && item.action_receipt.proposal_id) {
      const capability = proposalCapabilities.get(item.action_receipt.proposal_id);
      if (capability && absorbedReceiptIds.has(item.action_receipt.receipt_id)) {
        threadBuilder(builders, capability.id, capability.name).receipts.push(item);
        continue;
      }
    }
    if (item.item_type === "message" && item.message_kind === "planning_progress") {
      const capability = item.capability_id
        ? { id: item.capability_id, name: "" }
        : item.proposal_id
          ? proposalCapabilities.get(item.proposal_id)
          : undefined;
      if (capability) threadBuilder(builders, capability.id, capability.name).planning.push(item);
      else if (
        options.showUnassociatedPlanning
        && (!latestUnassociatedPlanning || item.sequence > latestUnassociatedPlanning.sequence)
      ) latestUnassociatedPlanning = item;
      continue;
    }
    if (item.item_type === "agent_document" && !latestDocumentItems.has(item)) continue;
    standalone.push({
      unit_type: "item",
      key: itemKey(item),
      sequence: item.sequence,
      item,
    });
  }
  if (latestUnassociatedPlanning) {
    standalone.push({
      unit_type: "item",
      key: itemKey(latestUnassociatedPlanning),
      sequence: latestUnassociatedPlanning.sequence,
      item: latestUnassociatedPlanning,
    });
  }

  const threads: StageThreadUnit[] = [...builders.values()].map((builder) => {
    builder.planning.sort((left, right) => left.sequence - right.sequence);
    builder.activities.sort((left, right) => left.sequence - right.sequence);
    builder.proposals.sort((left, right) => left.sequence - right.sequence);
    builder.receipts.sort((left, right) => left.sequence - right.sequence);
    const sequences = [
      ...builder.planning.map((item) => item.sequence),
      ...builder.activities.map((item) => item.sequence),
      ...builder.proposals.map((item) => item.sequence),
      ...builder.receipts.map((item) => item.sequence),
    ];
    return {
      unit_type: "stage_thread",
      key: `stage:${builder.capability_id}`,
      capability_id: builder.capability_id,
      capability_display_name: builder.capability_display_name || builder.capability_id.replaceAll("_", " "),
      sequence: Math.min(...sequences),
      status: threadStatus(builder),
      planning: builder.planning,
      activities: builder.activities,
      proposals: builder.proposals,
      receipts: builder.receipts,
      selected_option: selectedOption(builder.proposals),
      completed_activity_count: builder.activities.filter((activity) => activity.status === "completed").length,
    };
  });

  return [...standalone, ...threads].sort((left, right) => left.sequence - right.sequence);
}
