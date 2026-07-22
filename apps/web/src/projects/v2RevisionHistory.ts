import type { WorkflowRevisionV2Summary } from "../types-v2.ts";

export function revisionCanBeRestored(revision: WorkflowRevisionV2Summary, currentRevisionNo: number): boolean {
  return revision.revision_no !== currentRevisionNo;
}

export function revisionActionLabel(revision: WorkflowRevisionV2Summary): string {
  const source = revision.change_source.replaceAll("_", " ");
  return `Revision ${revision.revision_no} · ${source.charAt(0).toUpperCase()}${source.slice(1)}`;
}
