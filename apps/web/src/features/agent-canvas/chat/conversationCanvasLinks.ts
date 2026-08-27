import type {
  ChatActionReceiptCardV2,
  ChatArtifactCardV2,
  ChatMessageV2,
  ChatProposalCardV2,
  GuidanceAwaitingV1,
} from "../../../types-v2.ts";
import type { StageThreadUnit, StageTimelineUnit } from "./stageThreadProjection.ts";

export type ConversationCanvasLocationKind =
  | "stage_thread"
  | "message"
  | "artifact"
  | "receipt"
  | "proposal"
  | "guidance";

export interface ConversationCanvasLocation {
  key: string;
  kind: ConversationCanvasLocationKind;
  sequence: number;
  createdNodeIds: string[];
  updatedNodeIds: string[];
  deletedNodeIds: string[];
  relatedNodeIds: string[];
  navigableNodeIds: string[];
}

export interface ConversationCanvasLinkIndex {
  locations: Map<string, ConversationCanvasLocation>;
  sourceByNodeId: Map<string, ConversationCanvasLocation>;
}

export interface ConversationRevealRequest {
  locationKey: string;
  requestId: number;
}

interface ReverseSourceCandidate {
  location: ConversationCanvasLocation;
  priority: number;
  sequence: number;
}

interface MutableLocation {
  key: string;
  kind: ConversationCanvasLocationKind;
  sequence: number;
  createdNodeIds: string[];
  updatedNodeIds: string[];
  deletedNodeIds: string[];
  relatedNodeIds: string[];
}

function appendUnique(target: string[], values: readonly string[]) {
  for (const value of values) {
    if (value && !target.includes(value)) target.push(value);
  }
}

function messageNodeIds(message: ChatMessageV2): string[] {
  const result = [...message.linked_node_ids];
  if (message.script_node_id && !result.includes(message.script_node_id)) {
    result.push(message.script_node_id);
  }
  return result;
}

function proposalNodeIds(card: ChatProposalCardV2): string[] {
  return card.proposal.latest_application?.created_node_ids ?? [];
}

function addReceipt(location: MutableLocation, card: ChatActionReceiptCardV2) {
  appendUnique(location.createdNodeIds, card.action_receipt.created_node_ids);
  appendUnique(location.updatedNodeIds, card.action_receipt.updated_node_ids);
  appendUnique(location.deletedNodeIds, card.action_receipt.deleted_node_ids);
  location.sequence = Math.max(location.sequence, card.sequence);
}

function addMessage(location: MutableLocation, message: ChatMessageV2) {
  appendUnique(location.relatedNodeIds, messageNodeIds(message));
  location.sequence = Math.max(location.sequence, message.sequence);
}

function addArtifact(location: MutableLocation, artifact: ChatArtifactCardV2) {
  appendUnique(location.relatedNodeIds, [artifact.node_id]);
  location.sequence = Math.max(location.sequence, artifact.sequence);
}

function addProposal(location: MutableLocation, proposal: ChatProposalCardV2) {
  appendUnique(location.createdNodeIds, proposalNodeIds(proposal));
  location.sequence = Math.max(location.sequence, proposal.sequence);
}

function stageLocation(unit: StageThreadUnit): MutableLocation {
  const location: MutableLocation = {
    key: unit.key,
    kind: "stage_thread",
    sequence: unit.sequence,
    createdNodeIds: [],
    updatedNodeIds: [],
    deletedNodeIds: [],
    relatedNodeIds: [],
  };
  for (const receipt of unit.receipts) addReceipt(location, receipt);
  for (const proposal of unit.proposals) addProposal(location, proposal);
  for (const planning of unit.planning) addMessage(location, planning);
  return location;
}

function itemLocation(unit: Extract<StageTimelineUnit, { unit_type: "item" }>): MutableLocation | null {
  const item = unit.item;
  const location: MutableLocation = {
    key: unit.key,
    kind: item.item_type === "action_receipt" ? "receipt" : item.item_type as ConversationCanvasLocationKind,
    sequence: item.sequence,
    createdNodeIds: [],
    updatedNodeIds: [],
    deletedNodeIds: [],
    relatedNodeIds: [],
  };
  if (item.item_type === "message") addMessage(location, item);
  else if (item.item_type === "artifact") addArtifact(location, item);
  else if (item.item_type === "action_receipt") addReceipt(location, item);
  else if (item.item_type === "proposal") addProposal(location, item);
  else return null;
  return location;
}

