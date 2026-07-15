export type ScreenplayProductOption = {
  id: string;
  label?: string;
};

export type ScreenplayVersionTarget = {
  script_version_id: string;
  script_title: string;
};

export type ProductBeatRow = {
  key: string;
  value: string;
};

export function mergeProductOptions(
  supplied: readonly ScreenplayProductOption[],
  referencedIds: readonly string[],
): ScreenplayProductOption[] {
  const merged = new Map<string, ScreenplayProductOption>();
  supplied.forEach((option) => {
    if (option.id.trim()) merged.set(option.id, { id: option.id, label: option.label || option.id });
  });
  referencedIds.forEach((id) => {
    if (id.trim() && !merged.has(id)) merged.set(id, { id, label: id });
  });
  return [...merged.values()];
}

export function selectionGate(dirty: boolean, target: ScreenplayVersionTarget): { action: "select" | "confirm_discard"; target: ScreenplayVersionTarget } {
  return { action: dirty ? "confirm_discard" : "select", target };
}

export function nextFocusableIndex(index: number, count: number, backwards: boolean): number {
  if (count <= 0) return -1;
  return (index + (backwards ? -1 : 1) + count) % count;
}

export function nextTabIndex(key: string, index: number, count: number): number | null {
  if (key === "ArrowLeft") return nextFocusableIndex(index, count, true);
  if (key === "ArrowRight") return nextFocusableIndex(index, count, false);
  if (key === "Home") return 0;
  if (key === "End") return Math.max(0, count - 1);
  return null;
}

export function parsePositiveDuration(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export function draftDurationValue(value: string, _fallback: number): number {
  if (!value.trim()) return 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function versionSelectionFocusTarget({ failed, triggerEnabled }: { failed: boolean; triggerEnabled: boolean }): "trigger" | "stable" {
  return failed && triggerEnabled ? "trigger" : "stable";
}

export function createProductBeatRows(values: readonly string[], nextKey: () => string): ProductBeatRow[] {
  return values.map((value) => ({ key: nextKey(), value }));
}

export function reconcileProductBeatRows(
  current: readonly ProductBeatRow[],
  nextValues: readonly string[],
  nextKey: () => string,
): ProductBeatRow[] {
  const unused = [...current];
  return nextValues.map((value) => {
    const index = unused.findIndex((row) => row.value === value);
    if (index < 0) return { key: nextKey(), value };
    const [row] = unused.splice(index, 1);
    return row;
  });
}

export function summarizeValidationIssues<T extends { path: string; message: string }>(issues: readonly T[]): T[] {
  return issues.map((issue) => ({ ...issue }));
}
