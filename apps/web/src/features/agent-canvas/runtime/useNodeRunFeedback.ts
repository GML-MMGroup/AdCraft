import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AgentCanvasWorkflowV2, CanvasNodeV2 } from "../../../types-v2.ts";
import { isSourceOnlyNode } from "../model/nodeExecutionMode.ts";
import { nodeRunActivity } from "../model/nodeRunActivity.ts";

interface PendingNodeRun {
  nodeId: string;
  phase: "preparing" | "submitting" | "accepted";
  executionId: string | null;
}
interface RunScope {
  workflowId: string | null;
  active: boolean;
  runs: Map<string, PendingNodeRun>;
}
const TERMINAL_ATTEMPTS = new Set(["succeeded", "failed", "cancelled", "blocked", "skipped_dependency"]);

/** Local presentation only; never write a speculative status to authoring state. */
export function useNodeRunFeedback(workflow: AgentCanvasWorkflowV2 | null) {
  const workflowId = workflow?.workflow_id ?? null;
  const scopeRef = useRef<RunScope>({ workflowId, active: true, runs: new Map() });
  if (scopeRef.current.workflowId !== workflowId) {
    scopeRef.current = { workflowId, active: true, runs: new Map() };
  }
  const scope = scopeRef.current;
  const [snapshot, setSnapshot] = useState<{ scope: RunScope; runs: PendingNodeRun[] }>({ scope, runs: [] });
  const publish = useCallback((owner: RunScope) => {
    if (owner.active && scopeRef.current === owner) setSnapshot({ scope: owner, runs: [...owner.runs.values()] });
  }, []);

  useEffect(() => {
    scope.active = true;
    return () => { scope.active = false; scope.runs.clear(); };
  }, [scope]);

  useEffect(() => {
    if (!workflow || scope.workflowId !== workflow.workflow_id) return;
    let changed = false;
    for (const [nodeId, run] of scope.runs) {
      const node = workflow.nodes.find(candidate => candidate.node_id === nodeId);
      const attempt = node?.latest_attempt;
      const acknowledged = run.phase === "accepted" && (
        (attempt?.execution_id === run.executionId
          && (node?.status === "working" || TERMINAL_ATTEMPTS.has(attempt.status)))
        || (!attempt && node?.status === "working")
      );
      if (!node || acknowledged) { scope.runs.delete(nodeId); changed = true; }
    }
    if (changed) publish(scope);
  }, [publish, scope, snapshot, workflow]);

  const begin = useCallback((node: CanvasNodeV2, preparing: boolean) => {
    const owner = scope;
    if (!owner.active || scopeRef.current !== owner || !workflowId || node.workflow_id !== workflowId
      || !["text", "script", "image", "video", "audio"].includes(node.node_type)
      || isSourceOnlyNode(node) || nodeRunActivity(node) || !["draft", "failed", "ready"].includes(node.status)) return null;
    const previous = owner.runs.get(node.node_id);
    if (previous && (preparing || previous.phase !== "preparing")) return null;
    const run: PendingNodeRun = previous ?? { nodeId: node.node_id, phase: "preparing", executionId: null };
    run.phase = preparing ? "preparing" : "submitting";
    owner.runs.set(node.node_id, run);
    publish(owner);
    const isCurrent = () => owner.active && scopeRef.current === owner && owner.runs.get(node.node_id) === run;
    const finish = () => {
      if (!isCurrent()) return;
      owner.runs.delete(node.node_id);
      publish(owner);
    };
    return {
      isCurrent,
      finish,
      cancelPreparation: () => { if (run.phase === "preparing") finish(); },
      accept: (executionId: string) => {
        if (!isCurrent()) return;
        run.phase = "accepted";
        run.executionId = executionId;
        publish(owner);
      },
    };
  }, [publish, scope, workflowId]);
  const beginRun = useCallback((node: CanvasNodeV2) => begin(node, false), [begin]);
  const beginPreparation = useCallback((node: CanvasNodeV2) => begin(node, true)?.cancelPreparation ?? null, [begin]);
  const pendingNodeIds = useMemo(() => new Set(
    snapshot.scope === scope ? snapshot.runs.map(run => run.nodeId) : [],
  ), [scope, snapshot]);
  const awaitingAcknowledgement = snapshot.scope === scope && snapshot.runs.some(run => run.phase === "accepted");
  return { beginRun, beginPreparation, pendingNodeIds, awaitingAcknowledgement };
}
