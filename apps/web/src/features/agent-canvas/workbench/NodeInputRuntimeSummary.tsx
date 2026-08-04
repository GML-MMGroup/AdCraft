import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  ProviderInputManifestAuditV2,
  UpstreamInputReadinessIssueV2,
} from "../../../types-v2.ts";

type ResolvedInput = {
  bindingId: string;
  displayOrder: number;
  sourceName: string;
  mediaType: "text" | "image" | "video" | "audio";
  inputRole: string;
  required: boolean;
};

function nodeName(workflow: AgentCanvasWorkflowV2, nodeId: string | null): string {
  if (!nodeId) return "Asset reference";
  return workflow.nodes.find((node) => node.node_id === nodeId)?.title ?? nodeId;
}

function inputLabel(role: string): string {
  return role.replaceAll("_", " ");
}

function resolvedInputs(
  workflow: AgentCanvasWorkflowV2,
  inputManifest: ProviderInputManifestAuditV2,
): ResolvedInput[] {
  const text = inputManifest.text_inputs.map((input) => ({
    bindingId: input.binding_id,
    displayOrder: input.display_order,
    sourceName: nodeName(workflow, input.source_node_id),
    mediaType: "text" as const,
    inputRole: input.input_role,
    required: input.required,
  }));
  const media = inputManifest.media_inputs.map((input) => ({
    bindingId: input.binding_id,
    displayOrder: input.display_order,
    sourceName: workflow.assets.find((asset) => asset.asset_id === input.asset_id)?.display_name
      ?? nodeName(workflow, input.source_node_id),
    mediaType: input.media_type,
    inputRole: input.input_role,
    required: input.required,
  }));
  return [...text, ...media].sort((left, right) => (
    left.displayOrder - right.displayOrder || left.bindingId.localeCompare(right.bindingId)
  ));
}

export function NodeInputRuntimeSummary({
  workflow,
  node,
  inputManifest,
  inputReadinessIssue,
}: {
  workflow: AgentCanvasWorkflowV2;
  node: CanvasNodeV2;
  inputManifest?: ProviderInputManifestAuditV2 | null;
  inputReadinessIssue?: UpstreamInputReadinessIssueV2 | null;
}) {
  const issue = inputReadinessIssue?.target_node_id === node.node_id
    ? inputReadinessIssue
    : null;
  const inputs = inputManifest?.node_id === node.node_id
    ? resolvedInputs(workflow, inputManifest)
    : [];
  const omitted = inputManifest?.node_id === node.node_id
    ? inputManifest.omitted_optional_inputs
    : [];

  if (!issue && !inputs.length && !omitted.length) return null;

  return (
    <section className="agent-node-workbench__runtime-inputs" aria-label="Resolved node inputs">
      {issue ? (
        <p className="agent-node-workbench__input-warning" role="status">
          Waiting for required inputs: {issue.source_node_ids.map((sourceNodeId) => nodeName(workflow, sourceNodeId)).join(", ")}
        </p>
      ) : null}
      {inputs.length ? (
        <>
          <div className="agent-node-workbench__section-heading">
            <strong>Resolved inputs</strong>
            <span>{inputs.length}</span>
          </div>
          <div className="agent-node-workbench__resolved-input-list">
            {inputs.map((input) => (
              <div data-testid="resolved-input" key={input.bindingId}>
                <strong>{input.sourceName}</strong>
                <small>{input.mediaType} · {inputLabel(input.inputRole)} · {input.required ? "Required" : "Optional"}</small>
              </div>
            ))}
          </div>
        </>
      ) : null}
      {omitted.map((input) => (
        <p className="agent-node-workbench__input-warning" key={input.binding_id}>
          Optional input unavailable: {nodeName(workflow, input.source_node_id)}
        </p>
      ))}
    </section>
  );
}
