import {
  ChevronDownIcon,
  ChevronUpIcon,
  TrashIcon,
} from "../../../icons.tsx";
import type {
  AgentCanvasWorkflowV2,
  CanvasBindingInputRoleV2,
  CanvasBindingPatchRequestV2,
  CanvasConnectionPolicyV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";
import type { PatchBinding } from "./workbenchTypes.ts";

function referencePreview(asset: AgentCanvasWorkflowV2["assets"][number] | undefined | null): string | null {
  if (!asset) return null;
  return asset.media_type === "image"
    ? asset.media_url ?? asset.preview_url
    : asset.preview_url ?? asset.media_url;
}

function sourcePresentation(
  workflow: AgentCanvasWorkflowV2,
  binding: AgentCanvasWorkflowV2["bindings"][number],
) {
  const source = binding.source;
  if (source.kind === "image_asset") {
    const asset = workflow.assets.find((item) => item.asset_id === source.source_asset_id);
    return {
      name: asset?.display_name ?? source.source_asset_id,
      previewUrl: referencePreview(asset),
    };
  }
  const sourceNode = workflow.nodes.find((item) => item.node_id === source.source_node_id);
  const asset = sourceNode?.output_asset_id
    ? workflow.assets.find((item) => item.asset_id === sourceNode.output_asset_id)
    : null;
  return {
    name: sourceNode?.title ?? source.source_node_id,
    previewUrl: referencePreview(asset),
  };
}

function allowedInputRoles(
  workflow: AgentCanvasWorkflowV2,
  node: CanvasNodeV2,
  binding: AgentCanvasWorkflowV2["bindings"][number],
  connectionPolicy?: CanvasConnectionPolicyV2 | null,
): CanvasBindingInputRoleV2[] {
  if (!connectionPolicy) return [binding.input_role];
  const source = binding.source;
  if (source.kind === "image_asset") {
    return connectionPolicy.image_asset_targets[node.node_type] ?? [binding.input_role];
  }
  const sourceNode = workflow.nodes.find((item) => item.node_id === source.source_node_id);
  const rule = sourceNode
    ? connectionPolicy.input_roles.find((candidate) => (
      candidate.source_node_type === sourceNode.node_type
      && candidate.target_node_type === node.node_type
    ))
    : null;
  return rule?.roles ?? [binding.input_role];
}

export function NodeReferenceStrip({
  workflow,
  node,
  connectionPolicy,
  patchBinding,
  deleteBinding,
  pending,
  perform,
}: {
  workflow: AgentCanvasWorkflowV2;
  node: CanvasNodeV2;
  connectionPolicy?: CanvasConnectionPolicyV2 | null;
  patchBinding?: PatchBinding;
  deleteBinding?: (bindingId: string) => Promise<void>;
  pending: boolean;
  perform: (action: () => Promise<unknown>) => Promise<boolean>;
}) {
  const inboundBindings = workflow.bindings
    .filter((binding) => binding.target_node_id === node.node_id)
    .sort((left, right) => left.order - right.order);

  if (!inboundBindings.length) return null;

  const patch = async (bindingId: string, request: CanvasBindingPatchRequestV2) => {
    if (!patchBinding) return;
    await perform(() => patchBinding(bindingId, request));
  };

  return (
    <section className="agent-node-workbench__references" aria-label="Node references">
      <div className="agent-node-workbench__section-heading">
        <strong>References</strong>
        <span>{inboundBindings.length}</span>
      </div>
      <div className="agent-node-workbench__reference-list">
        {inboundBindings.map((binding, index) => {
          const source = sourcePresentation(workflow, binding);
          const roles = allowedInputRoles(workflow, node, binding, connectionPolicy);
          const label = binding.label || `Reference ${index + 1}`;
          return (
            <article key={binding.binding_id} className={!binding.enabled ? "is-disabled" : ""}>
              <div className="agent-node-workbench__reference-source">
                {source.previewUrl ? (
                  <img src={source.previewUrl} alt="" loading="lazy" decoding="async" />
                ) : <span aria-hidden="true">{index + 1}</span>}
                <div>
                  <strong>{label}</strong>
                  <small>{source.name}</small>
                </div>
                <div className="agent-node-workbench__reference-actions">
                  <button
                    type="button"
                    aria-label={`Move ${label} earlier`}
                    title="Move earlier"
                    disabled={pending || !patchBinding || index === 0}
                    onClick={() => void patch(binding.binding_id, { order: inboundBindings[index - 1]?.order ?? 0 })}
                  >
                    <ChevronUpIcon />
                  </button>
                  <button
                    type="button"
                    aria-label={`Move ${label} later`}
                    title="Move later"
                    disabled={pending || !patchBinding || index === inboundBindings.length - 1}
                    onClick={() => void patch(binding.binding_id, { order: inboundBindings[index + 1]?.order ?? binding.order })}
                  >
                    <ChevronDownIcon />
                  </button>
                  <button
                    type="button"
                    className="is-danger"
                    aria-label={`Remove ${label}`}
                    title="Remove reference"
                    disabled={pending || !deleteBinding}
                    onClick={() => deleteBinding && void perform(() => deleteBinding(binding.binding_id))}
                  >
                    <TrashIcon />
                  </button>
                </div>
              </div>
              <div className="agent-node-workbench__reference-config">
                <label>
                  <span>Role</span>
                  <select
                    value={binding.input_role}
                    disabled={pending || !patchBinding}
                    onChange={(event) => void patch(binding.binding_id, {
                      input_role: event.currentTarget.value as CanvasBindingInputRoleV2,
                    })}
                  >
                    {roles.map((role) => <option key={role} value={role}>{role.replaceAll("_", " ")}</option>)}
                  </select>
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={binding.required}
                    disabled={pending || !patchBinding}
                    onChange={(event) => void patch(binding.binding_id, { required: event.currentTarget.checked })}
                  />
                  <span>Required</span>
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={binding.enabled}
                    disabled={pending || !patchBinding}
                    onChange={(event) => void patch(binding.binding_id, { enabled: event.currentTarget.checked })}
                  />
                  <span>Enabled</span>
                </label>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
