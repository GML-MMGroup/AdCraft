import { CloseIcon } from "../../../icons.tsx";
import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";

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
      text: asset?.display_name ?? source.source_asset_id,
    };
  }
  const sourceNode = workflow.nodes.find((item) => item.node_id === source.source_node_id);
  const asset = sourceNode?.output_asset_id
    ? workflow.assets.find((item) => item.asset_id === sourceNode.output_asset_id)
    : null;
  return {
    name: sourceNode?.title ?? source.source_node_id,
    previewUrl: referencePreview(asset),
    text: sourceNode?.title ?? source.source_node_id,
  };
}

export function NodeReferenceStrip({
  workflow,
  node,
  deleteBinding,
  pending,
  perform,
}: {
  workflow: AgentCanvasWorkflowV2;
  node: CanvasNodeV2;
  deleteBinding?: (bindingId: string) => Promise<void>;
  pending: boolean;
  perform: (action: () => Promise<unknown>) => Promise<boolean>;
}) {
  const inboundBindings = workflow.bindings
    .filter((binding) => binding.target_node_id === node.node_id)
    .sort((left, right) => left.order - right.order);

  if (!inboundBindings.length) return null;

  return (
    <section className="agent-node-workbench__references" aria-label="Node references">
      <div className="agent-node-workbench__reference-list">
        {inboundBindings.map((binding, index) => {
          const source = sourcePresentation(workflow, binding);
          const label = binding.label || source.name || `Reference ${index + 1}`;
          return (
            <article
              key={binding.binding_id}
              className={`${source.previewUrl ? "is-media" : "is-text"}${!binding.enabled ? " is-disabled" : ""}`}
              title={label}
            >
              {source.previewUrl ? (
                <img src={source.previewUrl} alt={`${label} reference`} loading="lazy" decoding="async" />
              ) : <span className="agent-node-workbench__reference-text">{source.text || `Reference ${index + 1}`}</span>}
              <button
                type="button"
                aria-label={`Remove ${label} reference`}
                title={`Remove ${label}`}
                disabled={pending || !deleteBinding}
                onClick={() => deleteBinding && void perform(() => deleteBinding(binding.binding_id))}
              >
                <CloseIcon />
              </button>
            </article>
          );
        })}
      </div>
    </section>
  );
}
