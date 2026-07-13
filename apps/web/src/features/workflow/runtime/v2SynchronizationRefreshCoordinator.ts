import type { V2ScriptVersionListResponse } from "../../../types-v2.ts";
import type { V2SynchronizationRefreshPlan } from "./v2RuntimeEventModel.ts";

export type V2SynchronizationRefreshScope =
  | "history"
  | "selected"
  | "workflow"
  | "workflowStructure"
  | "slotPrompts"
  | "references"
  | "assets";

export type V2SynchronizationRefreshActions = {
  refreshHistory?: () => Promise<V2ScriptVersionListResponse | null | void> | V2ScriptVersionListResponse | null | void;
  refreshSelectedScreenplay?: (history: V2ScriptVersionListResponse | null) => Promise<unknown> | unknown;
  refreshWorkflow?: (scopes: ReadonlySet<V2SynchronizationRefreshScope>) => Promise<unknown> | unknown;
};

type LedgerEntry = {
  workflowId: string;
  generation: number;
  aliases: Set<string>;
  desired: Set<V2SynchronizationRefreshScope>;
  handled: Set<V2SynchronizationRefreshScope>;
  actions: V2SynchronizationRefreshActions;
  history: V2ScriptVersionListResponse | null;
  scheduled: number;
  touchedAt: number;
  parent: LedgerEntry | null;
};

type SerializationLane = {
  generation: number;
  tail: Promise<void>;
};

export type V2SynchronizationRefreshCoordinator = ReturnType<typeof createV2SynchronizationRefreshCoordinator>;

