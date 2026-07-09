import { useCallback } from "react";
import { formatV2AssetLocator } from "../operations/v2SlotOperationModel.ts";

export function useV2MediaContextMenu() {
  return useCallback(async (assetId: string, versionId: string) => {
    const locator = formatV2AssetLocator(assetId, versionId);
    if (locator && typeof navigator !== "undefined" && navigator.clipboard) {
      await navigator.clipboard.writeText(locator);
    }
    return locator;
  }, []);
}
