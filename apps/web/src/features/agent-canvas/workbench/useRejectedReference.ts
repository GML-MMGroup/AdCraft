import { useEffect, useState } from "react";
import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import type { AgentCanvasWorkflowV2, CanvasNodeV2, NodeRuntimeV2, ProviderInputManifestAuditV2 } from "../../../types-v2.ts";
import { inputManifestAuditFromEvent } from "../runtime/inputManifestAudit.ts";
import { mediaExecutionError } from "./mediaExecutionError.ts";
import { referenceImageRejection, rejectedReferenceBindingId } from "./referenceImageRejection.ts";

export function useRejectedReference(
  workflow: AgentCanvasWorkflowV2,
  node: CanvasNodeV2,
  runtime: NodeRuntimeV2 | null,
  inputManifest: ProviderInputManifestAuditV2 | null,
  running: boolean,
): string | null {
  const error = running || !["image", "video", "audio"].includes(node.node_type)
    ? null : mediaExecutionError(node, runtime);
  const rejection = error ? referenceImageRejection(error.message) : null;
  const executionId = error && runtime?.error === error ? runtime.execution_id
    : error ? node.latest_attempt?.execution_id : null;
  const manifestId = error && runtime?.error === error ? runtime.input_manifest_id : null;
  const nodeId = node.node_id;
  const workflowId = workflow.workflow_id;
  const contentIndex = rejection?.contentIndex ?? null;
  const [recoveredManifest, setRecoveredManifest] = useState<ProviderInputManifestAuditV2 | null>(null);
  const matches = (manifest: ProviderInputManifestAuditV2 | null) => Boolean(manifest
    && executionId && manifest.execution_id === executionId && manifest.node_id === nodeId
    && (!manifestId || manifest.input_manifest_id === manifestId));
  const manifest = matches(inputManifest) ? inputManifest : matches(recoveredManifest) ? recoveredManifest : null;

  useEffect(() => {
    if (manifest || contentIndex === null || contentIndex < 1 || !executionId) return;
    const controller = new AbortController();
    // The live stream starts at the runtime cursor on reload. Recover this
    // failed request's audit without replaying historical runtime side effects.
    void (async () => {
      let cursor = 0;
      let found: ProviderInputManifestAuditV2 | null = null;
      for (;;) {
        const page = await agentCanvasApi.agentCanvasEvents(workflowId, cursor, 200, controller.signal);
        if (controller.signal.aborted) return;
        for (const event of page.events) {
          if (event.node_id !== nodeId || event.execution_id !== executionId) continue;
          const candidate = inputManifestAuditFromEvent(event);
          if (candidate && (!manifestId || candidate.input_manifest_id === manifestId)) found = candidate;
        }
        if ((found && manifestId) || page.events.length < 200 || page.next_cursor <= cursor) break;
        cursor = page.next_cursor;
      }
      if (!controller.signal.aborted && found) setRecoveredManifest(found);
    })().catch(() => {
      // The provider reminder still appears if its historical audit is unavailable.
    });
    return () => controller.abort();
  }, [contentIndex, executionId, manifest, manifestId, nodeId, workflowId]);

  return manifest && contentIndex !== null && contentIndex > 0
    ? rejectedReferenceBindingId(workflow, nodeId, manifest.media_inputs[contentIndex - 1])
    : null;
}