function finalizeLocation(location: MutableLocation): ConversationCanvasLocation {
  const deleted = new Set(location.deletedNodeIds);
  const navigableNodeIds: string[] = [];
  appendUnique(navigableNodeIds, location.createdNodeIds);
  appendUnique(navigableNodeIds, location.updatedNodeIds);
  appendUnique(navigableNodeIds, location.relatedNodeIds);
  return {
    ...location,
    navigableNodeIds: navigableNodeIds.filter((nodeId) => !deleted.has(nodeId)),
  };
}

function sourceCandidates(
  unit: StageTimelineUnit,
  location: ConversationCanvasLocation,
): Array<{ nodeId: string; priority: number; sequence: number }> {
  const candidates: Array<{ nodeId: string; priority: number; sequence: number }> = [];
  const addReceiptCandidates = (card: ChatActionReceiptCardV2) => {
    for (const nodeId of card.action_receipt.created_node_ids) {
      candidates.push({ nodeId, priority: 400, sequence: card.sequence });
    }
    for (const nodeId of card.action_receipt.updated_node_ids) {
      candidates.push({ nodeId, priority: 300, sequence: card.sequence });
    }
  };
  if (unit.unit_type === "stage_thread") {
    for (const receipt of unit.receipts) addReceiptCandidates(receipt);
    for (const message of unit.planning) {
      for (const nodeId of messageNodeIds(message)) {
        candidates.push({ nodeId, priority: 200, sequence: message.sequence });
      }
    }
  } else if (unit.item.item_type === "action_receipt") {
    addReceiptCandidates(unit.item);
  } else if (unit.item.item_type === "message") {
    for (const nodeId of messageNodeIds(unit.item)) {
      candidates.push({ nodeId, priority: 200, sequence: unit.item.sequence });
    }
  } else if (unit.item.item_type === "artifact") {
    candidates.push({ nodeId: unit.item.node_id, priority: 100, sequence: unit.item.sequence });
  }
  return candidates.filter(({ nodeId }) => location.navigableNodeIds.includes(nodeId));
}

export function buildConversationCanvasLinkIndex(
  timeline: StageTimelineUnit[],
  guidanceAwaiting: GuidanceAwaitingV1 | null,
): ConversationCanvasLinkIndex {
  const locations = new Map<string, ConversationCanvasLocation>();
  const candidatesByNodeId = new Map<string, ReverseSourceCandidate>();

  for (const unit of timeline) {
    const mutable = unit.unit_type === "stage_thread" ? stageLocation(unit) : itemLocation(unit);
    if (!mutable) continue;
    const location = finalizeLocation(mutable);
    if (!location.createdNodeIds.length
      && !location.updatedNodeIds.length
      && !location.deletedNodeIds.length
      && !location.relatedNodeIds.length) continue;
    locations.set(location.key, location);
    for (const candidate of sourceCandidates(unit, location)) {
      const current = candidatesByNodeId.get(candidate.nodeId);
      if (!current
        || candidate.priority > current.priority
        || (candidate.priority === current.priority && candidate.sequence > current.sequence)) {
        candidatesByNodeId.set(candidate.nodeId, { location, ...candidate });
      }
    }
  }

  if (guidanceAwaiting?.node_ids.length) {
    const key = `guidance:${guidanceAwaiting.awaiting_id}`;
    locations.set(key, {
      key,
      kind: "guidance",
      sequence: Number.MAX_SAFE_INTEGER,
      createdNodeIds: [],
      updatedNodeIds: [],
      deletedNodeIds: [],
      relatedNodeIds: [...new Set(guidanceAwaiting.node_ids)],
      navigableNodeIds: [...new Set(guidanceAwaiting.node_ids)],
    });
  }

  return {
    locations,
    sourceByNodeId: new Map(
      [...candidatesByNodeId].map(([nodeId, candidate]) => [nodeId, candidate.location]),
    ),
  };
}

export function conversationLocationForNode(
  index: ConversationCanvasLinkIndex,
  nodeId: string,
): ConversationCanvasLocation | null {
  return index.sourceByNodeId.get(nodeId) ?? null;
}
