import type { WorkflowGraph } from "./types";

export function workflowSchemaVersionOfGraph(value?: WorkflowGraph | null): 1 | 2 {
  if (!value) return 1;
  const topLevelVersion = "workflow_schema_version" in value
    ? (value as WorkflowGraph & { workflow_schema_version?: unknown }).workflow_schema_version
    : undefined;
  if (topLevelVersion === 2) return 2;
  return value.metadata?.workflow_schema_version === 2 ? 2 : 1;
}

export function isWorkflowV2Graph(value?: WorkflowGraph | null): value is WorkflowGraph {
  return workflowSchemaVersionOfGraph(value) === 2;
}
