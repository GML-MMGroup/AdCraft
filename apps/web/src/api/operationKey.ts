export function createOperationKey(prefix: string): string {
  const suffix = (
    typeof crypto !== "undefined"
    && typeof crypto.randomUUID === "function"
  )
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${suffix}`;
}
