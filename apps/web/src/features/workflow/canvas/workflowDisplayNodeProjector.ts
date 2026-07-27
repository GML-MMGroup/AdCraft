import type {
  AssetVersionV2,
  WorkflowItemV2,
  WorkflowRuntimeV2,
  WorkflowSlotV2,
} from "../../../types-v2.ts";
import { nodeStatusWithExecution } from "../../../workflow/executionRuntime.ts";
import { isUserVisibleWorkflowNode } from "../../../workflow/visibility.ts";
import type { CanvasNode, WorkflowNodeData } from "../types.ts";
import {
  createWorkflowAssetIndex,
  type WorkflowAssetIndex,
} from "./workflowAssetIndex.ts";

type CandidateSummary = {
  candidateCount?: number;
  warningCount?: number;
  pendingVisibleCandidateCount?: number;
};

export type WorkflowDisplayNodeCallbacks = Pick<
  WorkflowNodeData,
  | "onOpenMedia"
  | "onSelectDynamicItem"
  | "onOpenScreenplay"
  | "onOpenV2SlotEditor"
  | "onOpenV2StoryboardPrompt"
  | "onOpenV2StoryboardVideoPreview"
  | "onChangeV2SlotPrompt"
  | "onChangeV2SlotNegativePrompt"
  | "onUploadV2SlotReference"
  | "onSelectV2SlotLibraryReference"
  | "onRemoveV2SlotReference"
  | "onOpenV2SlotAssetLibraryReplace"
  | "onOpenV2SlotAssetLibrarySave"
  | "onSaveV2ItemPrompt"
  | "onSubmitV2SlotPrompt"
  | "onSelectV2SlotVersion"
  | "onDiscardV2SlotWorkingVersion"
  | "onLoadV2SlotVersions"
>;

export type WorkflowDisplayNodeProjectionInput = {
  flowNodes: CanvasNode[];
  effectiveNodeStatusById: Record<string, string>;
  candidateSummaryByNodeId: Record<string, CandidateSummary | undefined>;
  activeProjectId?: string | null;
  workflowId?: string | null;
  dynamicItemRunningByNodeId: Record<string, WorkflowNodeData["runningDynamicItemById"]>;
  v2AssetVersions: AssetVersionV2[];
  slotVersionAssets: AssetVersionV2[];
  v2Runtime?: WorkflowRuntimeV2;
  v2FallbackRuntime?: WorkflowRuntimeV2;
  v2AudioMode?: string | null;
  v2SlotRuntimeStatusById: Record<string, string>;
  activeV2SlotId?: string | null;
  activeV2StoryboardItemId?: string | null;
  v2SlotDraftsById: NonNullable<WorkflowNodeData["v2SlotDraftsById"]>;
  v2ReferenceAssetsBySlotId: NonNullable<WorkflowNodeData["v2ReferenceAssetsBySlotId"]>;
  v2LibraryReferenceOptions: NonNullable<WorkflowNodeData["v2LibraryReferenceOptions"]>;
  callbacks: WorkflowDisplayNodeCallbacks;
};

type DisplayNodeCacheEntry = {
  sourceNode: CanvasNode;
  status: string;
  candidateCount: number;
  candidateWarningCount: number;
  pendingVisibleCandidateCount: number;
  projectId?: string | null;
  workflowId?: string | null;
  runningDynamicItemById?: WorkflowNodeData["runningDynamicItemById"];
  assets: AssetVersionV2[];
  runtime?: WorkflowRuntimeV2;
  runtimeSignature: string;
  audioMode?: string | null;
  slotRuntimeStatusById: Record<string, string>;
  openSlotId: string | null;
  openStoryboardItemId: string | null;
  slotDraftsById: NonNullable<WorkflowNodeData["v2SlotDraftsById"]>;
  referenceAssetsBySlotId: NonNullable<WorkflowNodeData["v2ReferenceAssetsBySlotId"]>;
  libraryReferenceOptions: NonNullable<WorkflowNodeData["v2LibraryReferenceOptions"]>;
  callbacks: WorkflowDisplayNodeCallbacks;
  result: CanvasNode;
};

