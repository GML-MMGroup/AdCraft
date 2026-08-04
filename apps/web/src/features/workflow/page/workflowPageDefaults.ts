import { memo } from "react";
import type { AdRequest } from "../../../types";
import { WorkflowCanvasNode } from "../canvas/WorkflowCanvasNode.tsx";
import { areWorkflowCanvasNodePropsEqual } from "../canvas/WorkflowCanvasNodeModel.ts";
import type { AssetLibraryUploadKind } from "../../../types.ts";

export const DEBUG_LIST_PREVIEW_LIMIT = 12;
export const LOCAL_REVISION_HISTORY_PREVIEW_LIMIT = 12;

export const nodeTypes = {
  workflowNode: memo(WorkflowCanvasNode, areWorkflowCanvasNodePropsEqual),
};

export const defaultAdRequest: AdRequest = {
  product_name: "Lemon Tea",
  product_description: "A refreshing summer lemon tea drink",
  core_selling_point: "Fresh lemon aroma and cold thirst relief",
  target_audience: "Young office workers and students",
  campaign_goal: "Increase summer purchase conversion",
  desired_emotion: "fresh and lively",
  duration_seconds: 30,
  visual_style: "bright summer commercial",
  references: [],
  channels: ["social"],
  skip_audio_agents: false,
  audio_mode: "bgm_only",
  output_resolution: "480p",
  aspect_ratio: "16:9",
};

export const ASSET_LIBRARY_UPLOAD_KIND_OPTIONS: Array<{ value: AssetLibraryUploadKind; label: string }> = [
  { value: "", label: "Auto / Uploaded reference" },
  { value: "product", label: "Product reference" },
  { value: "character", label: "Character reference" },
  { value: "scene", label: "Scene reference" },
  { value: "style_reference", label: "Style reference" },
  { value: "bgm", label: "BGM / Audio" },
  { value: "storyboard_image", label: "Storyboard image" },
  { value: "storyboard_video", label: "Storyboard video" },
];
