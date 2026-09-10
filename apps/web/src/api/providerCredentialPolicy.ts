import type {
  ProviderCapability,
  ProviderConnectionStatusV1,
} from "./providerRegistry.ts";

export const OPENROUTER_PROVIDER_ID = "openrouter";
export const OPENROUTER_SHARED_CAPABILITIES = ["text", "image"] as const;

export function usesSharedOpenRouterCredential(
  provider: ProviderConnectionStatusV1,
): boolean {
  return provider.provider_id === OPENROUTER_PROVIDER_ID
    && OPENROUTER_SHARED_CAPABILITIES.every((capability) => provider.capabilities.includes(capability));
}

export function updateCredentialDraftForProvider(
  provider: ProviderConnectionStatusV1,
  current: Partial<Record<ProviderCapability, string>>,
  capability: ProviderCapability,
  value: string,
): Partial<Record<ProviderCapability, string>> {
  if (!usesSharedOpenRouterCredential(provider)) {
    return { ...current, [capability]: value };
  }
  return { ...current, text: value, image: value };
}

export function clearCapabilitiesForProvider(
  provider: ProviderConnectionStatusV1,
  capability: ProviderCapability,
): ProviderCapability[] {
  return usesSharedOpenRouterCredential(provider)
    ? [...OPENROUTER_SHARED_CAPABILITIES]
    : [capability];
}