const RUNTIME_MEMBERSHIP_KEYS = [
  "running_slot_ids",
  "running_item_ids",
  "running_node_ids",
  "waiting_slot_ids",
  "waiting_item_ids",
  "waiting_node_ids",
  "failed_slot_ids",
  "failed_item_ids",
  "failed_node_ids",
  "completed_slot_ids",
  "completed_item_ids",
  "completed_node_ids",
  "blocked_slot_ids",
  "blocked_item_ids",
  "blocked_node_ids",
  "skipped_slot_ids",
  "skipped_item_ids",
  "skipped_node_ids",
] as const;

type RuntimeMembershipKey = typeof RUNTIME_MEMBERSHIP_KEYS[number];
type WorkflowRuntimeMembershipIndex = {
  runtime: WorkflowRuntimeV2;
  memberships: Record<RuntimeMembershipKey, ReadonlySet<string>>;
  scopeByNodeId: Map<string, {
    items: readonly WorkflowItemV2[];
    slots: readonly WorkflowSlotV2[];
    result: { runtime: WorkflowRuntimeV2 | undefined; signature: string };
  }>;
};

export type WorkflowDisplayNodeProjector = {
  project: (input: WorkflowDisplayNodeProjectionInput) => CanvasNode[];
};

const EMPTY_RECORD: Record<string, never> = {};
const EMPTY_ASSET_LIST: AssetVersionV2[] = [];
const EMPTY_ITEMS: WorkflowItemV2[] = [];
const EMPTY_SLOTS: WorkflowSlotV2[] = [];
const EMPTY_LIBRARY_OPTIONS: NonNullable<WorkflowNodeData["v2LibraryReferenceOptions"]> = [];

