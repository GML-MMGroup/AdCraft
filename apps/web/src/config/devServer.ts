const DEFAULT_BACKEND_ORIGIN = "http://127.0.0.1:8000";

export function resolveBackendOrigin(value: string | undefined): string {
  return value?.trim() || DEFAULT_BACKEND_ORIGIN;
}
