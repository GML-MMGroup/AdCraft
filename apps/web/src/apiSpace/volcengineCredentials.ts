export const VOLCENGINE_CREDENTIAL_CONSUMERS = ["llm", "image", "video"] as const;

export type VolcengineCredentialConsumer = (typeof VOLCENGINE_CREDENTIAL_CONSUMERS)[number];
export type VolcengineCredentialTestCapability = "minimal_request" | "minimal_llm_request" | "unsupported" | string;

export type VolcengineCredentialStatus = {
  configured: boolean;
  masked_api_key: string | null;
  source: "project_dotenv" | "process_environment" | "unconfigured" | string;
  test_capability: VolcengineCredentialTestCapability;
};

export type VolcengineCredentialStatusResponse = {
  provider: "volcengine_ark" | string;
  credentials: Record<VolcengineCredentialConsumer, VolcengineCredentialStatus>;
};

export type VolcengineCredentialUpdateRequest = {
  llm_api_key?: string;
  image_api_key?: string;
  video_api_key?: string;
};

export type VolcengineCredentialUpdateResponse = VolcengineCredentialStatusResponse & {
  updated_consumers: VolcengineCredentialConsumer[];
  applied: boolean;
  applied_at: string;
};

export type VolcengineCredentialTestRequest = {
  consumer: VolcengineCredentialConsumer;
  api_key?: string;
};

export type VolcengineCredentialTestResponse = {
  provider: "volcengine_ark" | string;
  accepted: boolean;
  tested_consumer: VolcengineCredentialConsumer;
  model_id?: string | null;
  tested_at: string;
};

export type VolcengineCredentialDraft = Record<VolcengineCredentialConsumer, string>;

const REQUEST_FIELD_BY_CONSUMER: Record<VolcengineCredentialConsumer, keyof VolcengineCredentialUpdateRequest> = {
  llm: "llm_api_key",
  image: "image_api_key",
  video: "video_api_key",
};

export function emptyVolcengineCredentialDraft(): VolcengineCredentialDraft {
  return { llm: "", image: "", video: "" };
}

export function buildVolcengineCredentialUpdateRequest(
  draft: VolcengineCredentialDraft,
): VolcengineCredentialUpdateRequest {
  const request: VolcengineCredentialUpdateRequest = {};

  for (const consumer of VOLCENGINE_CREDENTIAL_CONSUMERS) {
    const value = draft[consumer].trim();
    if (value) request[REQUEST_FIELD_BY_CONSUMER[consumer]] = value;
  }

  return request;
}

export function hasVolcengineCredentialUpdate(request: VolcengineCredentialUpdateRequest) {
  return Boolean(request.llm_api_key || request.image_api_key || request.video_api_key);
}

export function supportsVolcengineCredentialTest(capability: VolcengineCredentialTestCapability | undefined) {
  return capability === "minimal_request" || capability === "minimal_llm_request";
}
