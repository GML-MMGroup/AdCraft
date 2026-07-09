export type ApiProviderCategory = "text" | "image" | "video" | "audio" | "composition";
export type ApiProviderStatus = "available" | "coming_soon" | "disabled" | "misconfigured";
export type ApiKeyStatus = "not_configured" | "configured" | "unknown";

export type ApiProviderConfig = {
  provider_id: string;
  category: ApiProviderCategory;
  display_name: string;
  description: string;
  status: ApiProviderStatus;
  editable: boolean;
  model: string;
  base_url: string;
  api_key_status: ApiKeyStatus;
  parameters: {
    resolution?: "480p" | "720p" | "1080p";
    ratio?: "16:9" | "9:16" | "1:1";
    duration?: number;
    generate_audio?: boolean;
    watermark?: boolean;
  };
  advanced_json: Record<string, unknown>;
};

export type ApiProviderCategoryGroup = {
  category: ApiProviderCategory;
  label: string;
  summary: string;
  providers: ApiProviderConfig[];
};

export const API_SPACE_PROVIDER_CATALOG: ApiProviderCategoryGroup[] = [
  {
    category: "text",
    label: "Text",
    summary: "Script, prompt, and copywriting models.",
    providers: [comingSoonProvider("text_default", "Text providers", "Text provider configuration is coming soon.", "text")],
  },
  {
    category: "image",
    label: "Image",
    summary: "Character, scene, and storyboard image generation.",
    providers: [comingSoonProvider("image_default", "Image providers", "Image provider configuration is coming soon.", "image")],
  },
  {
    category: "video",
    label: "Video",
    summary: "Video generation models used by storyboard video nodes.",
    providers: [
      {
        provider_id: "volcengine_seedance",
        category: "video",
        display_name: "Seedance",
        description: "Demo configuration for the supported video generation provider.",
        status: "available",
        editable: true,
        model: "doubao-seedance",
        base_url: "",
        api_key_status: "not_configured",
        parameters: {
          resolution: "480p",
          ratio: "16:9",
          duration: 5,
          generate_audio: false,
          watermark: false,
        },
        advanced_json: {
          camera_fixed: false,
          provider: "volcengine",
          runtime: "demo",
        },
      },
    ],
  },
  {
    category: "audio",
    label: "Audio",
    summary: "BGM, sound effects, and voice model settings.",
    providers: [comingSoonProvider("audio_default", "Audio providers", "Audio provider configuration is coming soon.", "audio")],
  },
  {
    category: "composition",
    label: "Composition",
    summary: "Final video composition and export backends.",
    providers: [comingSoonProvider("composition_default", "Composition providers", "Composition provider configuration is coming soon.", "composition")],
  },
];

export const DEFAULT_SEEDANCE_PROVIDER = API_SPACE_PROVIDER_CATALOG
  .flatMap((group) => group.providers)
  .find((provider) => provider.provider_id === "volcengine_seedance") as ApiProviderConfig;

function comingSoonProvider(
  provider_id: string,
  display_name: string,
  description: string,
  category: ApiProviderCategory,
): ApiProviderConfig {
  return {
    provider_id,
    category,
    display_name,
    description,
    status: "coming_soon",
    editable: false,
    model: "",
    base_url: "",
    api_key_status: "unknown",
    parameters: {},
    advanced_json: {},
  };
}
