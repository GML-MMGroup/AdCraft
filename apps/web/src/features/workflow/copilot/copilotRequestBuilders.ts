import type { AssetLibraryReference, FrontDeskMessage, UploadedAsset } from "../../../types.ts";
import type { V2InputAssetUploadItem, V2PlanFromChatRequest, V2PlanFromPromptRequest } from "../../../types-v2.ts";

type InputAssetLocatorSource = string | Pick<V2InputAssetUploadItem, "locator">;

function inputAssetLocators(inputAssets: InputAssetLocatorSource[] = []) {
  return Array.from(new Set(inputAssets.map((asset) => typeof asset === "string" ? asset : asset.locator).filter((locator): locator is string => Boolean(locator?.trim()))));
}

export function buildV2PlanFromChatRequest(args: {
  message: string;
  history?: FrontDeskMessage[];
  inputAssets?: InputAssetLocatorSource[];
  selectedAssets?: UploadedAsset[];
  assetReferences?: AssetLibraryReference[];
  audioMode?: string;
  libraryEntityIds?: string[];
  referenceMode?: "best_effort" | "strict";
}): V2PlanFromChatRequest {
  return {
    message: args.message,
    history: args.history ?? [],
    input_asset_locators: inputAssetLocators(args.inputAssets),
    selected_assets: args.selectedAssets ?? [],
    asset_references: args.assetReferences ?? [],
    audio_mode: args.audioMode,
    library_entity_ids: args.libraryEntityIds ?? [],
    reference_mode: args.referenceMode ?? "strict",
  };
}

export function buildV2PlanFromPromptRequest(args: {
  prompt: string;
  product_name?: string | null;
  duration_seconds?: number;
  aspect_ratio?: string;
  inputAssets?: InputAssetLocatorSource[];
  selectedAssets?: UploadedAsset[];
  assetReferences?: AssetLibraryReference[];
  audioMode?: string;
  libraryEntityIds?: string[];
  referenceMode?: "best_effort" | "strict";
}): V2PlanFromPromptRequest {
  return {
    prompt: args.prompt,
    product_name: args.product_name,
    duration_seconds: args.duration_seconds,
    aspect_ratio: args.aspect_ratio,
    input_asset_locators: inputAssetLocators(args.inputAssets),
    selected_assets: args.selectedAssets ?? [],
    asset_references: args.assetReferences ?? [],
    audio_mode: args.audioMode,
    library_entity_ids: args.libraryEntityIds ?? [],
    reference_mode: args.referenceMode ?? "strict",
  };
}

export function buildCopilotChatReferences(args: {
  promptReferences?: AssetLibraryReference[];
  workflowReferences?: AssetLibraryReference[];
  contextReferences?: AssetLibraryReference[];
}): AssetLibraryReference[] {
  return [...(args.promptReferences ?? []), ...(args.workflowReferences ?? []), ...(args.contextReferences ?? [])];
}
