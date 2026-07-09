import { useCallback } from "react";
import { v2Api } from "../../../../api/v2Client.ts";
import type { V2StructuredChatTarget } from "../operations/v2SlotOperationTypes.ts";

const ASSET_LOCATOR_PATTERN = /asset:[A-Za-z0-9_-]+@[A-Za-z0-9_-]+/g;
export const V2_ASSET_LOCATOR_EXAMPLE = "asset:asset_id@version_id";

export function useV2AssetLocatorPaste(workflowId: string | null | undefined, onResolved: (target: V2StructuredChatTarget) => void) {
  return useCallback(async (text: string) => {
    if (!workflowId) return false;
    const locators = Array.from(new Set(text.match(ASSET_LOCATOR_PATTERN) ?? []));
    if (!locators.length) return false;
    for (const locator of locators) {
      const resolved = await v2Api.resolveLocator(workflowId, locator);
      const targetRecord = resolved.target && typeof resolved.target === "object" ? resolved.target as unknown as Record<string, unknown> : null;
      const targetDisplayName = typeof targetRecord?.display_name === "string" ? targetRecord.display_name.trim() : "";
      const displayName = resolved.owner?.owner_display_name || targetDisplayName || resolved.asset.semantic_type || resolved.asset.asset_id;
      onResolved({
        target_type: "asset",
        asset_id: resolved.asset.asset_id,
        version_id: resolved.asset.version_id,
        display_name: displayName,
        mention_text: `@${displayName}`,
      });
    }
    return true;
  }, [onResolved, workflowId]);
}

export { ASSET_LOCATOR_PATTERN };
