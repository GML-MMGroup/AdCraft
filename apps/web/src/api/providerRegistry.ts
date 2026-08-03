export const PROVIDER_CAPABILITIES = ["text", "image", "video", "audio"] as const;
export type ProviderCapability = (typeof PROVIDER_CAPABILITIES)[number];

export const MODEL_DEFAULT_PURPOSES = ["agent", "text", "image", "video", "audio"] as const;
export type ModelDefaultPurpose = (typeof MODEL_DEFAULT_PURPOSES)[number];

export type ProviderConnectionState = "configured" | "unconfigured" | "invalid";
export type ProviderCredentialSource = "project_dotenv" | "process_environment" | "unconfigured";
export type ProviderCredentialTestCapability = "minimal_request" | "unsupported";
export type ProviderModelAvailability = "available" | "unavailable" | "unauthorized" | "unsupported" | "deprecated";

export interface ProviderCredentialCapabilityStatusV1 {
  configured: boolean;
  fingerprint: string | null;
  source: ProviderCredentialSource;
  test_capability: ProviderCredentialTestCapability;
}

export interface ProviderConnectionStatusV1 {
  provider_id: string;
  display_name: string;
  capabilities: ProviderCapability[];
  connection_state: ProviderConnectionState;
  credentials: Partial<Record<ProviderCapability, ProviderCredentialCapabilityStatusV1>>;
  credential_revision: number;
  updated_at?: string | null;
}

export interface ProviderListResponseV1 {
  items: ProviderConnectionStatusV1[];
}

export interface ProviderCredentialUpdateRequestV1 {
  api_keys: Partial<Record<ProviderCapability, string>>;
  clear_capabilities: ProviderCapability[];
}

export interface ProviderCredentialUpdateResponseV1 {
  provider: ProviderConnectionStatusV1;
  updated_capabilities: ProviderCapability[];
  cleared_capabilities: ProviderCapability[];
  applied_at: string;
}

export interface ProviderCredentialTestRequestV1 {
  capability: ProviderCapability;
  model_ref?: string | null;
  api_key?: string | null;
}

export interface ProviderCredentialTestResponseV1 {
  provider_id: string;
  capability: ProviderCapability;
  accepted?: true;
  model_ref?: string | null;
  tested_at: string;
}

export interface ProviderModelSummaryV1 {
  model_ref: string;
  provider_id: string;
  provider_model_id: string;
  display_name: string;
  capability: "agent" | ProviderCapability;
  capability_metadata: Record<string, unknown>;
  availability: ProviderModelAvailability;
  unavailable_reason?: string | null;
  catalog_revision: number;
}

export interface ProviderModelListResponseV1 {
  items: ProviderModelSummaryV1[];
}

export interface ProviderModelQueryV1 {
  provider?: string;
  capability?: "agent" | ProviderCapability;
  node_type?: "text" | "script" | "image" | "video" | "audio" | "editing";
  purpose?: ModelDefaultPurpose;
  include_unavailable?: boolean;
}

export interface ProviderModelSyncResponseV1 {
  provider_id: string;
  sync_run_id: string;
  catalog_revision?: number | null;
  status?: "succeeded";
}

export interface ModelDefaultsResponseV1 {
  defaults: Partial<Record<ModelDefaultPurpose, string>>;
  revisions: Partial<Record<ModelDefaultPurpose, number>>;
}

export interface ModelDefaultsPatchRequestV1 {
  defaults: Partial<Record<ModelDefaultPurpose, string>>;
}

export function emptyProviderCredentialDraft(
  capabilities: readonly ProviderCapability[],
): Partial<Record<ProviderCapability, string>> {
  return Object.fromEntries(capabilities.map((capability) => [capability, ""]));
}

export function credentialUpdateFromDraft(
  draft: Partial<Record<ProviderCapability, string>>,
): ProviderCredentialUpdateRequestV1 | null {
  const api_keys = Object.fromEntries(
    Object.entries(draft)
      .map(([capability, value]) => [capability, value?.trim()] as const)
      .filter((entry): entry is [ProviderCapability, string] => (
        PROVIDER_CAPABILITIES.includes(entry[0] as ProviderCapability) && Boolean(entry[1])
      )),
  ) as Partial<Record<ProviderCapability, string>>;
  return Object.keys(api_keys).length ? { api_keys, clear_capabilities: [] } : null;
}

export function supportsCredentialTest(
  status: ProviderCredentialCapabilityStatusV1 | undefined,
): boolean {
  return status?.test_capability === "minimal_request";
}