export function createWorkflowDisplayNodeProjector(): WorkflowDisplayNodeProjector {
  let workflowAssets: AssetVersionV2[] | null = null;
  let slotAssets: AssetVersionV2[] | null = null;
  let assetIndex: WorkflowAssetIndex | null = null;
  let runtimeIndex: WorkflowRuntimeMembershipIndex | undefined;
  let cache = new Map<string, DisplayNodeCacheEntry>();

  return {
    project(input) {
      if (
        !assetIndex
        || workflowAssets !== input.v2AssetVersions
        || slotAssets !== input.slotVersionAssets
      ) {
        workflowAssets = input.v2AssetVersions;
        slotAssets = input.slotVersionAssets;
        assetIndex = createWorkflowAssetIndex(workflowAssets, slotAssets);
      }

      const nextCache = new Map<string, DisplayNodeCacheEntry>();
      const sourceRuntime = input.v2Runtime ?? input.v2FallbackRuntime;
      if (runtimeIndex?.runtime !== sourceRuntime) {
        runtimeIndex = sourceRuntime
          ? createWorkflowRuntimeMembershipIndex(sourceRuntime)
          : undefined;
      }
      const displayNodes = input.flowNodes
        .filter((node) => isUserVisibleWorkflowNode({ id: node.id, node_type: node.data.kind }))
        .map((node) => {
          const previous = cache.get(node.id);
          const summary = input.candidateSummaryByNodeId[node.id];
          const status = nodeStatusWithExecution(
            node.id,
            node.data.status,
            input.effectiveNodeStatusById,
          );
          const slots = node.data.v2Slots ?? EMPTY_SLOTS;
          const items = node.data.v2Items ?? EMPTY_ITEMS;
          const slotIds = slots.map((slot) => slot.slot_id);
          const itemIds = items.map((item) => item.item_id);
          const assets = assetIndex!.assetsForNode({
            nodeId: node.id,
            items,
            slots,
            localAssets: node.data.v2AssetVersions ?? EMPTY_ASSET_LIST,
          });
          const slotRuntimeStatusById = scopeRecord(
            input.v2SlotRuntimeStatusById,
            slotIds,
            previous?.slotRuntimeStatusById,
          );
          const slotDraftsById = scopeRecord(
            input.v2SlotDraftsById,
            slotIds,
            previous?.slotDraftsById,
          );
          const referenceAssetsBySlotId = scopeRecord(
            input.v2ReferenceAssetsBySlotId,
            slotIds,
            previous?.referenceAssetsBySlotId,
          );
          const openSlotId = input.activeV2SlotId
            && slotIds.includes(input.activeV2SlotId)
            ? input.activeV2SlotId
            : null;
          const openStoryboardItemId = input.activeV2StoryboardItemId
            && itemIds.includes(input.activeV2StoryboardItemId)
            ? input.activeV2StoryboardItemId
            : null;
          const libraryReferenceOptions = openSlotId
            ? input.v2LibraryReferenceOptions
            : EMPTY_LIBRARY_OPTIONS;
          const candidateCount = summary?.candidateCount ?? 0;
          const candidateWarningCount = summary?.warningCount ?? 0;
          const pendingVisibleCandidateCount = summary?.pendingVisibleCandidateCount ?? 0;
          const scopedRuntime = scopeWorkflowRuntime(
            runtimeIndex,
            node.id,
            items,
            slots,
            itemIds,
            slotIds,
            previous?.runtime,
            previous?.runtimeSignature,
          );
          const runtime = scopedRuntime.runtime;
          const runningDynamicItemById = input.dynamicItemRunningByNodeId[node.id];

          if (
            previous
            && previous.sourceNode === node
            && previous.status === status
            && previous.candidateCount === candidateCount
            && previous.candidateWarningCount === candidateWarningCount
            && previous.pendingVisibleCandidateCount === pendingVisibleCandidateCount
            && previous.projectId === input.activeProjectId
            && previous.workflowId === input.workflowId
            && previous.runningDynamicItemById === runningDynamicItemById
            && previous.assets === assets
            && previous.runtime === runtime
            && previous.audioMode === input.v2AudioMode
            && previous.slotRuntimeStatusById === slotRuntimeStatusById
            && previous.openSlotId === openSlotId
            && previous.openStoryboardItemId === openStoryboardItemId
            && previous.slotDraftsById === slotDraftsById
            && previous.referenceAssetsBySlotId === referenceAssetsBySlotId
            && previous.libraryReferenceOptions === libraryReferenceOptions
            && previous.callbacks === input.callbacks
          ) {
            nextCache.set(node.id, previous);
            return previous.result;
          }

          const result: CanvasNode = {
            ...node,
            data: {
              ...node.data,
              status,
              candidateCount,
              candidateWarningCount,
              pendingVisibleCandidateCount,
              ...input.callbacks,
              projectId: input.activeProjectId,
              workflowId: input.workflowId,
              runningDynamicItemById,
              v2AssetVersions: assets,
              v2Runtime: runtime,
              v2AudioMode: input.v2AudioMode,
              v2SlotRuntimeStatusById: slotRuntimeStatusById,
              v2OpenSlotId: openSlotId,
              v2OpenStoryboardItemId: openStoryboardItemId,
              v2SlotDraftsById: slotDraftsById,
              v2ReferenceAssetsBySlotId: referenceAssetsBySlotId,
              v2LibraryReferenceOptions: libraryReferenceOptions,
            },
          };
          nextCache.set(node.id, {
            sourceNode: node,
            status,
            candidateCount,
            candidateWarningCount,
            pendingVisibleCandidateCount,
            projectId: input.activeProjectId,
            workflowId: input.workflowId,
            runningDynamicItemById,
            assets,
            runtime,
            runtimeSignature: scopedRuntime.signature,
            audioMode: input.v2AudioMode,
            slotRuntimeStatusById,
            openSlotId,
            openStoryboardItemId,
            slotDraftsById,
            referenceAssetsBySlotId,
            libraryReferenceOptions,
            callbacks: input.callbacks,
            result,
          });
          return result;
        });

      cache = nextCache;
      return displayNodes;
    },
  };
}

function scopeRecord<T>(
  source: Record<string, T>,
  keys: string[],
  previous: Record<string, T> | undefined,
): Record<string, T> {
  if (!keys.length) return EMPTY_RECORD;
  const next: Record<string, T> = {};
  for (const key of keys) {
    if (source[key] !== undefined) next[key] = source[key];
  }
  if (
    previous
    && Object.keys(previous).length === Object.keys(next).length
    && Object.keys(next).every((key) => Object.is(previous[key], next[key]))
  ) {
    return previous;
  }
  return next;
}

