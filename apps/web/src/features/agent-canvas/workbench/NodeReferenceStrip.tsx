import { CloseIcon, DocumentIcon } from "../../../icons.tsx";
import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
} from "../../../types-v2.ts";
import { mediaAssetPreviewPath } from "../../../workflow/mediaPreview.ts";
import { StableMediaPreview } from "../../../workflow/StableMediaPreview.tsx";

function referencePreview(asset: AgentCanvasWorkflowV2["assets"][number] | undefined | null): string | null {
  if (!asset) return null;
  return mediaAssetPreviewPath(asset) || null;
}

function sourcePresentation(
  workflow: AgentCanvasWorkflowV2,
  binding: AgentCanvasWorkflowV2["bindings"][number],
) {
  const source = binding.source;
  if (source.kind === "image_asset") {
    const asset = workflow.assets.find((item) => item.asset_id === source.source_asset_id);
    const boundVersionAsset = asset && source.source_asset_version_id
      ? { ...asset, version_id: source.source_asset_version_id }
      : asset;
    return {
      name: asset?.display_name ?? source.source_asset_id,
      previewUrl: referencePreview(boundVersionAsset),
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
              aria-label={source.previewUrl ? undefined : `${label} text reference`}
            >
              {source.previewUrl ? (
                <StableMediaPreview src={source.previewUrl} alt={`${label} reference`} loading="lazy" decoding="async" />
              ) : (
                <span className="agent-node-workbench__reference-icon">
                  <DocumentIcon />
                </span>
              )}
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
