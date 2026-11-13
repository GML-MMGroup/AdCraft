import type { ProviderModelSummaryV1 } from "../../../api/providerRegistry.ts";

type ModelIdentity = Pick<ProviderModelSummaryV1, "model_ref" | "provider_model_id">;

export interface ModelBrandIcon {
  src: string;
  monochrome: boolean;
  wordmark?: boolean;
}

// Match the original model family, including models served by routing providers.
// Asset provenance is recorded in public/model-logos/README.md.
const brands: ReadonlyArray<{ family: RegExp; icon: ModelBrandIcon }> = [
  { family: /(?:^|[:/\s])(?:gpt|chatgpt|sora)(?:[-\s/]|$)/, icon: { src: "/model-logos/openai.svg", monochrome: true } },
  { family: /(?:^|[:/\s])glm(?:[-\s/]|$)/, icon: { src: "/model-logos/zai.svg", monochrome: false } },
  { family: /(?:^|[:/\s])(?:doubao|seedance|seedream|seed)(?:[-\s/]|$)/, icon: { src: "/model-logos/bytedance.svg", monochrome: true } },
  { family: /(?:^|[:/\s])(?:minimax-hailuo|hailuo)(?:[-\s/]|$)/, icon: { src: "/model-logos/hailuo.svg", monochrome: false } },
  { family: /(?:^|[:/\s])tempolor(?:[-\s/]|$)/, icon: { src: "/model-logos/tempolor.svg", monochrome: true, wordmark: true } },
];

export function modelBrandIcon(model: ModelIdentity | null | undefined): ModelBrandIcon | null {
  if (!model) return null;
  const identity = `${model.provider_model_id} ${model.model_ref}`.toLowerCase();
  return brands.find(brand => brand.family.test(identity))?.icon ?? null;
}
