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
  refreshHistory?: () => Promise<unknown> | unknown;
  refreshSelectedScreenplay?: () => Promise<unknown> | unknown;
  refreshWorkflow?: (scopes: ReadonlySet<V2SynchronizationRefreshScope>) => Promise<unknown> | unknown;
};

type LedgerEntry = {
  workflowId: string;
  aliases: Set<string>;
  handled: Set<V2SynchronizationRefreshScope>;
  pending: Set<V2SynchronizationRefreshScope>;
  touchedAt: number;
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
      if (entry.pending.size === 0 && timestamp - entry.touchedAt > ttlMs) removeEntry(entry);
    });
    while (entries.size > maxEntries) {
      const oldest = Array.from(entries)
        .filter((entry) => entry.pending.size === 0)
        .sort((left, right) => left.touchedAt - right.touchedAt)[0];
      if (!oldest) break;
      removeEntry(oldest);
    }
  };

  const stableAliases = (workflowId: string, plan: V2SynchronizationRefreshPlan) => [
    ...plan.transactionIds.map((id) => `${workflowId}:transaction:${id}`),
    ...plan.scriptVersionIds.map((id) => `${workflowId}:script:${id}`),
  ];

  const entryFor = (workflowId: string, plan: V2SynchronizationRefreshPlan): LedgerEntry => {
    prune();
    const requestedAliases = stableAliases(workflowId, plan);
    const matchingEntries = Array.from(new Set(requestedAliases.map((alias) => aliases.get(alias)).filter((entry): entry is LedgerEntry => Boolean(entry))));
    const entry = matchingEntries[0] ?? {
      workflowId,
      aliases: new Set<string>(),
      handled: new Set<V2SynchronizationRefreshScope>(),
      pending: new Set<V2SynchronizationRefreshScope>(),
      touchedAt: now(),
    };
    matchingEntries.slice(1).forEach((other) => {
      other.handled.forEach((scope) => entry.handled.add(scope));
      other.pending.forEach((scope) => entry.pending.add(scope));
      other.aliases.forEach((alias) => entry.aliases.add(alias));
      removeEntry(other);
    });
    requestedAliases.forEach((alias) => entry.aliases.add(alias));
    entry.aliases.forEach((alias) => aliases.set(alias, entry));
    entry.touchedAt = now();
    if (requestedAliases.length) entries.add(entry);
    prune();
    return entry;
  };

  const available = (entry: LedgerEntry, scope: V2SynchronizationRefreshScope) =>
    !entry.handled.has(scope) && !entry.pending.has(scope);

  const run = async (
    entry: LedgerEntry,
    scopes: V2SynchronizationRefreshScope[],
    action: (() => Promise<unknown> | unknown) | undefined,
    subsumed: V2SynchronizationRefreshScope[] = [],
  ) => {
    if (!action || !scopes.length) return;
    scopes.forEach((scope) => entry.pending.add(scope));
    subsumed.forEach((scope) => entry.pending.add(scope));
    try {
      await action();
      scopes.forEach((scope) => entry.handled.add(scope));
      subsumed.forEach((scope) => entry.handled.add(scope));
    } finally {
      scopes.forEach((scope) => entry.pending.delete(scope));
      subsumed.forEach((scope) => entry.pending.delete(scope));
      entry.touchedAt = now();
    }
  };

  const coordinate = async (
    workflowId: string,
    plan: V2SynchronizationRefreshPlan,
    actions: V2SynchronizationRefreshActions,
  ) => {
    if (!plan.isSynchronizationBatch || activeWorkflowId !== workflowId) return;
    const entry = entryFor(workflowId, plan);
    const tasks: Promise<unknown>[] = [];

    if (plan.refreshSelectedScreenplay && available(entry, "selected")) {
      tasks.push(run(entry, ["selected"], actions.refreshSelectedScreenplay, ["history"]));
    } else if (plan.refreshScreenplayHistory && available(entry, "history") && !entry.handled.has("selected") && !entry.pending.has("selected")) {
      tasks.push(run(entry, ["history"], actions.refreshHistory));
    }

    const workflowScopes: V2SynchronizationRefreshScope[] = [];
    if (plan.refreshWorkflowStructure && available(entry, "workflowStructure")) {
      workflowScopes.push("workflowStructure");
    } else if (plan.refreshWorkflow && available(entry, "workflow") && !entry.handled.has("workflowStructure") && !entry.pending.has("workflowStructure")) {
      workflowScopes.push("workflow");
    }
    if (plan.refreshSlotPrompts && available(entry, "slotPrompts")) workflowScopes.push("slotPrompts");
    if (plan.refreshReferences && available(entry, "references")) workflowScopes.push("references");
    if (plan.refreshAssets && available(entry, "assets")) workflowScopes.push("assets");
    if (workflowScopes.length && actions.refreshWorkflow) {
      const subsumed = workflowScopes.includes("workflowStructure") ? ["workflow" as const] : [];
      tasks.push(run(entry, workflowScopes, () => actions.refreshWorkflow?.(new Set(workflowScopes)), subsumed));
    }

    await Promise.allSettled(tasks);
    prune();
  };

  return {
    activateWorkflow(workflowId: string | null) {
      if (activeWorkflowId === workflowId) return;
      clear();
      activeWorkflowId = workflowId;
    },
    clearWorkflow(workflowId: string | null) {
      if (workflowId !== null && activeWorkflowId !== workflowId) return;
      clear();
      if (activeWorkflowId === workflowId) activeWorkflowId = null;
    },
    coordinate,
    dispose() {
      clear();
      activeWorkflowId = null;
    },
  };
}
