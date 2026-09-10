import type { ModelParameterDescriptorV1 } from "../../../api/providerRegistry.ts";

export interface ModelParameterIssue {
  name: string;
  message: string;
}

function isUnset(value: unknown): boolean {
  return value === undefined || value === null || value === "";
}

function issueForValue(
  descriptor: ModelParameterDescriptorV1,
  value: unknown,
): string | null {
  if (isUnset(value)) {
    return descriptor.required ? "This parameter is required." : null;
  }
  if (descriptor.value_type === "enum") {
    return typeof value === "string" && descriptor.allowed_values.includes(value)
      ? null
      : `Choose one of: ${descriptor.allowed_values.join(", ")}.`;
  }
  if (descriptor.value_type === "boolean") {
    return typeof value === "boolean" ? null : "Choose enabled or disabled.";
  }
  if (descriptor.value_type === "string") {
    return typeof value === "string" ? null : "Enter a text value.";
  }
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "Enter a valid number.";
  }
  if (descriptor.value_type === "integer" && !Number.isInteger(value)) {
    return "Enter a whole number.";
  }
  if (descriptor.minimum !== null && value < descriptor.minimum) {
    return `Enter ${descriptor.minimum} or more.`;
  }
  if (descriptor.maximum !== null && value > descriptor.maximum) {
    return `Enter ${descriptor.maximum} or less.`;
  }
  return null;
}

export function validateModelParameters(
  descriptors: readonly ModelParameterDescriptorV1[],
  parameters: Readonly<Record<string, unknown>>,
): ModelParameterIssue[] {
  const issues: ModelParameterIssue[] = [];
  descriptors.forEach((descriptor) => {
    const message = issueForValue(descriptor, parameters[descriptor.name]);
    if (message) issues.push({ name: descriptor.name, message });
  });
  return issues;
}

export function modelParameterLabel(name: string): string {
  const words = name.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
