import type {
  AgentCanvasWorkflowV2,
  CanvasBindingV2,
  CanvasNodeV2,
  EditingBgmEntryV2,
  EditingManifestV2,
  EditingNodeContentV2,
  EditingVideoEntryV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";

export interface EditingBoundInput<TEntry extends EditingVideoEntryV2 | EditingBgmEntryV2> {
  referenceId: string;
  entry: TEntry;
  binding: CanvasBindingV2 | null;
  node: CanvasNodeV2 | null;
  asset: ProjectAssetSummaryV2 | null;
}

export interface EditingInputs {
  videos: Array<EditingBoundInput<EditingVideoEntryV2>>;
  bgm: EditingBoundInput<EditingBgmEntryV2> | null;
}

function resolveEntry<TEntry extends EditingVideoEntryV2 | EditingBgmEntryV2>(
  workflow: AgentCanvasWorkflowV2,
  inbound: Map<string, CanvasBindingV2>,
  entry: TEntry,
  mediaType: "video" | "audio",
): EditingBoundInput<TEntry> {
  const binding = entry.binding_id ? inbound.get(entry.binding_id) ?? null : null;
  const sourceNodeId = binding?.source.kind === "node_output"
    ? binding.source.source_node_id
    : null;
  const node = sourceNodeId
    ? workflow.nodes.find((candidate) => (
        candidate.node_id === sourceNodeId
        && candidate.node_type === mediaType
      )) ?? null
    : null;
  const assetId = entry.asset_id ?? node?.output_asset_id ?? null;
  const asset = assetId
    ? workflow.assets.find((candidate) => (
        candidate.asset_id === assetId && candidate.media_type === mediaType
      )) ?? null
    : null;
  return {
    referenceId: entry.binding_id ?? entry.asset_id!,
    entry,
    binding,
    node,
    asset,
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
  return {
    videos: content.manifest.video_entries.map((entry) => (
      resolveEntry(workflow, inbound, entry, "video")
    )),
    bgm: content.manifest.bgm
      ? resolveEntry(workflow, inbound, content.manifest.bgm, "audio")
      : null,
  };
}

export function moveEditingVideoEntry(
  manifest: EditingManifestV2,
  referenceId: string,
  offset: -1 | 1,
): EditingManifestV2 {
  const from = manifest.video_entries.findIndex((entry) => (
    (entry.binding_id ?? entry.asset_id) === referenceId
  ));
  const to = from + offset;
  if (from < 0 || to < 0 || to >= manifest.video_entries.length) {
    return manifest;
  }
  const videoEntries = [...manifest.video_entries];
  [videoEntries[from], videoEntries[to]] = [videoEntries[to], videoEntries[from]];
  return { ...manifest, video_entries: videoEntries };
}

export function reorderEditingVideoEntries(
  manifest: EditingManifestV2,
  orderedReferenceIds: readonly string[],
): EditingManifestV2 {
  const requested = new Set(orderedReferenceIds);
  const positions = manifest.video_entries.flatMap((entry, index) => {
    const referenceId = entry.binding_id ?? entry.asset_id;
    return referenceId && requested.has(referenceId) ? [{ index, referenceId }] : [];
  });
  if (positions.length < 2) return manifest;

  const entriesByReferenceId = new Map(
    manifest.video_entries.flatMap((entry) => {
      const referenceId = entry.binding_id ?? entry.asset_id;
      return referenceId && requested.has(referenceId) ? [[referenceId, entry] as const] : [];
    }),
  );
  const currentOrder = positions.map(({ referenceId }) => referenceId);
  const nextOrder = [
    ...orderedReferenceIds.filter((referenceId, index, ids) => (
      requested.has(referenceId)
      && entriesByReferenceId.has(referenceId)
      && ids.indexOf(referenceId) === index
    )),
    ...currentOrder.filter((referenceId) => !orderedReferenceIds.includes(referenceId)),
  ];
  if (nextOrder.every((referenceId, index) => referenceId === currentOrder[index])) return manifest;

  const videoEntries = [...manifest.video_entries];
  positions.forEach(({ index }, position) => {
    videoEntries[index] = entriesByReferenceId.get(nextOrder[position]!)!;
  });
  return { ...manifest, video_entries: videoEntries };
}

export function updateEditingVideoEntry(
  manifest: EditingManifestV2,
  referenceId: string,
  patch: Partial<EditingVideoEntryV2>,
): EditingManifestV2 {
  const index = manifest.video_entries.findIndex((entry) => (
    (entry.binding_id ?? entry.asset_id) === referenceId
  ));
  if (index < 0) return manifest;
  const videoEntries = manifest.video_entries.map((entry, entryIndex) => (
    entryIndex === index ? { ...entry, ...patch } : entry
  ));
  return { ...manifest, video_entries: videoEntries };
}

export function replaceEditingManifest(
  _content: EditingNodeContentV2,
  manifest: EditingManifestV2,
): EditingManifestV2 {
  return {
    ...manifest,
    video_entries: manifest.video_entries.map((entry) => ({ ...entry })),
    bgm: manifest.bgm ? { ...manifest.bgm } : null,
    output: { ...manifest.output },
  };
}