export function createV2SynchronizationRefreshCoordinator(options: {
  ttlMs?: number;
  maxEntries?: number;
  now?: () => number;
} = {}) {
  const ttlMs = options.ttlMs ?? 60_000;
  const maxEntries = options.maxEntries ?? 128;
  const now = options.now ?? Date.now;
  const entries = new Set<LedgerEntry>();
  const aliases = new Map<string, LedgerEntry>();
  let activeWorkflowId: string | null = null;
  let generation = 0;
  let lane: SerializationLane = { generation, tail: Promise.resolve() };

  const rootEntry = (candidate: LedgerEntry): LedgerEntry => {
    let root = candidate;
    while (root.parent) root = root.parent;
    let current = candidate;
    while (current.parent && current.parent !== root) {
      const parent = current.parent;
      current.parent = root;
      current = parent;
    }
    return root;
  };

  const removeEntry = (entry: LedgerEntry) => {
    entries.delete(entry);
    entry.aliases.forEach((alias) => {
      if (aliases.get(alias) === entry) aliases.delete(alias);
    });
  };

  const clear = () => {
    entries.clear();
    aliases.clear();
  };

  const prune = () => {
    const timestamp = now();
    Array.from(entries).forEach((entry) => {
      if (entry.scheduled === 0 && timestamp - entry.touchedAt > ttlMs) removeEntry(entry);
    });
    while (entries.size > maxEntries) {
      const oldest = Array.from(entries)
        .filter((entry) => entry.scheduled === 0)
        .sort((left, right) => left.touchedAt - right.touchedAt)[0];
      if (!oldest) break;
      removeEntry(oldest);
    }
  };

  const stableAliases = (workflowId: string, plan: V2SynchronizationRefreshPlan) => [
    ...plan.transactionIds.map((id) => `${workflowId}:transaction:${id}`),
    ...plan.scriptVersionIds.map((id) => `${workflowId}:script:${id}`),
  ];

  const mergeActions = (target: V2SynchronizationRefreshActions, source: V2SynchronizationRefreshActions) => {
    target.refreshHistory ??= source.refreshHistory;
    target.refreshSelectedScreenplay ??= source.refreshSelectedScreenplay;
    target.refreshWorkflow ??= source.refreshWorkflow;
  };

  const mergeEntries = (target: LedgerEntry, source: LedgerEntry) => {
    source.aliases.forEach((alias) => target.aliases.add(alias));
    source.desired.forEach((scope) => target.desired.add(scope));
    source.handled.forEach((scope) => target.handled.add(scope));
    mergeActions(target.actions, source.actions);
    target.history ??= source.history;
    target.scheduled += source.scheduled;
    source.parent = target;
    removeEntry(source);
  };

  const entryFor = (workflowId: string, plan: V2SynchronizationRefreshPlan): LedgerEntry => {
    prune();
    const requestedAliases = stableAliases(workflowId, plan);
    const matchingEntries = Array.from(new Set(requestedAliases
      .map((alias) => aliases.get(alias))
      .filter((entry): entry is LedgerEntry => Boolean(entry))
      .map(rootEntry)));
    const entry = matchingEntries[0] ?? {
      workflowId,
      generation,
      aliases: new Set<string>(),
      desired: new Set<V2SynchronizationRefreshScope>(),
      handled: new Set<V2SynchronizationRefreshScope>(),
      actions: {},
      history: null,
      scheduled: 0,
      touchedAt: now(),
      parent: null,
    };
    matchingEntries.slice(1).forEach((other) => mergeEntries(entry, other));
    requestedAliases.forEach((alias) => entry.aliases.add(alias));
    entry.aliases.forEach((alias) => aliases.set(alias, entry));
    entry.touchedAt = now();
    if (requestedAliases.length) entries.add(entry);
    prune();
    return entry;
  };

  const addDesiredScopes = (entry: LedgerEntry, plan: V2SynchronizationRefreshPlan) => {
    if (plan.refreshScreenplayHistory) entry.desired.add("history");
    if (plan.refreshSelectedScreenplay) entry.desired.add("selected");
    if (plan.refreshWorkflow) entry.desired.add("workflow");
    if (plan.refreshWorkflowStructure) entry.desired.add("workflowStructure");
    if (plan.refreshSlotPrompts) entry.desired.add("slotPrompts");
    if (plan.refreshReferences) entry.desired.add("references");
    if (plan.refreshAssets) entry.desired.add("assets");
  };

  const isActive = (entry: LedgerEntry) =>
    entry.generation === generation && entry.workflowId === activeWorkflowId;

  const executeScreenplayScope = async (candidate: LedgerEntry): Promise<boolean> => {
    const entry = rootEntry(candidate);
    if (!isActive(entry)) return false;
    if (entry.desired.has("selected") && !entry.handled.has("selected") && entry.actions.refreshSelectedScreenplay) {
      try {
        await entry.actions.refreshSelectedScreenplay(entry.handled.has("history") ? entry.history : null);
      } catch {
        return false;
      }
      const current = rootEntry(entry);
      if (!isActive(current)) return false;
      current.handled.add("selected");
      current.handled.add("history");
      current.touchedAt = now();
      return true;
    }
    if (entry.desired.has("history") && !entry.handled.has("history") && entry.actions.refreshHistory) {
      let response: V2ScriptVersionListResponse | null | void;
      try {
        response = await entry.actions.refreshHistory();
      } catch {
        return false;
      }
      const current = rootEntry(entry);
      if (!isActive(current)) return false;
      current.history = response ?? null;
      current.handled.add("history");
      current.touchedAt = now();
      return true;
    }
    return false;
  };

  const executeWorkflowScopes = async (candidate: LedgerEntry): Promise<boolean> => {
    const entry = rootEntry(candidate);
    if (!isActive(entry) || !entry.actions.refreshWorkflow) return false;
    const scopes: V2SynchronizationRefreshScope[] = [];
    const hydrationRequested = entry.desired.has("workflow") || entry.desired.has("workflowStructure");
    const hydrationHandled = entry.handled.has("workflow") || entry.handled.has("workflowStructure");
    if (hydrationRequested && !hydrationHandled) {
      scopes.push(entry.desired.has("workflowStructure") ? "workflowStructure" : "workflow");
    }
    (["slotPrompts", "references", "assets"] as const).forEach((scope) => {
      if (entry.desired.has(scope) && !entry.handled.has(scope)) scopes.push(scope);
    });
    if (!scopes.length) return false;
    try {
      await entry.actions.refreshWorkflow(new Set(scopes));
    } catch {
      return false;
    }
    const current = rootEntry(entry);
    if (!isActive(current)) return false;
    if (scopes.includes("workflow") || scopes.includes("workflowStructure")) {
      current.handled.add("workflow");
      current.handled.add("workflowStructure");
    }
    scopes.forEach((scope) => current.handled.add(scope));
    current.touchedAt = now();
    return true;
  };

  const drainEntry = async (candidate: LedgerEntry) => {
    while (isActive(rootEntry(candidate))) {
      if (await executeScreenplayScope(candidate)) continue;
      if (await executeWorkflowScopes(candidate)) continue;
      break;
    }
  };

  const coordinate = async (
    workflowId: string,
    plan: V2SynchronizationRefreshPlan,
    actions: V2SynchronizationRefreshActions,
  ) => {
    if (!plan.isSynchronizationBatch || activeWorkflowId !== workflowId) return;
    const entry = entryFor(workflowId, plan);
    addDesiredScopes(entry, plan);
    mergeActions(entry.actions, actions);
    entry.scheduled += 1;
    const currentLane = lane;
    const work = currentLane.tail.then(async () => {
      try {
        await drainEntry(rootEntry(entry));
      } finally {
        const current = rootEntry(entry);
        current.scheduled = Math.max(0, current.scheduled - 1);
        current.touchedAt = now();
        prune();
      }
    });
    currentLane.tail = work.catch(() => {});
    await work;
  };

  return {
    activateWorkflow(workflowId: string | null) {
      if (activeWorkflowId === workflowId) return;
      clear();
      activeWorkflowId = workflowId;
      generation += 1;
      lane = { generation, tail: Promise.resolve() };
    },
    clearWorkflow(workflowId: string | null) {
      if (workflowId !== null && activeWorkflowId !== workflowId) return;
      clear();
      if (activeWorkflowId === workflowId) activeWorkflowId = null;
      generation += 1;
      lane = { generation, tail: Promise.resolve() };
    },
    coordinate,
    dispose() {
      clear();
      activeWorkflowId = null;
      generation += 1;
      lane = { generation, tail: Promise.resolve() };
    },
  };
}
