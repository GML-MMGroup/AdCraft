import type {
  AgentCanvasWorkflowV2,
  CanvasBindingV2,
  CanvasNodeV2,
  EditingManifestV2,
  EditingNodeContentV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";

export interface EditingBoundInput {
  binding: CanvasBindingV2;
  node: CanvasNodeV2;
  asset: ProjectAssetSummaryV2 | null;
}

export interface EditingInputs {
  videos: EditingBoundInput[];
  bgm: EditingBoundInput | null;
}

function resolveNodeInput(
  workflow: AgentCanvasWorkflowV2,
  binding: CanvasBindingV2 | undefined,
  nodeType: "video" | "audio",
): EditingBoundInput | null {
  if (!binding || binding.source.kind !== "node") return null;
  const sourceNodeId = binding.source.node_id;
  const node = workflow.nodes.find((candidate) =>
    candidate.node_id === sourceNodeId
    && candidate.node_type === nodeType,
  );
  if (!node) return null;
  return {
    binding,
    node,
    asset: node.output_asset_id
      ? workflow.assets.find((candidate) => candidate.asset_id === node.output_asset_id) ?? null
      : null,
  };
}

export function buildEditingInputs(
  workflow: AgentCanvasWorkflowV2,
  editingNodeId: string,
  content: EditingNodeContentV2,
): EditingInputs {
  const inbound = new Map(
    workflow.bindings
      .filter((binding) => binding.target_node_id === editingNodeId)
      .map((binding) => [binding.binding_id, binding]),
  );
  const videos = content.manifest.ordered_video_binding_ids.flatMap((bindingId) => {
    const binding = inbound.get(bindingId);
    if (binding?.binding_kind !== "video_reference") return [];
    const resolved = resolveNodeInput(workflow, binding, "video");
    return resolved ? [resolved] : [];
  });
  const bgmBindingId = content.manifest.bgm_audio_binding_id;
  const bgmBinding = bgmBindingId ? inbound.get(bgmBindingId) : undefined;
  const bgm = bgmBinding?.binding_kind === "audio_reference"
    ? resolveNodeInput(workflow, bgmBinding, "audio")
    : null;
  return { videos, bgm };
}

export function moveEditingVideoBinding(
  manifest: EditingManifestV2,
  bindingId: string,
  offset: -1 | 1,
): EditingManifestV2 {
  const from = manifest.ordered_video_binding_ids.indexOf(bindingId);
  const to = from + offset;
  if (from < 0 || to < 0 || to >= manifest.ordered_video_binding_ids.length) {
    return manifest;
  }
  const ordered = [...manifest.ordered_video_binding_ids];
  [ordered[from], ordered[to]] = [ordered[to], ordered[from]];
  return { ...manifest, ordered_video_binding_ids: ordered };
}

export function replaceEditingManifest(
  _content: EditingNodeContentV2,
  manifest: EditingManifestV2,
): EditingManifestV2 {
  return {
    ...manifest,
    ordered_video_binding_ids: [...manifest.ordered_video_binding_ids],
    output: { ...manifest.output },
  };
}
