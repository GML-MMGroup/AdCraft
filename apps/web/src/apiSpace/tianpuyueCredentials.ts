export type TianpuyueCredentialStatus = {
  configured: boolean;
  masked_api_key: string | null;
  source: "project_dotenv" | "process_environment" | "unconfigured" | string;
  test_capability: "unsupported" | string;
};

export type TianpuyueCredentialStatusResponse = {
  provider: "tianpuyue";
  credentials: {
    audio: TianpuyueCredentialStatus;
  };
};

export type TianpuyueCredentialUpdateRequest = {
  audio_api_key: string;
};

export type TianpuyueCredentialUpdateResponse = TianpuyueCredentialStatusResponse & {
  updated_consumers: Array<"audio">;
  applied: boolean;
  applied_at: string;
};

export function buildTianpuyueCredentialUpdateRequest(
  candidate: string,
): TianpuyueCredentialUpdateRequest | null {
  const audioApiKey = candidate.trim();
  return audioApiKey ? { audio_api_key: audioApiKey } : null;
}
