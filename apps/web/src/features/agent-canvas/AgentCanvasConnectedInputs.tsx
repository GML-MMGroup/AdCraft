import {
  DocumentIcon,
  ImageIcon,
  MuteIcon,
  VideoIcon,
} from "../../icons.tsx";
import type {
  AgentCanvasWorkflowV2,
  CanvasBindingV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../types-v2.ts";
import {
  durationHintForResolvedInputs,
  resolvedInputPurposeLabel,
  type ProviderInputsResolvedState,
  type ProviderResolvedInputSummary,
} from "./runtime/providerInputsResolved.ts";

type ConnectedInputView = {
  binding: CanvasBindingV2;
  sourceNode: CanvasNodeV2 | null;
  sourceAsset: ProjectAssetSummaryV2 | null;
  resolved: ProviderResolvedInputSummary | null;
};

function connectedInputs(
  workflow: AgentCanvasWorkflowV2,
  nodeId: string,
  resolvedInputs: ProviderInputsResolvedState | null,
): ConnectedInputView[] {
  const nodes = new Map(workflow.nodes.map((node) => [node.node_id, node]));
  const assets = new Map(workflow.assets.map((asset) => [asset.asset_id, asset]));
  const resolvedByBinding = new Map(
    (resolvedInputs?.inputs ?? []).map((input) => [input.binding_id, input]),
  );
  return workflow.bindings
    .filter((binding) => binding.target_node_id === nodeId)
    .sort((left, right) => (
      left.display_order - right.display_order
      || left.binding_id.localeCompare(right.binding_id)
    ))
    .map((binding) => {
      const sourceNode = binding.source.kind === "node"
        ? nodes.get(binding.source.node_id) ?? null
        : null;
      const assetId = binding.source.kind === "image_asset"
        ? binding.source.asset_id
        : sourceNode?.output_asset_id;
      return {
        binding,
        sourceNode,
        sourceAsset: assetId ? assets.get(assetId) ?? null : null,
        resolved: resolvedByBinding.get(binding.binding_id) ?? null,
      };
    });
}

function inputRoleLabel(role: CanvasBindingV2["input_role"]): string {
  return role.replaceAll("_", " ").replace(/^\w/, (letter) => letter.toUpperCase());
}

function sourceTypeLabel(input: ConnectedInputView): string {
  if (input.sourceNode) {
    return `${input.sourceNode.node_type.replace(/^\w/, (letter) => letter.toUpperCase())} node`;
  }
  return input.sourceAsset ? `${input.sourceAsset.media_type} asset` : "Asset";
}

function fallbackIcon(input: ConnectedInputView) {
  const type = input.sourceAsset?.media_type ?? input.sourceNode?.node_type;
  if (type === "image") return <ImageIcon />;
  if (type === "video" || type === "editing") return <VideoIcon />;
  if (type === "audio") return <MuteIcon />;
  return <DocumentIcon />;
}

function previewUrl(input: ConnectedInputView): string | null {
  return input.sourceAsset?.preview_url
    ?? (input.sourceAsset?.media_type === "image" ? input.sourceAsset.media_url : null);
}

export function AgentCanvasConnectedInputs({
  workflow,
  nodeId,
  resolvedInputs,
}: {
  workflow: AgentCanvasWorkflowV2;
  nodeId: string;
  resolvedInputs: ProviderInputsResolvedState | null;
}) {
  const inputs = connectedInputs(workflow, nodeId, resolvedInputs);
  if (!inputs.length) return null;
  const durationHint = resolvedInputs
    ? durationHintForResolvedInputs(resolvedInputs)
    : null;

  return (
    <section
      className="agent-canvas-inspector__connected-inputs"
      aria-label="Connected inputs"
    >
      <header>
        <strong>Connected inputs</strong>
        <span>{inputs.length}</span>
      </header>
      <div className="agent-canvas-inspector__input-list">
        {inputs.map((input) => {
          const providerLabel = input.resolved?.label ?? null;
          const purposeLabel = input.resolved
            ? resolvedInputPurposeLabel(input.resolved)
            : null;
          const sourceName = input.sourceNode?.title
            ?? input.sourceAsset?.display_name
            ?? input.binding.binding_id;
          const primaryName = purposeLabel ?? sourceName;
          const showSourceName = sourceName !== primaryName;
          const src = previewUrl(input);
          return (
            <article
              className="agent-canvas-inspector__input-card"
              data-testid="agent-canvas-connected-input"
              key={input.binding.binding_id}
            >
              <div className="agent-canvas-inspector__input-preview">
                {src ? (
                  <img src={src} alt={`${primaryName} input`} />
                ) : (
                  <span role="img" aria-label={`${primaryName} preview unavailable`}>
                    {fallbackIcon(input)}
                  </span>
                )}
              </div>
              <div className="agent-canvas-inspector__input-copy">
                <div>
                  <strong>{primaryName}</strong>
                  {providerLabel && providerLabel !== primaryName ? (
                    <span>{providerLabel}</span>
                  ) : null}
                </div>
                {showSourceName ? <small>{sourceName}</small> : null}
                <small>{sourceTypeLabel(input)}</small>
                <div className="agent-canvas-inspector__input-tags">
                  <span>{inputRoleLabel(input.binding.input_role)}</span>
                  <span className={input.binding.required ? "is-required" : "is-optional"}>
                    {input.binding.required ? "Required" : "Optional"}
                  </span>
                </div>
              </div>
            </article>
          );
        })}
      </div>
      {durationHint ? (
        <p className="agent-canvas-inspector__duration-hint" role="status">
          {durationHint}
        </p>
      ) : null}
    </section>
  );
}