function scopeWorkflowRuntime(
  runtimeIndex: WorkflowRuntimeMembershipIndex | undefined,
  nodeId: string,
  items: readonly WorkflowItemV2[],
  slots: readonly WorkflowSlotV2[],
  itemIds: string[],
  slotIds: string[],
  previous: WorkflowRuntimeV2 | undefined,
  previousSignature: string | undefined,
): { runtime: WorkflowRuntimeV2 | undefined; signature: string } {
  if (!runtimeIndex) return { runtime: undefined, signature: "" };
  const cached = runtimeIndex.scopeByNodeId.get(nodeId);
  if (cached?.items === items && cached.slots === slots) {
    return cached.result;
  }
  const { runtime, memberships } = runtimeIndex;
  const scoped: WorkflowRuntimeV2 = {
    workflow_id: runtime.workflow_id,
    active_execution_id: runtime.active_execution_id,
    execution_status: runtime.execution_status,
    running_slot_ids: selectRuntimeIds(slotIds, memberships.running_slot_ids),
    running_item_ids: selectRuntimeIds(itemIds, memberships.running_item_ids),
    running_node_ids: selectRuntimeNodeId(nodeId, memberships.running_node_ids),
    waiting_slot_ids: selectRuntimeIds(slotIds, memberships.waiting_slot_ids),
    waiting_item_ids: selectRuntimeIds(itemIds, memberships.waiting_item_ids),
    waiting_node_ids: selectRuntimeNodeId(nodeId, memberships.waiting_node_ids),
    failed_slot_ids: selectRuntimeIds(slotIds, memberships.failed_slot_ids),
    failed_item_ids: selectRuntimeIds(itemIds, memberships.failed_item_ids),
    failed_node_ids: selectRuntimeNodeId(nodeId, memberships.failed_node_ids),
    completed_slot_ids: selectRuntimeIds(slotIds, memberships.completed_slot_ids),
    completed_item_ids: selectRuntimeIds(itemIds, memberships.completed_item_ids),
    completed_node_ids: selectRuntimeNodeId(nodeId, memberships.completed_node_ids),
    blocked_slot_ids: selectRuntimeIds(slotIds, memberships.blocked_slot_ids),
    blocked_item_ids: selectRuntimeIds(itemIds, memberships.blocked_item_ids),
    blocked_node_ids: selectRuntimeNodeId(nodeId, memberships.blocked_node_ids),
    skipped_slot_ids: selectRuntimeIds(slotIds, memberships.skipped_slot_ids),
    skipped_item_ids: selectRuntimeIds(itemIds, memberships.skipped_item_ids),
    skipped_node_ids: selectRuntimeNodeId(nodeId, memberships.skipped_node_ids),
    node_runtime: pickRuntimeRecords(runtime.node_runtime, [nodeId]),
    item_runtime: pickRuntimeRecords(runtime.item_runtime, itemIds),
    slot_runtime: pickRuntimeRecords(runtime.slot_runtime, slotIds),
    events_cursor: runtime.events_cursor,
    updated_at: runtime.updated_at,
  };
  const signature = JSON.stringify({
    ...scoped,
    events_cursor: undefined,
    updated_at: undefined,
  });
  const result = signature === previousSignature
    ? { runtime: previous, signature }
    : { runtime: scoped, signature };
  runtimeIndex.scopeByNodeId.set(nodeId, { items, slots, result });
  return result;
}

function createWorkflowRuntimeMembershipIndex(
  runtime: WorkflowRuntimeV2,
): WorkflowRuntimeMembershipIndex {
  const memberships = {} as Record<RuntimeMembershipKey, ReadonlySet<string>>;
  for (const key of RUNTIME_MEMBERSHIP_KEYS) {
    memberships[key] = new Set(runtime[key]);
  }
  return { runtime, memberships, scopeByNodeId: new Map() };
}

function selectRuntimeIds(
  ids: string[],
  membership: ReadonlySet<string>,
) {
  const selected: string[] = [];
  for (const id of ids) {
    if (membership.has(id)) selected.push(id);
  }
  return selected;
}

function selectRuntimeNodeId(
  nodeId: string,
  membership: ReadonlySet<string>,
) {
  return membership.has(nodeId) ? [nodeId] : [];
}

function pickRuntimeRecords<T>(
  source: Record<string, T>,
  keys: string[],
): Record<string, T> {
  const result: Record<string, T> = {};
  for (const key of keys) {
    if (source[key] !== undefined) result[key] = source[key];
  }
  return result;
}
