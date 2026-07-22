import { useEffect, useState } from "react";
import { v2Api } from "../api/v2Client";
import { useApp } from "../AppContextValue";
import type { WorkflowRevisionV2Summary } from "../types-v2";
import { workflowV2ToWorkflowGraph } from "../workflow-v2/pageAdapter";
import { revisionActionLabel, revisionCanBeRestored } from "./v2RevisionHistory";

export function V2WorkflowRevisionControl() {
  const { workflow, setWorkflow } = useApp();
  const [open, setOpen] = useState(false);
  const [revisions, setRevisions] = useState<WorkflowRevisionV2Summary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState<number | null>(null);
  const workflowId = workflow?.project_id ? workflow.workflow_id : null;
  const currentRevisionNo = workflow?.semantic_revision_no ?? 0;

  useEffect(() => {
    setOpen(false);
    setRevisions([]);
    setError(null);
  }, [workflowId]);

  if (!workflowId) return null;
  const activeWorkflowId = workflowId;

  async function toggleHistory() {
    const nextOpen = !open;
    setOpen(nextOpen);
    if (!nextOpen || revisions.length) return;
    try {
      setError(null);
      setRevisions((await v2Api.workflowRevisions(activeWorkflowId)).items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Revision history could not be loaded.");
    }
  }

  async function restoreRevision(revisionNo: number) {
    setRestoring(revisionNo);
    try {
      setError(null);
      const response = await v2Api.restoreWorkflowRevision(activeWorkflowId, revisionNo);
      setWorkflow(workflowV2ToWorkflowGraph(response.value.workflow));
      setRevisions((await v2Api.workflowRevisions(activeWorkflowId)).items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Revision could not be restored.");
    } finally {
      setRestoring(null);
    }
  }

  return (
    <div className="workflow-revision-control">
      <button className="ghost-btn" type="button" aria-expanded={open} onClick={() => void toggleHistory()}>
        History
      </button>
      {open ? (
        <section className="workflow-revision-menu" aria-label="Workflow revision history">
          <h2>Revision history</h2>
          {error ? <p role="alert">{error}</p> : null}
          {revisions.map((revision) => (
            <div key={revision.revision_id} className="workflow-revision-row">
              <span>{revisionActionLabel(revision)}</span>
              <time dateTime={revision.created_at}>{new Date(revision.created_at).toLocaleString()}</time>
              <button
                type="button"
                disabled={!revisionCanBeRestored(revision, currentRevisionNo) || restoring !== null}
                onClick={() => void restoreRevision(revision.revision_no)}
              >
                {revision.revision_no === currentRevisionNo ? "Current" : "Restore"}
              </button>
            </div>
          ))}
        </section>
      ) : null}
    </div>
  );
}
