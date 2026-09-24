import type { ImageResolutionCapabilitiesV1 } from "../../../api/providerRegistry.ts";
import {
  defaultImageResolutionParameter,
  IMAGE_ASPECT_RATIO_PARAMETER,
  IMAGE_RESOLUTION_PARAMETER,
  IMAGE_SIZE_PARAMETER,
  imageResolutionIssues,
  imageResolutionPairOptions,
  imageResolutionParameter,
  type ImageResolutionPairParameter,
} from "./imageResolutionCapabilities.ts";
import { InlineParameterSelect } from "./InlineParameterSelect.tsx";

function parameterSelect({
  label,
  name,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string;
  name: string;
  value: string;
  options: readonly string[];
  disabled: boolean;
  onChange: (value: string | undefined) => void;
}) {
  return (
    <div className="agent-node-workbench__parameter" key={name}>
      <span title={label}>{label}</span>
      <InlineParameterSelect
        label={label}
        value={value}
        options={options}
        disabled={disabled}
        onChange={onChange}
      />
    </div>
  );
}

export function ImageResolutionControls({
  capabilities,
  parameters,
  disabled,
  onChange,
  layout = "default",
}: {
  capabilities: ImageResolutionCapabilitiesV1;
  parameters: Readonly<Record<string, unknown>>;
  disabled: boolean;
  onChange: (parameters: Record<string, unknown>) => void;
  layout?: "default" | "inline";
}) {
  const modes = capabilities.parameter_modes;
  const issues = imageResolutionIssues(capabilities, parameters);
  const issueByName = new Map(issues.map((issue) => [issue.name, issue.message]));

  const selectSize = (value: string) => {
    const next = { ...parameters };
    delete next[IMAGE_RESOLUTION_PARAMETER];
    delete next[IMAGE_ASPECT_RATIO_PARAMETER];
    if (value) next[IMAGE_SIZE_PARAMETER] = value;
    else delete next[IMAGE_SIZE_PARAMETER];
    onChange(next);
  };

  const selectPair = (name: ImageResolutionPairParameter, value: string) => {
    const otherName: ImageResolutionPairParameter = name === IMAGE_RESOLUTION_PARAMETER
      ? IMAGE_ASPECT_RATIO_PARAMETER
      : IMAGE_RESOLUTION_PARAMETER;
    // A resolution without its aspect ratio (or the reverse) is rejected by the
    // adapter, so the counterpart falls back to its default or first option.
    const otherValue = imageResolutionParameter(parameters, otherName)
      ?? defaultImageResolutionParameter(capabilities, otherName)
      ?? imageResolutionPairOptions(capabilities, otherName)[0];
    const next = { ...parameters };
    delete next[IMAGE_SIZE_PARAMETER];
    if (value) next[name] = value;
    else delete next[name];
    if (otherValue) next[otherName] = otherValue;
    else delete next[otherName];
    onChange(next);
  };

  return (
    <div className={`agent-node-workbench__model-parameters${layout === "inline" ? " agent-node-workbench__model-parameters--inline" : ""}`} aria-label="Image resolution">
      {modes.includes("size")
        ? parameterSelect({
          label: "Size",
          name: IMAGE_SIZE_PARAMETER,
          value: imageResolutionParameter(parameters, IMAGE_SIZE_PARAMETER)
            ?? defaultImageResolutionParameter(capabilities, IMAGE_SIZE_PARAMETER)
            ?? (capabilities.size_options.includes("2048x2048") ? "2048x2048" : capabilities.size_options[0] ?? ""),
          options: capabilities.size_options,
          disabled,
          onChange: (value) => selectSize(value ?? ""),
        })
        : null}
      {modes.includes("resolution_with_aspect_ratio")
        ? ([IMAGE_RESOLUTION_PARAMETER, IMAGE_ASPECT_RATIO_PARAMETER] as const).map((name) => (
          <div key={name}>
            {parameterSelect({
              label: name === IMAGE_RESOLUTION_PARAMETER ? "Resolution" : "Ratio",
              name,
              value: imageResolutionParameter(parameters, name)
                ?? defaultImageResolutionParameter(capabilities, name)
                ?? "",
              options: imageResolutionPairOptions(capabilities, name),
              disabled,
              onChange: (value) => selectPair(name, value ?? ""),
            })}
            {issueByName.get(name) ? (
              <p className="agent-node-workbench__field-error">{issueByName.get(name)}</p>
            ) : null}
          </div>
        ))
        : null}
    </div>
  );
}
