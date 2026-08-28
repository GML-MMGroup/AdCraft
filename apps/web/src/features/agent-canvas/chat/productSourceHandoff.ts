export interface ProductMainHandoff {
  workflowId: string;
  assetId: string;
  versionId: string;
  pendingHandoffId: string | null;
  displayName: string;
  previewUrl: string | null;
}

function storageKey(workflowId: string): string {
  return `adcraft:product-main-handoff:${workflowId}`;
}

function isProductMainHandoff(value: unknown, workflowId: string): value is ProductMainHandoff {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return record.workflowId === workflowId
    && typeof record.assetId === "string"
    && record.assetId.trim().length > 0
    && typeof record.versionId === "string"
    && record.versionId.trim().length > 0
    && (record.pendingHandoffId === null
      || (typeof record.pendingHandoffId === "string" && record.pendingHandoffId.trim().length > 0))
    && typeof record.displayName === "string"
    && record.displayName.trim().length > 0
    && (record.previewUrl === null || typeof record.previewUrl === "string");
}

export function readProductMainHandoff(workflowId: string): ProductMainHandoff | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(storageKey(workflowId));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (isProductMainHandoff(parsed, workflowId)) return parsed;
    window.sessionStorage.removeItem(storageKey(workflowId));
  } catch {
    // Storage is an optional browser convenience; backend identities remain authoritative.
  }
  return null;
}

export function writeProductMainHandoff(handoff: ProductMainHandoff): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(storageKey(handoff.workflowId), JSON.stringify(handoff));
  } catch {
    // Quota/privacy restrictions must not block the upload or guided submit.
  }
}

export function clearProductMainHandoff(workflowId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(storageKey(workflowId));
  } catch {
    // Storage is best effort only.
  }
}
