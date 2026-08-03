import { ApiError } from "../../api/client.ts";

export type ApiSpaceNotice = { kind: "success" | "error"; message: string } | null;

export function providerRegistryErrorMessage(
  error: unknown,
  operation: "load" | "save" | "test" | "sync" | "defaults",
): string {
  const code = providerRegistryErrorCode(error);
  if (code === "local_settings_access_denied") {
    return "This browser is not allowed to manage local credentials.";
  }
  if (code === "credential_update_invalid") {
    return "Enter a valid non-empty key without line breaks.";
  }
  if (code === "credential_update_conflict") {
    return "Another credential update is in progress. Try again shortly.";
  }
  if (code === "credential_persistence_failed" || code === "credential_runtime_reload_failed") {
    return "The backend could not apply this credential update.";
  }
  if (code === "credential_not_configured") {
    return "Enter a key here or save one before testing.";
  }
  if (code === "credential_test_not_supported") {
    return "This provider capability cannot be safely tested here.";
  }
  if (code === "credential_test_configuration_invalid") {
    return "The backend provider test configuration is invalid.";
  }
  if (code === "credential_test_failed") {
    return "The provider rejected this credential.";
  }
  if (code === "provider_test_unavailable") {
    return "The provider is temporarily unavailable. Try again later.";
  }
  if (code === "model_catalog_sync_failed") {
    return "Model synchronization failed. Existing model choices were kept.";
  }
  if (code === "model_capability_mismatch") {
    return "This model cannot be used for the selected default.";
  }
  if (code === "model_unavailable") {
    return "This model is currently unavailable.";
  }
  if (error instanceof ApiError && error.status === 403) {
    return "This browser is not allowed to manage local credentials.";
  }
  if (error instanceof ApiError && error.status === 404) {
    return "This backend does not provide the provider registry yet.";
  }
  if (operation === "load") return "Unable to load provider settings. Check that the local backend is running.";
  if (operation === "sync") return "Unable to synchronize this provider's models.";
  if (operation === "defaults") return "Unable to save default models.";
  if (operation === "test") return "Unable to test this credential.";
  return "Unable to save credentials. No changes were confirmed.";
}

function providerRegistryErrorCode(error: unknown): string {
  if (!(error instanceof ApiError) || !error.payload || typeof error.payload !== "object") return "";
  const detail = (error.payload as { detail?: unknown }).detail;
  return detail && typeof detail === "object" && typeof (detail as { code?: unknown }).code === "string"
    ? (detail as { code: string }).code
    : "";
}
