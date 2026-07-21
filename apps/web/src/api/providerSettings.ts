export type ProviderCredentialConsumer = "llm" | "image" | "video";
export type CredentialSource = "project_dotenv" | "process_environment" | "unconfigured";
export type CredentialTestCapability = "minimal_request" | "unsupported";

export type ProviderCredentialConsumerStatus = {
  configured: boolean;
  masked_api_key: string | null;
  source: CredentialSource;
  test_capability: CredentialTestCapability;
};

export type ProviderCredentialStatusResponse = {
  provider: "volcengine_ark";
  credentials: Record<ProviderCredentialConsumer, ProviderCredentialConsumerStatus>;
};

export type ProviderCredentialUpdateRequest = Partial<Record<`${ProviderCredentialConsumer}_api_key`, string>>;

export type ProviderCredentialUpdateResponse = ProviderCredentialStatusResponse & {
  updated_consumers: ProviderCredentialConsumer[];
  applied: true;
  applied_at: string;
};

export type ProviderCredentialTestRequest = {
  consumer: ProviderCredentialConsumer;
  api_key?: string;
};

export type ProviderCredentialTestResponse = {
  provider: "volcengine_ark";
  accepted: true;
  tested_consumer: ProviderCredentialConsumer;
  model_id: string | null;
  tested_at: string;
};
