import type { VideoSkillPreviewV2, VideoSkillPublicDetailV2 } from "../../../types-v2.ts";

// Dedicated previews for creative methods that have no companion artwork.
const CREATIVE_METHOD_ARTWORK = new Set([
  "absence-reveal",
  "abstract-form-language",
  "absurd-meme-comedy",
  "attribute-backfire",
  "brand-pareidolia",
  "collectible-toy-world",
  "collision-montage",
  "consequence-chain",
  "counter-intuitive-correction",
  "emotional-micro-moment",
  "extreme-hyperbole",
  "genre-hijack",
  "identity-transformation",
  "interface-bleed",
  "literalized-idiom",
  "misdirection-reversal",
  "object-point-of-view",
  "parallel-lives",
  "private-ritual",
  "scale-shift",
  "self-aware-ad",
  "single-constraint-film",
  "surreal-displacement",
  "synesthetic-translation",
  "time-loop",
  "visual-metaphor",
  "world-hopping-relay",
]);

// Authored companion pairs from the backend's seed/creative_method_skills and
// agent/video-skills packages. This only shares artwork; selection stays independent.
const COMPANION_STYLE: Readonly<Record<string, string>> = {
  "summer-sensory-use-moment": "japanese-summer-sensory-film",
  "streetwear-identity-journey": "2000s-street-fashion-film",
  "product-triggered-world-expansion": "surreal-cinematic-product-worlds",
  "product-playground-odyssey": "sunlit-pastel-product-fantasy",
  "miniature-artisan-ritual": "golden-macro-patisserie",
  "uncanny-testimony-reveal": "suspense-to-sensory-release",
  "doctor-patient-reversal": "clinic-suspense-comedy",
  "authority-to-advocate": "costume-comedy-live-action",
  "melodrama-commerce-reversal": "melodrama-commerce-film",
  "interruption-to-offer-reversal": "whip-pan-promo-ambush",
};

export function creativeMethodPreview(skillId: string, styles: readonly VideoSkillPublicDetailV2[]): VideoSkillPreviewV2 | null {
  if (CREATIVE_METHOD_ARTWORK.has(skillId)) {
    return { kind: "image", summary: null, media_url: `/imgs/creative-skills/${skillId}.webp` };
  }
  const styleId = COMPANION_STYLE[skillId];
  return (styleId ? styles.find(style => style.skill_id === styleId)?.preview : null) ?? null;
}
