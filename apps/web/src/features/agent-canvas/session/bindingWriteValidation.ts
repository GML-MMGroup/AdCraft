import type { CanvasBindingCreateRequestV2 } from "../../../types-v2.ts";

export function assertValidCanvasBindingWrite(request: CanvasBindingCreateRequestV2): void {
  if (request.source.kind !== "image_asset") return;
  if (!request.source.source_asset_id.trim()) {
    throw new Error("Image asset bindings require source_asset_id.");
  }
  if (!request.source.source_asset_version_id.trim()) {
    throw new Error("Image asset bindings require source_asset_version_id.");
  }
}
