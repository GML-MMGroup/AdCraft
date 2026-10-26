/** Stable source colors are visual identifiers, never execution-state indicators. */
const PALETTE = ["#CBB781", "#83ACD8", "#B09ACE", "#8DBAA9", "#C18C9F", "#D4A178"] as const;
export function canvasConnectionColor(sourceNodeId: string): string {
  let hash = 2166136261;
  for (const character of sourceNodeId) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
  return PALETTE[(hash >>> 0) % PALETTE.length];
}
