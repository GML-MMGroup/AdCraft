import type {
  ActiveStyleSkillSummaryV2,
  AgentCanvasAssetMediaTypeV2,
  CanvasNodeTypeV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";

export interface ComposerSkillContext {
  title: string;
  summary: string;
}

export interface ComposerAssetContext {
  assetId: string;
  displayName: string;
  mediaType: AgentCanvasAssetMediaTypeV2;
  thumbnailUrl: string | null;
}

export interface ComposerNodeContext {
  nodeId: string;
  title: string;
  nodeType: CanvasNodeTypeV2;
}

export interface ComposerContextView {
  skill: ComposerSkillContext | null;
  assets: ComposerAssetContext[];
  nodes: ComposerNodeContext[];
  uploadState: "idle" | "uploading" | "failed";
}

export interface ComposerContextInput {
  activeStyle: ActiveStyleSkillSummaryV2 | null;
  assets: ProjectAssetSummaryV2[];
  nodes: CanvasNodeV2[];
  selectedAssetIds: string[];
  selectedNodeIds: string[];
  uploadState: ComposerContextView["uploadState"];
}

function unique(ids: string[]): string[] {
  return [...new Set(ids)];
}

export function buildComposerContextView(input: ComposerContextInput): ComposerContextView {
  const assetsById = new Map(input.assets.map((asset) => [asset.asset_id, asset]));
  const nodesById = new Map(input.nodes.map((node) => [node.node_id, node]));

  return {
    skill: input.activeStyle
      ? { title: input.activeStyle.title, summary: input.activeStyle.summary }
      : null,
    assets: unique(input.selectedAssetIds).flatMap((assetId) => {
      const asset = assetsById.get(assetId);
      return asset ? [{
        assetId: asset.asset_id,
        displayName: asset.display_name,
        mediaType: asset.media_type,
        thumbnailUrl: asset.preview_url ?? asset.media_url,
      }] : [];
    }),
    nodes: unique(input.selectedNodeIds).flatMap((nodeId) => {
      const node = nodesById.get(nodeId);
      return node ? [{ nodeId: node.node_id, title: node.title, nodeType: node.node_type }] : [];
    }),
    uploadState: input.uploadState,
  };
}

export function hasComposerContext(view: ComposerContextView): boolean {
  return Boolean(
    view.skill
    || view.assets.length
    || view.nodes.length
    || view.uploadState !== "idle",
  );
}
