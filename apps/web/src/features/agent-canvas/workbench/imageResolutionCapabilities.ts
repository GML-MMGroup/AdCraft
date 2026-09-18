import type { ImageResolutionCapabilitiesV1 } from "../../../api/providerRegistry.ts";

export interface ImageResolutionIssue {
  name: string;
  message: string;
}

export const IMAGE_SIZE_PARAMETER = "size";
export const IMAGE_RESOLUTION_PARAMETER = "resolution";
export const IMAGE_ASPECT_RATIO_PARAMETER = "aspect_ratio";

const RESOLUTION_PARAMETER_NAMES = [
  IMAGE_SIZE_PARAMETER,
  IMAGE_RESOLUTION_PARAMETER,
  IMAGE_ASPECT_RATIO_PARAMETER,
];

export type ImageResolutionPairParameter =
  | typeof IMAGE_RESOLUTION_PARAMETER
  | typeof IMAGE_ASPECT_RATIO_PARAMETER;

export function imageResolutionParameter(
  parameters: Readonly<Record<string, unknown>>,
  name: string,
): string | undefined {
  const value = parameters[name];
  return typeof value === "string" && value ? value : undefined;
}

export function defaultImageResolutionParameter(
  capabilities: ImageResolutionCapabilitiesV1,
  name: string,
): string | undefined {
  const value = capabilities.default_parameters[name];
  return typeof value === "string" && value ? value : undefined;
}

export function imageResolutionPairOptions(
  capabilities: ImageResolutionCapabilitiesV1,
  name: ImageResolutionPairParameter,
): readonly string[] {
  return name === IMAGE_RESOLUTION_PARAMETER
    ? capabilities.resolution_options
    : capabilities.aspect_ratio_options;
}

/**
 * The paired mode must never submit only one of resolution/aspect_ratio, so a
 * half-filled pair is reported as an issue instead of being sent to the adapter.
 */
export function imageResolutionIssues(
  capabilities: ImageResolutionCapabilitiesV1,
  parameters: Readonly<Record<string, unknown>>,
): ImageResolutionIssue[] {
  if (!capabilities.parameter_modes.includes("resolution_with_aspect_ratio")) return [];
  const resolution = imageResolutionParameter(parameters, IMAGE_RESOLUTION_PARAMETER);
  const aspectRatio = imageResolutionParameter(parameters, IMAGE_ASPECT_RATIO_PARAMETER);
  if (resolution && !aspectRatio) {
    return [{
      name: IMAGE_ASPECT_RATIO_PARAMETER,
      message: "Choose an aspect ratio to send with the resolution.",
    }];
  }
  if (!resolution && aspectRatio) {
    return [{
      name: IMAGE_RESOLUTION_PARAMETER,
      message: "Choose a resolution to send with the aspect ratio.",
    }];
  }
  return [];
}

/**
 * Parameters saved for a previously selected model are rejected by the adapter
 * of the current one (a size on a resolution/aspect-ratio model, or the
 * reverse), so the draft drops the parameters this model does not declare.
 */
export function staleImageResolutionParameters(
  capabilities: ImageResolutionCapabilitiesV1,
  parameters: Readonly<Record<string, unknown>>,
): string[] {
  const accepted = new Set<string>();
  if (capabilities.parameter_modes.includes("size")) accepted.add(IMAGE_SIZE_PARAMETER);
  if (capabilities.parameter_modes.includes("resolution_with_aspect_ratio")) {
    accepted.add(IMAGE_RESOLUTION_PARAMETER);
    accepted.add(IMAGE_ASPECT_RATIO_PARAMETER);
  }
  return RESOLUTION_PARAMETER_NAMES.filter((name) => name in parameters && !accepted.has(name));
}
